"""Multi-provider LLM summarization service (ChatGPT, Claude, Gemini, DeepSeek, Qwen)
supporting both text-transcript summarization and direct audio-to-summary via LLM API
(with verified URLs, regional/model fallbacks, and Resumable File API upload for large MP3s).
"""

import base64
import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from pod2bullets.config import settings
from pod2bullets.db.repository import Repository
from pod2bullets.models import TranscriptSummary
from pod2bullets.naming import slugify
from pod2bullets.system_status import activity_tracker

logger = logging.getLogger("pod2bullets.llm")

DEFAULT_SUMMARY_PROMPT = (
    "Você é um especialista em síntese de podcasts. Analise o conteúdo a seguir e elabore "
    "um resumo estruturado em português contendo:\n"
    "1. **Resumo Executivo (TL;DR):** 2 a 3 frases explicando o tema central do episódio.\n"
    "2. **Principais Pontos (Bullets):** Os tópicos, dados, histórias e argumentos mais importantes.\n"
    "3. **Destaques e Conclusões:** Insights práticos e aprendizados finais do episódio."
)

GEMINI_FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

CLAUDE_FALLBACK_MODELS = [
    "claude-sonnet-4-0",
    "claude-3-7-sonnet-latest",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
]

QWEN_REGIONAL_URLS = [
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
]

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "id": "gemini",
        "name": "Gemini (Google)",
        "default_model": "gemini-3.6-flash",
        "suggested_models": [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
        ],
        "supports_direct_audio": True,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "env_key": "GEMINI_API_KEY",
    },
    "chatgpt": {
        "id": "chatgpt",
        "name": "ChatGPT (OpenAI)",
        "default_model": "gpt-4o-mini",
        "audio_model": "gpt-4o-mini-audio-preview",
        "suggested_models": [
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini-audio-preview",
            "gpt-4o-audio-preview",
        ],
        "supports_direct_audio": True,
        "base_url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
    },
    "claude": {
        "id": "claude",
        "name": "Claude (Anthropic)",
        "default_model": "claude-sonnet-4-0",
        "suggested_models": [
            "claude-sonnet-4-0",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ],
        "supports_direct_audio": True,
        "base_url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "suggested_models": ["deepseek-chat", "deepseek-reasoner"],
        "supports_direct_audio": True,
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "id": "qwen",
        "name": "Qwen (Alibaba DashScope)",
        "default_model": "qwen-plus",
        "audio_model": "qwen-omni-turbo",
        "suggested_models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-omni-turbo"],
        "supports_direct_audio": True,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "env_key": "DASHSCOPE_API_KEY",
    },
}


def _raise_with_api_detail(resp: httpx.Response, provider_name: str) -> None:
    """Raise a clear error including the provider's JSON error message when HTTP >= 400."""
    if resp.status_code < 400:
        return
    detail = resp.text[:400]
    try:
        err_json = resp.json()
        if isinstance(err_json, dict) and "error" in err_json:
            err_obj = err_json["error"]
            if isinstance(err_obj, dict) and "message" in err_obj:
                detail = err_obj["message"]
            else:
                detail = str(err_obj)
    except Exception:
        pass
    raise RuntimeError(f"Erro HTTP {resp.status_code} na API {provider_name}: {detail}")


class LLMService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(connect=30.0, read=600.0, write=300.0, pool=30.0)
        )

    def get_config(self) -> dict[str, Any]:
        """Return current LLM configuration, registered providers, and last selected provider."""
        active_provider = self.repo.get_setting("llm_provider", "gemini") or "gemini"
        if active_provider not in LLM_PROVIDERS:
            active_provider = "gemini"

        last_direct_provider = (
            self.repo.get_setting("llm_direct_provider", active_provider) or active_provider
        )
        if last_direct_provider not in LLM_PROVIDERS:
            last_direct_provider = active_provider

        prompt = (
            self.repo.get_setting("llm_prompt", DEFAULT_SUMMARY_PROMPT) or DEFAULT_SUMMARY_PROMPT
        )

        providers_cfg: dict[str, dict[str, Any]] = {}
        registered_list: list[dict[str, Any]] = []

        for pid, meta in LLM_PROVIDERS.items():
            saved_key = self.repo.get_setting(f"llm_api_key_{pid}", "") or ""
            saved_model = (
                self.repo.get_setting(f"llm_model_{pid}", meta["default_model"])
                or meta["default_model"]
            )
            # Auto-upgrade deprecated gemini-2.5-flash to gemini-3.6-flash
            if pid == "gemini" and saved_model == "gemini-2.5-flash":
                saved_model = "gemini-3.6-flash"
                self.repo.set_setting("llm_model_gemini", saved_model)

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

        if registered_list and not providers_cfg[last_direct_provider]["has_key"]:
            last_direct_provider = registered_list[0]["id"]

        return {
            "active_provider": active_provider,
            "last_direct_provider": last_direct_provider,
            "prompt": prompt,
            "providers": providers_cfg,
            "registered_providers": registered_list,
        }

    def set_last_direct_provider(self, provider: str) -> None:
        """Remember the user's last selected LLM provider for direct summarization."""
        if provider in LLM_PROVIDERS:
            self.repo.set_setting("llm_direct_provider", provider)
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
            self.repo.set_setting(f"llm_model_{provider}", clean_m)
        if api_key is not None and api_key.strip():
            self.repo.set_setting(f"llm_api_key_{provider}", api_key.strip())

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

    def _call_gemini_with_fallback(
        self,
        preferred_model: str,
        api_key: str,
        parts: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Call Gemini generateContent and automatically fallback if a model returns 404 (deprecated) or 503 (busy)."""
        clean_pref = preferred_model.strip().removeprefix("models/")
        candidates_to_try = [clean_pref] + [m for m in GEMINI_FALLBACK_MODELS if m != clean_pref]
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {"contents": [{"parts": parts}]}

        last_resp: httpx.Response | None = None
        for idx, model_candidate in enumerate(candidates_to_try):
            url = LLM_PROVIDERS["gemini"]["base_url"].format(model=model_candidate)
            logger.info(
                f"[LLM] Chamando Gemini generateContent com modelo '{model_candidate}' "
                f"(tentativa {idx + 1}/{len(candidates_to_try)})..."
            )
            resp = self.client.post(url, headers=headers, json=payload)
            last_resp = resp
            if resp.status_code == 200:
                data = resp.json()
                cands = data.get("candidates", [])
                if not cands:
                    raise RuntimeError(f"Resposta sem candidatos da API Gemini: {data}")
                out_parts = cands[0].get("content", {}).get("parts", [])
                text = "\n".join(p.get("text", "") for p in out_parts if "text" in p).strip()
                if model_candidate != clean_pref:
                    logger.info(
                        f"[LLM] Modelo '{model_candidate}' respondeu com sucesso! "
                        f"Atualizando modelo padrão do Gemini para '{model_candidate}'."
                    )
                    self.repo.set_setting("llm_model_gemini", model_candidate)
                return text, model_candidate

            if resp.status_code in (404, 503) and idx + 1 < len(candidates_to_try):
                logger.warning(
                    f"[LLM] Modelo Gemini '{model_candidate}' retornou HTTP {resp.status_code} "
                    f"({resp.text[:160].strip()}). Tentando fallback automático '{candidates_to_try[idx + 1]}'..."
                )
                continue

            _raise_with_api_detail(resp, "Gemini")

        if last_resp is not None:
            _raise_with_api_detail(last_resp, "Gemini")
        raise RuntimeError("Falha ao comunicar com a API Gemini.")

    def _call_claude_with_fallback(
        self,
        preferred_model: str,
        api_key: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Call Anthropic Messages API with automatic model fallback on 404."""
        clean_pref = preferred_model.strip()
        candidates_to_try = [clean_pref] + [m for m in CLAUDE_FALLBACK_MODELS if m != clean_pref]
        url = LLM_PROVIDERS["claude"]["base_url"]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        last_resp: httpx.Response | None = None
        for idx, model_candidate in enumerate(candidates_to_try):
            payload = {
                "model": model_candidate,
                "max_tokens": 4096,
                "messages": messages,
            }
            resp = self.client.post(url, headers=headers, json=payload)
            last_resp = resp
            if resp.status_code == 200:
                data = resp.json()
                content_blocks = data.get("content", [])
                text = "\n".join(
                    b.get("text", "") for b in content_blocks if b.get("type") == "text"
                ).strip()
                return text, model_candidate

            if resp.status_code == 404 and idx + 1 < len(candidates_to_try):
                logger.warning(
                    f"[LLM] Modelo Claude '{model_candidate}' retornou 404. "
                    f"Tentando fallback '{candidates_to_try[idx + 1]}'..."
                )
                continue

            _raise_with_api_detail(resp, "Claude (Anthropic)")

        if last_resp is not None:
            _raise_with_api_detail(last_resp, "Claude (Anthropic)")
        raise RuntimeError("Falha ao comunicar com a API Claude.")

    def _post_qwen_with_regional_fallback(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        """Try Alibaba DashScope International, US, and China regional endpoints on 401/404."""
        last_resp: httpx.Response | None = None
        for url in QWEN_REGIONAL_URLS:
            resp = self.client.post(url, headers=headers, json=payload)
            last_resp = resp
            if resp.status_code == 200:
                return resp
            if resp.status_code not in (401, 404):
                break
        assert last_resp is not None
        return last_resp

    def _upload_to_gemini_files_api(
        self,
        audio_path: Path,
        mime_type: str,
        api_key: str,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict[str, str]:
        """Upload large podcast audio files (>4MB) via Google's Resumable File API in 8 MiB chunks."""
        total_size = audio_path.stat().st_size
        total_mb = total_size / (1024 * 1024)
        logger.info(
            f"[LLM-DIRETO] Iniciando upload resumível para Gemini File API "
            f"({total_mb:.1f} MB, arquivo='{audio_path.name}')..."
        )

        start_resp = self.client.post(
            "https://generativelanguage.googleapis.com/upload/v1beta/files",
            headers={
                "x-goog-api-key": api_key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(total_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": audio_path.name}},
        )
        _raise_with_api_detail(start_resp, "Gemini File Upload (start)")
        upload_url = start_resp.headers.get("x-goog-upload-url")
        if not upload_url:
            raise RuntimeError("Gemini File API não retornou o header x-goog-upload-url.")

        chunk_size = 8 * 1024 * 1024  # 8 MiB (required multiple for Google resumable protocol)
        offset = 0
        final_json: dict[str, Any] = {}

        with open(audio_path, "rb") as f:
            while offset < total_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                is_last = (offset + len(chunk)) >= total_size
                cmd = "upload, finalize" if is_last else "upload"

                up_resp = self.client.post(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "X-Goog-Upload-Offset": str(offset),
                        "X-Goog-Upload-Command": cmd,
                    },
                    content=chunk,
                )
                _raise_with_api_detail(up_resp, "Gemini File Upload (chunk)")
                offset += len(chunk)
                pct_upload = (offset / total_size) * 100.0
                logger.info(
                    f"[LLM-DIRETO] Upload Gemini File API: {offset / (1024 * 1024):.1f} / "
                    f"{total_mb:.1f} MB ({pct_upload:.1f}%)"
                )
                if progress_callback:
                    progress_callback(10.0 + (pct_upload * 0.65))

                if is_last:
                    final_json = up_resp.json()

        file_info = final_json.get("file", {})
        file_name = file_info.get("name", "")
        file_uri = file_info.get("uri", "")
        state = file_info.get("state", "ACTIVE")

        polls = 0
        while state == "PROCESSING" and polls < 60:
            time.sleep(2.0)
            polls += 1
            chk = self.client.get(
                f"https://generativelanguage.googleapis.com/v1beta/{file_name}",
                headers={"x-goog-api-key": api_key},
            )
            if chk.status_code == 200:
                f_data = chk.json()
                state = f_data.get("state", "ACTIVE")
                file_uri = f_data.get("uri", file_uri)
                logger.info(f"[LLM-DIRETO] Processando arquivo no Gemini ({state})...")

        if state not in ("ACTIVE", ""):
            raise RuntimeError(f"Arquivo enviado ao Gemini ficou com estado inválido: {state}")

        logger.info(f"[LLM-DIRETO] Upload concluído e ativo no Gemini: {file_uri}")
        return {"name": file_name, "uri": file_uri}

    def call_llm_api(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        transcript_text: str,
    ) -> str:
        """Execute HTTP request to ChatGPT, Claude, Gemini, DeepSeek, or Qwen API with text."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor não suportado: {provider}")
        if not api_key:
            raise ValueError(
                f"API Key não cadastrada para {LLM_PROVIDERS[provider]['name']}. "
                "Cadastre a chave em '🤖 Resumo LLM / Prompt'."
            )

        meta = LLM_PROVIDERS[provider]
        full_user_message = f"{prompt}\n\n---\nTRANSCRIÇÃO DO EPISÓDIO:\n{transcript_text}"

        if provider in ("chatgpt", "deepseek", "qwen"):
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "Você é um assistente especialista em resumir episódios de podcasts em bullet points claros.",
                    },
                    {"role": "user", "content": full_user_message},
                ],
                "temperature": 0.3,
            }
            if provider == "qwen":
                resp = self._post_qwen_with_regional_fallback(headers, payload)
            else:
                resp = self.client.post(meta["base_url"], headers=headers, json=payload)
            _raise_with_api_detail(resp, meta["name"])
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

        if provider == "claude":
            text, _ = self._call_claude_with_fallback(
                preferred_model=model_name,
                api_key=api_key,
                messages=[{"role": "user", "content": full_user_message}],
            )
            return text

        if provider == "gemini":
            text, _ = self._call_gemini_with_fallback(
                preferred_model=model_name,
                api_key=api_key,
                parts=[{"text": full_user_message}],
            )
            return text

        raise ValueError(f"Provedor não suportado: {provider}")

    def call_llm_audio_api(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        audio_path: Path,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[str, str]:
        """Send downloaded audio file + customizable prompt directly to the selected LLM API."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor não suportado: {provider}")
        if not api_key:
            raise ValueError(
                f"API Key não cadastrada para {LLM_PROVIDERS[provider]['name']}. "
                "Cadastre a chave em '🤖 Resumo LLM / Prompt'."
            )

        meta = LLM_PROVIDERS[provider]
        ext = audio_path.suffix.lstrip(".").lower() or "mp3"
        mime_map = {
            "mp3": "audio/mp3",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "ogg": "audio/ogg",
            "opus": "audio/ogg",
        }
        mime_type = mime_map.get(ext, "audio/mp3")
        file_size = audio_path.stat().st_size

        if provider == "gemini":
            if file_size > 4 * 1024 * 1024:
                uploaded = self._upload_to_gemini_files_api(
                    audio_path=audio_path,
                    mime_type=mime_type,
                    api_key=api_key,
                    progress_callback=progress_callback,
                )
                try:
                    if progress_callback:
                        progress_callback(80.0)
                    parts = [
                        {
                            "file_data": {
                                "mime_type": mime_type,
                                "file_uri": uploaded["uri"],
                            }
                        },
                        {"text": prompt},
                    ]
                    return self._call_gemini_with_fallback(
                        preferred_model=model_name,
                        api_key=api_key,
                        parts=parts,
                    )
                finally:
                    if uploaded.get("name"):
                        try:
                            self.client.delete(
                                f"https://generativelanguage.googleapis.com/v1beta/{uploaded['name']}",
                                headers={"x-goog-api-key": api_key},
                            )
                            logger.info(
                                f"[LLM-DIRETO] Arquivo temporário removido da Gemini File API: {uploaded['name']}"
                            )
                        except Exception:
                            pass
            else:
                b64_audio = base64.b64encode(audio_path.read_bytes()).decode("ascii")
                parts = [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_audio,
                        }
                    },
                ]
                return self._call_gemini_with_fallback(
                    preferred_model=model_name,
                    api_key=api_key,
                    parts=parts,
                )

        b64_audio = base64.b64encode(audio_path.read_bytes()).decode("ascii")

        if provider in ("chatgpt", "qwen", "deepseek"):
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            target_model = model_name
            if provider == "chatgpt" and "audio" not in target_model:
                target_model = meta.get("audio_model", "gpt-4o-mini-audio-preview")
            elif provider == "qwen" and "audio" not in target_model and "omni" not in target_model:
                target_model = meta.get("audio_model", "qwen-omni-turbo")

            # Qwen DashScope expects data URI prefix (`data:;base64,...`) in input_audio.data
            audio_data_field = f"data:;base64,{b64_audio}" if provider == "qwen" else b64_audio
            payload = {
                "model": target_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_data_field,
                                    "format": "wav" if ext == "wav" else "mp3",
                                },
                            },
                        ],
                    }
                ],
            }
            if provider == "qwen":
                resp = self._post_qwen_with_regional_fallback(headers, payload)
            else:
                resp = self.client.post(meta["base_url"], headers=headers, json=payload)

            # If a text-only endpoint (like DeepSeek) rejects input_audio with HTTP 400,
            # automatically transcribe locally first and then summarize via text API!
            if resp.status_code == 400 and provider == "deepseek":
                logger.info(
                    "[LLM-DIRETO] DeepSeek não aceita áudio binário direto; "
                    "transcrevendo localmente e enviando texto para DeepSeek..."
                )
                from pod2bullets.transcriber.registry import ModelRegistry

                engine = ModelRegistry().get_engine(settings.default_model_id)
                tx_res = engine.transcribe(audio_path)
                return (
                    self.call_llm_api(provider, model_name, api_key, prompt, tx_res.plain_text),
                    model_name,
                )

            _raise_with_api_detail(resp, meta["name"])
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip(), target_model

        if provider == "claude":
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_audio,
                            },
                        },
                    ],
                }
            ]
            try:
                return self._call_claude_with_fallback(
                    preferred_model=model_name,
                    api_key=api_key,
                    messages=messages,
                )
            except RuntimeError as e:
                if "400" in str(e):
                    logger.info(
                        "[LLM-DIRETO] API Claude não aceita áudio binário direto; "
                        "transcrevendo localmente e enviando texto para Claude..."
                    )
                    from pod2bullets.transcriber.registry import ModelRegistry

                    engine = ModelRegistry().get_engine(settings.default_model_id)
                    tx_res = engine.transcribe(audio_path)
                    return (
                        self.call_llm_api(provider, model_name, api_key, prompt, tx_res.plain_text),
                        model_name,
                    )
                raise

        raise ValueError(f"Provedor não suportado: {provider}")

    def summarize_audio_direct(
        self,
        episode_id: int,
        audio_path: Path,
        provider: str | None = None,
        custom_prompt: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> TranscriptSummary:
        """Send downloaded episode audio directly to LLM API, save .txt summary, and record in SQLite."""
        ep = self.repo.get_episode(episode_id)
        if not ep:
            raise ValueError(f"Episódio {episode_id} não encontrado")

        cfg = self.get_config()
        chosen_provider = provider or cfg["last_direct_provider"]
        if chosen_provider not in LLM_PROVIDERS:
            chosen_provider = cfg["active_provider"]

        self.set_last_direct_provider(chosen_provider)
        prov_info = cfg["providers"][chosen_provider]
        chosen_model = prov_info["model"]
        chosen_prompt = (custom_prompt or cfg["prompt"]).strip()
        chosen_key = prov_info["api_key"]

        logger.info(
            f"[LLM-DIRETO] Enviando áudio '{audio_path.name}' "
            f"({audio_path.stat().st_size / (1024 * 1024):.2f} MB) do episódio #{episode_id} "
            f"para {prov_info['name']} ({chosen_model})..."
        )
        if progress_callback:
            progress_callback(10.0)

        t0 = time.perf_counter()
        summary_text, used_model = self.call_llm_audio_api(
            provider=chosen_provider,
            model_name=chosen_model,
            api_key=chosen_key,
            prompt=chosen_prompt,
            audio_path=audio_path,
            progress_callback=progress_callback,
        )
        if progress_callback:
            progress_callback(95.0)

        elapsed = round(time.perf_counter() - t0, 2)

        transcripts_dir = audio_path.parent / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        summary_filename = (
            f"{slugify(ep.title)}__resumo_direto_{chosen_provider}_{slugify(used_model)}.txt"
        )
        summary_path = transcripts_dir / summary_filename
        summary_path.write_text(summary_text, encoding="utf-8")

        record = self.repo.record_summary(
            episode_id=episode_id,
            transcript_id=None,
            provider=chosen_provider,
            model_name=used_model,
            prompt_used=chosen_prompt,
            summary_text=summary_text,
            summary_path=str(summary_path),
            duration_proc_seconds=elapsed,
        )
        logger.info(
            f"[LLM-DIRETO] Resumo direto concluído em {elapsed}s ({len(summary_text)} chars) -> {summary_path}"
        )
        return record

    def summarize_episode(
        self,
        episode_id: int,
        provider: str | None = None,
        model_name: str | None = None,
        custom_prompt: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptSummary:
        """Generate an LLM summary from an existing text transcript and save it to SQLite and .txt."""
        ep = self.repo.get_episode(episode_id)
        if not ep:
            raise ValueError(f"Episódio {episode_id} não encontrado")

        transcripts = self.repo.list_episode_transcripts(episode_id)
        if not transcripts:
            raise ValueError("Este episódio ainda não possui transcrição para resumir.")

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
        chosen_key = (api_key or prov_info["api_key"]).strip()

        self.save_config(
            provider=chosen_provider,
            prompt=chosen_prompt,
            model_name=chosen_model,
            api_key=api_key if api_key else None,
        )

        task_key = f"llm_summary:{episode_id}"
        activity_tracker.start(
            task_key,
            f"Resumindo episódio #{episode_id} via {prov_info['name']} ({chosen_model})",
        )
        logger.info(
            f"[LLM] Iniciando resumo da transcrição do episódio #{episode_id} '{ep.title}' "
            f"| Provedor: {prov_info['name']} | Modelo: {chosen_model} | "
            f"Tamanho transcrição: {len(plain_text)} chars"
        )
        t0 = time.perf_counter()
        try:
            summary_text = self.call_llm_api(
                provider=chosen_provider,
                model_name=chosen_model,
                api_key=chosen_key,
                prompt=chosen_prompt,
                transcript_text=plain_text,
            )
            elapsed = round(time.perf_counter() - t0, 2)

            summary_filename = (
                f"{slugify(ep.title)}__resumo_{chosen_provider}_{slugify(chosen_model)}.txt"
            )
            summary_path = tx_path.parent / summary_filename
            summary_path.write_text(summary_text, encoding="utf-8")

            record = self.repo.record_summary(
                episode_id=episode_id,
                transcript_id=latest_tx.id,
                provider=chosen_provider,
                model_name=chosen_model,
                prompt_used=chosen_prompt,
                summary_text=summary_text,
                summary_path=str(summary_path),
                duration_proc_seconds=elapsed,
            )
            logger.info(
                f"[LLM] Resumo concluído em {elapsed}s ({len(summary_text)} chars) -> {summary_path}"
            )
            return record
        finally:
            activity_tracker.finish(task_key)
