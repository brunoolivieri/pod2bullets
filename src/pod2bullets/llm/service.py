"""Multi-provider LLM summarization service (ChatGPT, Claude, Gemini, DeepSeek, Qwen)
supporting both text-transcript summarization and direct audio-to-summary via LLM API.
"""

import base64
import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx

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

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "id": "gemini",
        "name": "Gemini (Google)",
        "default_model": "gemini-2.5-flash",
        "suggested_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
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
        "default_model": "claude-3-5-sonnet-latest",
        "suggested_models": [
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
            "claude-3-7-sonnet-latest",
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
        "base_url": "https://api.deepseek.com/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "id": "qwen",
        "name": "Qwen (Alibaba DashScope)",
        "default_model": "qwen-plus",
        "audio_model": "qwen-omni-turbo",
        "suggested_models": ["qwen-plus", "qwen-max", "qwen-omni-turbo", "qwen-audio-turbo"],
        "supports_direct_audio": True,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "env_key": "DASHSCOPE_API_KEY",
    },
}


class LLMService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(timeout=180.0)

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

        # If the remembered provider has no key but another registered provider does, prefer the registered one
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
            self.repo.set_setting(f"llm_model_{provider}", model_name.strip())
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

    def call_llm_audio_api(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        prompt: str,
        audio_path: Path,
    ) -> str:
        """Send downloaded audio file + customizable prompt directly to the selected LLM API."""
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Provedor não suportado: {provider}")
        if not api_key:
            raise ValueError(
                f"API Key não cadastrada para {LLM_PROVIDERS[provider]['name']}. "
                "Cadastre a chave em '🤖 Resumo LLM / Prompt'."
            )

        meta = LLM_PROVIDERS[provider]
        audio_bytes = audio_path.read_bytes()
        b64_audio = base64.b64encode(audio_bytes).decode("ascii")
        ext = audio_path.suffix.lstrip(".").lower() or "mp3"
        mime_map = {
            "mp3": "audio/mp3",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "ogg": "audio/ogg",
            "opus": "audio/ogg",
        }
        mime_type = mime_map.get(ext, "audio/mp3")

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
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_audio,
                                }
                            },
                        ]
                    }
                ]
            }
            resp = self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Resposta vazia da API Gemini (áudio): {data}")
            parts = candidates[0].get("content", {}).get("parts", [])
            return "\n".join(p.get("text", "") for p in parts).strip()

        if provider in ("chatgpt", "qwen", "deepseek"):
            url = meta["base_url"]
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            target_model = model_name
            if provider == "chatgpt" and "audio" not in target_model:
                target_model = meta.get("audio_model", "gpt-4o-mini-audio-preview")
            elif provider == "qwen" and "audio" not in target_model and "omni" not in target_model:
                target_model = meta.get("audio_model", "qwen-omni-turbo")

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
                                    "data": b64_audio,
                                    "format": "wav" if ext == "wav" else "mp3",
                                },
                            },
                        ],
                    }
                ],
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
                "messages": [
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
                ],
            }
            resp = self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content_blocks = data.get("content", [])
            return "\n".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            ).strip()

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
            progress_callback(25.0)

        t0 = time.perf_counter()
        summary_text = self.call_llm_audio_api(
            provider=chosen_provider,
            model_name=chosen_model,
            api_key=chosen_key,
            prompt=chosen_prompt,
            audio_path=audio_path,
        )
        if progress_callback:
            progress_callback(95.0)

        elapsed = round(time.perf_counter() - t0, 2)

        transcripts_dir = audio_path.parent / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        summary_filename = (
            f"{slugify(ep.title)}__resumo_direto_{chosen_provider}_{slugify(chosen_model)}.txt"
        )
        summary_path = transcripts_dir / summary_filename
        summary_path.write_text(summary_text, encoding="utf-8")

        record = self.repo.record_summary(
            episode_id=episode_id,
            transcript_id=None,
            provider=chosen_provider,
            model_name=chosen_model,
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
