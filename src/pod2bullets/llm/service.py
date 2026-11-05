"""Multi-provider LLM text summarization service (ChatGPT, Claude, Gemini, DeepSeek, Qwen).
Strictly summarizes locally generated text transcripts (no audio/MP3 uploads to external APIs).
Always tries the newest model/API version first, dynamically discovers available models from the
provider's API when needed, and logs/displays each attempt and fallback clearly.
"""

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from pod2bullets.db.repository import Repository
from pod2bullets.models import TranscriptSummary
from pod2bullets.naming import slugify
from pod2bullets.system_status import activity_tracker

logger = logging.getLogger("pod2bullets.llm")

DEFAULT_SUMMARY_PROMPT = (
    "Você é um especialista em síntese de podcasts. Analise a transcrição a seguir e elabore "
    "um resumo estruturado em português contendo:\n"
    "1. **Resumo Executivo (TL;DR):** 2 a 3 frases explicando o tema central do episódio.\n"
    "2. **Principais Pontos (Bullets):** Os tópicos, dados, histórias e argumentos mais importantes.\n"
    "3. **Destaques e Conclusões:** Insights práticos e aprendizados finais do episódio."
)

# Retired/deprecated model aliases mapped automatically to the newest recommended model
DEPRECATED_MODEL_UPGRADES: dict[str, dict[str, str]] = {
    "claude": {
        "claude-sonnet-4-0": "claude-sonnet-4-6",
        "claude-3-7-sonnet-latest": "claude-sonnet-4-6",
        "claude-3-5-sonnet-latest": "claude-sonnet-4-6",
        "claude-3-5-haiku-latest": "claude-haiku-4-5",
    },
    "gemini": {
        "gemini-1.5-flash": "gemini-2.5-flash",
        "gemini-1.5-pro": "gemini-2.5-pro",
        "gemini-3.6-flash": "gemini-2.5-flash",
    },
    "chatgpt": {
        "gpt-3.5-turbo": "gpt-4.1-mini",
    },
}

QWEN_REGIONAL_URLS = [
    ("Intl (Singapura)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"),
    ("US (Virgínia)", "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"),
    ("CN (Pequim)", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
]

DEEPSEEK_API_URLS = [
    ("v1", "https://api.deepseek.com/v1/chat/completions"),
    ("v1-root", "https://api.deepseek.com/chat/completions"),
]

GEMINI_API_VERSIONS = ["v1beta", "v1"]
CLAUDE_API_VERSIONS = ["2023-06-01"]

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "id": "gemini",
        "name": "Gemini (Google)",
        "default_model": "gemini-2.5-flash",
        "suggested_models": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-flash-latest",
        ],
        "base_url": "https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent",
        "models_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "env_key": "GEMINI_API_KEY",
    },
    "claude": {
        "id": "claude",
        "name": "Claude (Anthropic)",
        "default_model": "claude-sonnet-4-6",
        "suggested_models": [
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-sonnet-4-20250514",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-haiku-20240307",
        ],
        "base_url": "https://api.anthropic.com/v1/messages",
        "models_url": "https://api.anthropic.com/v1/models",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "chatgpt": {
        "id": "chatgpt",
        "name": "ChatGPT (OpenAI)",
        "default_model": "gpt-4.1-mini",
        "suggested_models": [
            "gpt-4.1-mini",
            "gpt-4.1",
            "gpt-4o-mini",
            "gpt-4o",
        ],
        "base_url": "https://api.openai.com/v1/chat/completions",
        "models_url": "https://api.openai.com/v1/models",
        "env_key": "OPENAI_API_KEY",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "suggested_models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "models_url": "https://api.deepseek.com/models",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "id": "qwen",
        "name": "Qwen (Alibaba DashScope)",
        "default_model": "qwen-plus",
        "suggested_models": [
            "qwen-plus",
            "qwen-max",
            "qwen-turbo",
            "qwen-long",
        ],
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "models_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
        "env_key": "DASHSCOPE_API_KEY",
    },
}


class LLMSummaryError(RuntimeError):
    """Structured error raised when an LLM summarization fails after trying available models/versions."""

    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def _extract_api_error_detail(resp: httpx.Response) -> str:
    """Extract a concise human-readable error message from a provider's JSON response."""
    detail = resp.text[:300].strip()
    try:
        err_json = resp.json()
        if isinstance(err_json, dict):
            if "error" in err_json:
                err_obj = err_json["error"]
                if isinstance(err_obj, dict) and "message" in err_obj:
                    detail = str(err_obj["message"])
                else:
                    detail = str(err_obj)
            elif "message" in err_json:
                detail = str(err_json["message"])
    except Exception:
        pass
    return detail


def _friendly_status_explanation(status_code: int, provider_name: str, detail: str) -> str:
    """Translate HTTP status codes from LLM APIs into actionable Portuguese messages."""
    if status_code == 401:
        return f"Chave de API inválida ou expirada em {provider_name} (HTTP 401): {detail}"
    if status_code == 402:
        return f"Saldo/créditos insuficientes na conta {provider_name} (HTTP 402): {detail}"
    if status_code == 403:
        return f"Acesso negado pela API {provider_name} (HTTP 403 - verifique permissões/região da chave): {detail}"
    if status_code == 404:
        return (
            f"Modelo ou versão de endpoint não encontrado em {provider_name} (HTTP 404): {detail}"
        )
    if status_code == 429:
        return f"Limite de requisições ou cota excedida em {provider_name} (HTTP 429): {detail}"
    if status_code >= 500:
        return f"Servidor da API {provider_name} temporariamente sobrecarregado (HTTP {status_code}): {detail}"
    return f"Erro HTTP {status_code} na API {provider_name}: {detail}"


def _sanitize_api_key(raw_key: str | None) -> str:
    """Clean whitespace/zero-width chars from API key and reject non-ASCII or multi-word prose."""
    if not raw_key:
        return ""
    cleaned = (
        raw_key.strip()
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
        .replace("\xa0", "")
    )
    if not cleaned:
        return ""
    if "..." in cleaned or "•" in cleaned or cleaned == "Configurada":
        return ""
    if any(ch.isspace() for ch in cleaned) or not cleaned.isascii():
        return ""
    return cleaned


class LLMService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(connect=25.0, read=300.0, write=120.0, pool=25.0)
        )
        self._last_attempts_report: list[str] = []

    def get_config(self) -> dict[str, Any]:
        """Return current LLM configuration, registered providers, and last selected provider."""
        active_provider = self.repo.get_setting("llm_provider", "gemini") or "gemini"
        if active_provider not in LLM_PROVIDERS and active_provider != "none":
            active_provider = "gemini"

        last_direct_provider = (
            self.repo.get_setting("llm_direct_provider", active_provider) or active_provider
        )
        if last_direct_provider not in LLM_PROVIDERS and last_direct_provider != "none":
            last_direct_provider = active_provider if active_provider in LLM_PROVIDERS else "gemini"

        prompt = (
            self.repo.get_setting("llm_prompt", DEFAULT_SUMMARY_PROMPT) or DEFAULT_SUMMARY_PROMPT
        )

        providers_cfg: dict[str, dict[str, Any]] = {}
        registered_list: list[dict[str, Any]] = []

        for pid, meta in LLM_PROVIDERS.items():
            raw_saved = self.repo.get_setting(f"llm_api_key_{pid}", "") or ""
            saved_key = _sanitize_api_key(raw_saved)
            if raw_saved and not saved_key:
                self.clear_api_key(pid)

            saved_model = (
                self.repo.get_setting(f"llm_model_{pid}", meta["default_model"])
                or meta["default_model"]
            ).strip()

            # Automatically migrate retired model IDs to the newest model
            upgrades = DEPRECATED_MODEL_UPGRADES.get(pid, {})
            if saved_model in upgrades:
                new_model = upgrades[saved_model]
                logger.info(
                    f"[LLM] Atualizando modelo antigo '{saved_model}' de {meta['name']} "
                    f"para o mais recente '{new_model}'."
                )
                saved_model = new_model
                self.repo.set_setting(f"llm_model_{pid}", saved_model)

            entry = {
                **meta,
                "model": saved_model,
                "has_key": bool(saved_key),
                "masked_key": (
                    f"{saved_key[:4]}...{saved_key[-4:]}"
                    if len(saved_key) > 8
                    else ("Configurada" if saved_key else "")
                ),
                "api_key": saved_key,
            }
            providers_cfg[pid] = entry
            if saved_key:
                registered_list.append(entry)

        if (
            last_direct_provider != "none"
            and registered_list
            and not providers_cfg.get(last_direct_provider, {}).get("has_key")
        ):
            last_direct_provider = registered_list[0]["id"]

        return {
            "active_provider": active_provider if active_provider in LLM_PROVIDERS else "gemini",
            "last_direct_provider": last_direct_provider,
            "prompt": prompt,
            "providers": providers_cfg,
            "registered_providers": registered_list,
        }

    def set_last_direct_provider(self, provider: str) -> None:
        """Remember the user's last selected LLM provider (or 'none' for transcription-only)."""
        if provider == "none" or provider in LLM_PROVIDERS:
            self.repo.set_setting("llm_direct_provider", provider)
            if provider in LLM_PROVIDERS:
                self.repo.set_setting("llm_provider", provider)

    def save_config(
        self,
        provider: str,
        prompt: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Persist LLM provider, custom prompt, model name, and optional API key via GUI."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor LLM inválido: {provider}")

        self.repo.set_setting("llm_provider", provider)
        self.repo.set_setting("llm_direct_provider", provider)
        if prompt is not None and prompt.strip():
            self.repo.set_setting("llm_prompt", prompt.strip())
        if model_name is not None and model_name.strip():
            clean_m = model_name.strip().removeprefix("models/")
            clean_m = DEPRECATED_MODEL_UPGRADES.get(provider, {}).get(clean_m, clean_m)
            self.repo.set_setting(f"llm_model_{provider}", clean_m)
        if api_key is not None and api_key.strip():
            clean_key = _sanitize_api_key(api_key)
            if not clean_key:
                raise ValueError(
                    "A API Key informada é inválida (contém espaços, acentos ou caracteres não-ASCII). "
                    "Cole apenas o token da chave de API."
                )
            self.repo.set_setting(f"llm_api_key_{provider}", clean_key)

        logger.info(
            f"[LLM] Configuração salva via GUI: provedor='{provider}', "
            f"modelo='{model_name or LLM_PROVIDERS[provider]['default_model']}'"
        )

    def save_prompt_only(self, prompt: str) -> None:
        """Save only the customizable summarization prompt."""
        if prompt and prompt.strip():
            self.repo.set_setting("llm_prompt", prompt.strip())
            logger.info(f"[LLM] Prompt customizável atualizado ({len(prompt.strip())} chars).")

    def clear_api_key(self, provider: str | None = None) -> None:
        """Delete stored API key(s) from SQLite settings."""
        cur = self.repo.conn.cursor()
        if provider:
            cur.execute("DELETE FROM settings WHERE key = ?", (f"llm_api_key_{provider}",))
            logger.info(f"[LLM] Chave de API removida para o provedor '{provider}'.")
        else:
            cur.execute("DELETE FROM settings WHERE key LIKE 'llm_api_key_%'")
            logger.info("[LLM] Todas as chaves de API foram removidas.")
        self.repo.conn.commit()

    def _discover_live_models(self, provider: str, api_key: str) -> list[str]:
        """Query the provider's /models endpoint to discover active models on the user's account, newest first."""
        meta = LLM_PROVIDERS.get(provider, {})
        models_url = meta.get("models_url")
        if not models_url:
            return []

        try:
            if provider == "gemini":
                resp = self.client.get(models_url, headers={"x-goog-api-key": api_key})
                if resp.status_code != 200:
                    return []
                items = resp.json().get("models", [])
                names: list[str] = []
                for it in items:
                    methods = it.get("supportedGenerationMethods", [])
                    name = str(it.get("name", "")).removeprefix("models/")
                    if (
                        "generateContent" in methods
                        and name.startswith("gemini-")
                        and "embedding" not in name
                        and "tts" not in name
                        and "image" not in name
                        and "vision" not in name
                    ):
                        names.append(name)
                # Sort newest versions first (e.g. gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash)
                names.sort(key=lambda x: ("flash" in x, x), reverse=True)
                return names[:6]

            if provider == "claude":
                resp = self.client.get(
                    models_url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code != 200:
                    return []
                # Anthropic /v1/models returns models already sorted newest-first!
                items = resp.json().get("data", [])
                return [str(it["id"]) for it in items if isinstance(it, dict) and it.get("id")][:6]

            if provider in ("chatgpt", "deepseek", "qwen"):
                resp = self.client.get(
                    models_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code != 200:
                    return []
                items = resp.json().get("data", [])
                ids = [str(it["id"]) for it in items if isinstance(it, dict) and it.get("id")]
                if provider == "chatgpt":
                    preferred = [
                        m
                        for m in ids
                        if m.startswith(("gpt-4.1", "gpt-4o", "o3", "o4"))
                        and "audio" not in m
                        and "realtime" not in m
                        and "transcribe" not in m
                        and "tts" not in m
                    ]
                    preferred.sort(reverse=True)
                    return preferred[:6]
                return ids[:6]
        except Exception as exc:
            logger.debug(f"[LLM] Não foi possível consultar catálogo ao vivo de {provider}: {exc}")
        return []

    def _build_candidate_chain(self, provider: str, preferred_model: str) -> list[str]:
        """Build ordered list of candidate models starting with the newest/preferred model, then fallbacks."""
        meta = LLM_PROVIDERS[provider]
        clean_pref = preferred_model.strip().removeprefix("models/")
        clean_pref = DEPRECATED_MODEL_UPGRADES.get(provider, {}).get(clean_pref, clean_pref)

        chain: list[str] = []
        # 1. Start with the newest default model or user's chosen model
        for m in [clean_pref, meta["default_model"], *meta["suggested_models"]]:
            if m and m not in chain:
                chain.append(m)
        return chain

    def _call_gemini_with_fallback(
        self,
        preferred_model: str,
        api_key: str,
        full_user_message: str,
    ) -> tuple[str, str, list[str]]:
        """Try Gemini models from newest to older across API versions (v1beta -> v1)."""
        candidates = self._build_candidate_chain("gemini", preferred_model)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {"contents": [{"parts": [{"text": full_user_message}]}]}
        attempts_log: list[str] = []
        discovered_added = False

        idx = 0
        while idx < len(candidates):
            model_candidate = candidates[idx]
            for ver_idx, api_ver in enumerate(GEMINI_API_VERSIONS):
                attempt_num = len(attempts_log) + 1
                url = LLM_PROVIDERS["gemini"]["base_url"].format(
                    api_version=api_ver, model=model_candidate
                )
                role_tag = (
                    "mais recente / principal"
                    if attempt_num == 1
                    else f"alternativa #{attempt_num}"
                )
                logger.info(
                    f"[LLM] ▶ Tentativa {attempt_num} | Gemini (API {api_ver}) | "
                    f"Modelo: '{model_candidate}' ({role_tag})..."
                )
                try:
                    resp = self.client.post(url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    msg = f"Tentativa {attempt_num} ({model_candidate} / {api_ver}): falha de rede ({exc})"
                    attempts_log.append(msg)
                    logger.warning(f"[LLM] ⚠️ {msg}")
                    break

                if resp.status_code == 200:
                    data = resp.json()
                    cands = data.get("candidates", [])
                    if not cands:
                        msg = f"Tentativa {attempt_num} ({model_candidate} / {api_ver}): resposta vazia da API"
                        attempts_log.append(msg)
                        break
                    out_parts = cands[0].get("content", {}).get("parts", [])
                    text = "\n".join(p.get("text", "") for p in out_parts if "text" in p).strip()
                    attempts_log.append(
                        f"Tentativa {attempt_num} ({model_candidate} / {api_ver}): ✅ Sucesso"
                    )
                    logger.info(
                        f"[LLM] ✅ Sucesso na tentativa {attempt_num} com Gemini '{model_candidate}' (API {api_ver})!"
                    )
                    self.repo.set_setting("llm_model_gemini", model_candidate)
                    return text, model_candidate, attempts_log

                detail = _extract_api_error_detail(resp)
                friendly = _friendly_status_explanation(resp.status_code, "Gemini (Google)", detail)
                attempts_log.append(
                    f"Tentativa {attempt_num} ({model_candidate} / {api_ver}): ❌ HTTP {resp.status_code} ({detail[:120]})"
                )

                # Stop immediately on invalid API key (400 API_KEY_INVALID or 401/403)
                if resp.status_code in (401, 403) or (
                    resp.status_code == 400 and "API_KEY" in resp.text.upper()
                ):
                    logger.error(f"[LLM] ❌ {friendly}")
                    raise LLMSummaryError(friendly, attempts=attempts_log)

                # If 404 on v1beta, try v1 for same model; if both 404, discover live models and move to next model
                if resp.status_code == 404 and ver_idx == 0:
                    logger.warning(
                        f"[LLM] ⚠️ '{model_candidate}' não encontrado na API {api_ver} (HTTP 404). "
                        f"Alternando versão da API para '{GEMINI_API_VERSIONS[1]}'..."
                    )
                    continue

                if not discovered_added and resp.status_code in (400, 404):
                    discovered_added = True
                    live = self._discover_live_models("gemini", api_key)
                    for lm in live:
                        if lm not in candidates:
                            candidates.insert(idx + 1, lm)
                    if live:
                        logger.info(
                            f"[LLM] 🔎 Modelos ativos descobertos na conta Gemini (mais recentes primeiro): {live[:4]}"
                        )

                if idx + 1 < len(candidates):
                    logger.warning(
                        f"[LLM] ⚠️ Tentativa {attempt_num} falhou ({model_candidate} -> HTTP {resp.status_code}). "
                        f"Alternando para o próximo modelo: '{candidates[idx + 1]}'..."
                    )
                break
            idx += 1

        summary_err = (
            f"Não foi possível resumir com Gemini após {len(attempts_log)} tentativa(s). "
            f"Histórico: {' | '.join(attempts_log)}"
        )
        logger.error(f"[LLM] ❌ {summary_err}")
        raise LLMSummaryError(summary_err, attempts=attempts_log)

    def _call_claude_with_fallback(
        self,
        preferred_model: str,
        api_key: str,
        full_user_message: str,
    ) -> tuple[str, str, list[str]]:
        """Try Claude models from newest (Claude 4.6 / 4.5) to older, with live /v1/models discovery on 404."""
        candidates = self._build_candidate_chain("claude", preferred_model)
        url = LLM_PROVIDERS["claude"]["base_url"]
        api_ver = CLAUDE_API_VERSIONS[0]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": api_ver,
            "Content-Type": "application/json",
        }
        attempts_log: list[str] = []
        discovered_added = False

        idx = 0
        while idx < len(candidates):
            model_candidate = candidates[idx]
            attempt_num = len(attempts_log) + 1
            role_tag = (
                "mais recente / principal" if attempt_num == 1 else f"alternativa #{attempt_num}"
            )
            logger.info(
                f"[LLM] ▶ Tentativa {attempt_num} | Claude (API {api_ver}) | "
                f"Modelo: '{model_candidate}' ({role_tag})..."
            )
            payload = {
                "model": model_candidate,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": full_user_message}],
            }
            try:
                resp = self.client.post(url, headers=headers, json=payload)
            except httpx.RequestError as exc:
                msg = f"Tentativa {attempt_num} ({model_candidate}): falha de rede ({exc})"
                attempts_log.append(msg)
                logger.warning(f"[LLM] ⚠️ {msg}")
                idx += 1
                continue

            if resp.status_code == 200:
                data = resp.json()
                content_blocks = data.get("content", [])
                text = "\n".join(
                    b.get("text", "") for b in content_blocks if b.get("type") == "text"
                ).strip()
                attempts_log.append(f"Tentativa {attempt_num} ({model_candidate}): ✅ Sucesso")
                logger.info(
                    f"[LLM] ✅ Sucesso na tentativa {attempt_num} com Claude '{model_candidate}' (API {api_ver})!"
                )
                self.repo.set_setting("llm_model_claude", model_candidate)
                return text, model_candidate, attempts_log

            detail = _extract_api_error_detail(resp)
            friendly = _friendly_status_explanation(resp.status_code, "Claude (Anthropic)", detail)
            attempts_log.append(
                f"Tentativa {attempt_num} ({model_candidate}): ❌ HTTP {resp.status_code} ({detail[:120]})"
            )

            # Do not retry other models if the API key itself is invalid (401/403) or out of credits (400 credit balance)
            if resp.status_code in (401, 402, 403) or (
                resp.status_code == 400 and "credit balance" in detail.lower()
            ):
                logger.error(f"[LLM] ❌ {friendly}")
                raise LLMSummaryError(friendly, attempts=attempts_log)

            # On 404 (model not found), query Anthropic's live /v1/models endpoint to get exact active models
            if not discovered_added and resp.status_code in (400, 404):
                discovered_added = True
                live = self._discover_live_models("claude", api_key)
                if live:
                    logger.info(
                        f"[LLM] 🔎 Modelos ativos descobertos na API Claude (mais recentes primeiro): {live[:5]}"
                    )
                    insert_pos = idx + 1
                    for lm in live:
                        if lm not in candidates:
                            candidates.insert(insert_pos, lm)
                            insert_pos += 1

            if idx + 1 < len(candidates):
                logger.warning(
                    f"[LLM] ⚠️ Tentativa {attempt_num} recusada ({model_candidate} -> HTTP {resp.status_code}: {detail[:90]}). "
                    f"Alternando para tentativa {attempt_num + 1}: '{candidates[idx + 1]}'..."
                )
            idx += 1

        summary_err = (
            f"Não foi possível resumir com Claude (Anthropic) após {len(attempts_log)} tentativa(s). "
            f"Histórico de tentativas: {' | '.join(attempts_log)}"
        )
        logger.error(f"[LLM] ❌ {summary_err}")
        raise LLMSummaryError(summary_err, attempts=attempts_log)

    def _call_openai_compatible_with_fallback(
        self,
        provider: str,
        preferred_model: str,
        api_key: str,
        full_user_message: str,
    ) -> tuple[str, str, list[str]]:
        """Call ChatGPT, DeepSeek, or Qwen trying newest models first and alternating endpoints/models on failure."""
        meta = LLM_PROVIDERS[provider]
        prov_name = meta["name"]
        candidates = self._build_candidate_chain(provider, preferred_model)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if provider == "qwen":
            endpoints = QWEN_REGIONAL_URLS
        elif provider == "deepseek":
            endpoints = DEEPSEEK_API_URLS
        else:
            endpoints = [("v1", meta["base_url"])]

        attempts_log: list[str] = []
        discovered_added = False

        idx = 0
        while idx < len(candidates):
            model_candidate = candidates[idx]
            for ep_idx, (ep_label, url) in enumerate(endpoints):
                attempt_num = len(attempts_log) + 1
                role_tag = (
                    "mais recente / principal"
                    if attempt_num == 1
                    else f"alternativa #{attempt_num}"
                )
                logger.info(
                    f"[LLM] ▶ Tentativa {attempt_num} | {prov_name} ({ep_label}) | "
                    f"Modelo: '{model_candidate}' ({role_tag})..."
                )
                payload = {
                    "model": model_candidate,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Você é um assistente especialista em resumir episódios de podcasts em bullet points claros.",
                        },
                        {"role": "user", "content": full_user_message},
                    ],
                    "temperature": 0.3,
                }
                try:
                    resp = self.client.post(url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    msg = f"Tentativa {attempt_num} ({model_candidate} / {ep_label}): falha de rede ({exc})"
                    attempts_log.append(msg)
                    logger.warning(f"[LLM] ⚠️ {msg}")
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    attempts_log.append(
                        f"Tentativa {attempt_num} ({model_candidate} / {ep_label}): ✅ Sucesso"
                    )
                    logger.info(
                        f"[LLM] ✅ Sucesso na tentativa {attempt_num} com {prov_name} '{model_candidate}' ({ep_label})!"
                    )
                    self.repo.set_setting(f"llm_model_{provider}", model_candidate)
                    return text, model_candidate, attempts_log

                detail = _extract_api_error_detail(resp)
                friendly = _friendly_status_explanation(resp.status_code, prov_name, detail)
                attempts_log.append(
                    f"Tentativa {attempt_num} ({model_candidate} / {ep_label}): ❌ HTTP {resp.status_code} ({detail[:120]})"
                )

                # For Qwen, a 401/404 on Singapore endpoint may work on US or CN endpoint
                if (
                    provider == "qwen"
                    and resp.status_code in (401, 404)
                    and ep_idx + 1 < len(endpoints)
                ):
                    logger.warning(
                        f"[LLM] ⚠️ Endpoint Qwen '{ep_label}' retornou HTTP {resp.status_code}. "
                        f"Alternando para região '{endpoints[ep_idx + 1][0]}'..."
                    )
                    continue

                if resp.status_code in (401, 402, 403):
                    logger.error(f"[LLM] ❌ {friendly}")
                    raise LLMSummaryError(friendly, attempts=attempts_log)

                if not discovered_added and resp.status_code in (400, 404):
                    discovered_added = True
                    live = self._discover_live_models(provider, api_key)
                    if live:
                        logger.info(
                            f"[LLM] 🔎 Modelos ativos descobertos em {prov_name}: {live[:5]}"
                        )
                        insert_pos = idx + 1
                        for lm in live:
                            if lm not in candidates:
                                candidates.insert(insert_pos, lm)
                                insert_pos += 1

                if idx + 1 < len(candidates):
                    logger.warning(
                        f"[LLM] ⚠️ Tentativa {attempt_num} recusada ({model_candidate} -> HTTP {resp.status_code}: {detail[:90]}). "
                        f"Alternando para tentativa {attempt_num + 1}: '{candidates[idx + 1]}'..."
                    )
                break
            idx += 1

        summary_err = (
            f"Não foi possível resumir com {prov_name} após {len(attempts_log)} tentativa(s). "
            f"Histórico: {' | '.join(attempts_log)}"
        )
        logger.error(f"[LLM] ❌ {summary_err}")
        raise LLMSummaryError(summary_err, attempts=attempts_log)

    def call_llm_api(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        transcript_text: str,
    ) -> str:
        """Execute text-only summarization request to ChatGPT, Claude, Gemini, DeepSeek, or Qwen."""
        text, _, _ = self.call_llm_api_detailed(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            prompt=prompt,
            transcript_text=transcript_text,
        )
        return text

    def call_llm_api_detailed(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        transcript_text: str,
    ) -> tuple[str, str, list[str]]:
        """Execute LLM text summarization returning (summary_text, actual_model_used, attempts_log)."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor não suportado: {provider}")
        clean_key = _sanitize_api_key(api_key)
        if not clean_key:
            raise LLMSummaryError(
                f"API Key não cadastrada ou inválida para {LLM_PROVIDERS[provider]['name']}. "
                "Cadastre a chave em '🤖 Resumo LLM / Prompt'."
            )

        full_user_message = f"{prompt}\n\n---\nTRANSCRIÇÃO DO EPISÓDIO:\n{transcript_text}"

        if provider == "gemini":
            text, used_model, attempts = self._call_gemini_with_fallback(
                preferred_model=model_name,
                api_key=clean_key,
                full_user_message=full_user_message,
            )
            self._last_attempts_report = attempts
            return text, used_model, attempts

        if provider == "claude":
            text, used_model, attempts = self._call_claude_with_fallback(
                preferred_model=model_name,
                api_key=clean_key,
                full_user_message=full_user_message,
            )
            self._last_attempts_report = attempts
            return text, used_model, attempts

        if provider in ("chatgpt", "deepseek", "qwen"):
            text, used_model, attempts = self._call_openai_compatible_with_fallback(
                provider=provider,
                preferred_model=model_name,
                api_key=clean_key,
                full_user_message=full_user_message,
            )
            self._last_attempts_report = attempts
            return text, used_model, attempts

        raise ValueError(f"Provedor não suportado: {provider}")

    def summarize_episode(
        self,
        episode_id: int,
        provider: str | None = None,
        model_name: str | None = None,
        custom_prompt: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptSummary:
        """Generate an LLM summary from an existing local text transcript and save it to SQLite and .txt."""
        ep = self.repo.get_episode(episode_id)
        if not ep:
            raise ValueError(f"Episódio {episode_id} não encontrado")

        transcripts = self.repo.list_episode_transcripts(episode_id)
        if not transcripts:
            raise ValueError("Este episódio ainda não possui transcrição local para resumir.")

        latest_tx = transcripts[0]
        tx_path = Path(latest_tx.plain_text_path)
        if not tx_path.exists():
            raise ValueError(f"Arquivo de transcrição não encontrado em disco: {tx_path}")

        plain_text = tx_path.read_text(encoding="utf-8")
        cfg = self.get_config()

        chosen_provider = provider or cfg["active_provider"]
        if chosen_provider not in LLM_PROVIDERS:
            chosen_provider = "gemini"

        prov_info = cfg["providers"][chosen_provider]
        chosen_model = (model_name or prov_info["model"]).strip()
        chosen_prompt = (custom_prompt or cfg["prompt"]).strip()
        chosen_key = _sanitize_api_key(api_key) if api_key else prov_info["api_key"]

        self.save_config(
            provider=chosen_provider,
            prompt=chosen_prompt,
            model_name=chosen_model,
            api_key=chosen_key if api_key else None,
        )

        task_key = f"llm_summary:{episode_id}"
        activity_tracker.start(
            task_key,
            f"Resumindo transcrição do episódio #{episode_id} via {prov_info['name']} ({chosen_model})",
        )
        logger.info(
            f"[LLM] Iniciando resumo da transcrição local do episódio #{episode_id} '{ep.title}' "
            f"| Provedor: {prov_info['name']} | Modelo preferencial: {chosen_model} | "
            f"Tamanho da transcrição: {len(plain_text)} chars"
        )
        t0 = time.perf_counter()
        try:
            summary_text, used_model, attempts = self.call_llm_api_detailed(
                provider=chosen_provider,
                model_name=chosen_model,
                api_key=chosen_key,
                prompt=chosen_prompt,
                transcript_text=plain_text,
            )
            elapsed = round(time.perf_counter() - t0, 2)

            base_filename = f"{slugify(ep.title)}__resumo_{chosen_provider}_{slugify(used_model)}"
            summary_path = tx_path.parent / f"{base_filename}.txt"
            if summary_path.exists():
                summary_path = tx_path.parent / f"{base_filename}_{int(time.time())}.txt"
            summary_path.write_text(summary_text, encoding="utf-8")

            record = self.repo.record_summary(
                episode_id=episode_id,
                transcript_id=latest_tx.id,
                provider=chosen_provider,
                model_name=used_model,
                prompt_used=chosen_prompt,
                summary_text=summary_text,
                summary_path=str(summary_path),
                duration_proc_seconds=elapsed,
            )
            logger.info(
                f"[LLM] Resumo concluído em {elapsed}s usando '{used_model}' "
                f"({len(attempts)} tentativa(s), {len(summary_text)} chars) -> {summary_path}"
            )
            return record
        finally:
            activity_tracker.finish(task_key)
