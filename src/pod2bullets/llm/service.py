"""Multi-provider LLM summarization service (ChatGPT, Claude, Gemini, DeepSeek, Qwen)."""

import logging
import os
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

LLM_PROVIDERS: dict[str, dict[str, str]] = {
    "chatgpt": {
        "id": "chatgpt",
        "name": "ChatGPT (OpenAI)",
        "default_model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
    },
    "claude": {
        "id": "claude",
        "name": "Claude (Anthropic)",
        "default_model": "claude-3-5-sonnet-latest",
        "base_url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "id": "gemini",
        "name": "Gemini (Google)",
        "default_model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "env_key": "GEMINI_API_KEY",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "id": "qwen",
        "name": "Qwen (Alibaba DashScope)",
        "default_model": "qwen-plus",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "env_key": "DASHSCOPE_API_KEY",
    },
}


class LLMService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(timeout=120.0)

    def get_config(self) -> dict[str, Any]:
        """Return current LLM configuration and per-provider settings from SQLite."""
        active_provider = self.repo.get_setting("llm_provider", "gemini") or "gemini"
        if active_provider not in LLM_PROVIDERS:
            active_provider = "gemini"

        prompt = (
            self.repo.get_setting("llm_prompt", DEFAULT_SUMMARY_PROMPT) or DEFAULT_SUMMARY_PROMPT
        )

        providers_cfg: dict[str, dict[str, Any]] = {}
        for pid, meta in LLM_PROVIDERS.items():
            saved_key = self.repo.get_setting(f"llm_api_key_{pid}", "") or ""
            env_val = os.environ.get(meta["env_key"], "")
            effective_key = saved_key or env_val
            saved_model = (
                self.repo.get_setting(f"llm_model_{pid}", meta["default_model"])
                or meta["default_model"]
            )
            providers_cfg[pid] = {
                **meta,
                "model": saved_model,
                "has_key": bool(effective_key),
                "masked_key": (
                    f"{effective_key[:4]}...{effective_key[-4:]}"
                    if len(effective_key) > 8
                    else ("Configurada" if effective_key else "")
                ),
                "api_key": effective_key,
            }

        return {
            "active_provider": active_provider,
            "prompt": prompt,
            "providers": providers_cfg,
        }

    def save_config(
        self,
        provider: str,
        prompt: str,
        model_name: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Persist LLM provider, custom prompt, model name, and optional API key via GUI."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor LLM inválido: {provider}")

        self.repo.set_setting("llm_provider", provider)
        if prompt and prompt.strip():
            self.repo.set_setting("llm_prompt", prompt.strip())
        if model_name and model_name.strip():
            self.repo.set_setting(f"llm_model_{provider}", model_name.strip())
        if api_key is not None and api_key.strip():
            self.repo.set_setting(f"llm_api_key_{provider}", api_key.strip())

        logger.info(
            f"[LLM] Configuração salva via GUI: provedor='{provider}', "
            f"modelo='{model_name or LLM_PROVIDERS[provider]['default_model']}'"
        )

    def call_llm_api(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        transcript_text: str,
    ) -> str:
        """Execute HTTP request to ChatGPT, Claude, Gemini, DeepSeek, or Qwen API."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor não suportado: {provider}")
        if not api_key:
            raise ValueError(
                f"API Key não configurada para {LLM_PROVIDERS[provider]['name']}. "
                "Configure a chave na tela de Resumo LLM."
            )

        meta = LLM_PROVIDERS[provider]
        full_user_message = f"{prompt}\n\n---\nTRANSCRIÇÃO DO EPISÓDIO:\n{transcript_text}"

        if provider in ("chatgpt", "deepseek", "qwen"):
            url = meta["base_url"]
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
            resp = self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

        if provider == "claude":
            url = meta["base_url"]
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model_name,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": full_user_message}],
            }
            resp = self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content_blocks = data.get("content", [])
            return "\n".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            ).strip()

        if provider == "gemini":
            url = meta["base_url"].format(model=model_name)
            headers = {
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": full_user_message},
                        ]
                    }
                ]
            }
            resp = self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Resposta vazia da API Gemini: {data}")
            parts = candidates[0].get("content", {}).get("parts", [])
            return "\n".join(p.get("text", "") for p in parts).strip()

        raise ValueError(f"Provedor não suportado: {provider}")

    def summarize_episode(
        self,
        episode_id: int,
        provider: str | None = None,
        model_name: str | None = None,
        custom_prompt: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptSummary:
        """Generate an LLM summary for a transcribed episode and save it to SQLite and .txt."""
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

        # Persist prompt/provider updates if user customized them inline
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
