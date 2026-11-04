# PROGRESS — Estado de Execução e Handoff (`pod2bullets`)

Status possíveis: `pendente` · `em andamento` · `concluído` · `bloqueado`.
Regras obrigatórias de atualização e passagem de bastão em [AGENTS.md](AGENTS.md).
Especificação detalhada de cada passo em [PLAN.md](PLAN.md#5-passos-de-execução-faseados).

---

## Checkpoint de Handoff Ativo

- **Estado atual:** `plano concluído` (todos os passos implementados e testados com sucesso)
- **Passo ativo / próximo da fila:** nenhum (todas as fases F0 a F6 concluídas)
- **Último agente a atualizar:** Gemini CLI (Gemini Flash)
- **Data:** 2026-11-04
- **Arquivos:** todos os módulos e suíte de testes 100% verde no WSL `Ubuntu-26.04`.

---

## Passos

| Passo | Fase / Descrição | Depende de | Status | Agente | Data |
|-------|------------------|------------|--------|--------|------|
| F0.1 | Fundação: Scaffolding Python, `pyproject.toml`, `setup_wsl.sh`, `config`, `naming` e CLI base no WSL Ubuntu 26.04 | — | concluído | Gemini CLI | 2026-11-04 |
| F0.2 | Fundação: Gerador de fixtures offline (feeds RSS sintéticos + áudios curtos WAV/MP3 via PyAV) | F0.1 | concluído | Gemini CLI | 2026-11-04 |
| F1.1 | Subscrições & DB: Schema SQLite (WAL), models e repositório (listas, feeds, episódios, transcrições, jobs) | F0.1 | concluído | Gemini CLI | 2026-11-04 |
| F1.2 | Subscrições & Feeds: Parser RSS/Atom, import/export OPML e sincronização de catálogo (zero download automático) | F0.2, F1.1 | concluído | Gemini CLI | 2026-11-04 |
| F2.1 | Download Manual: Serviço de download sob demanda (streaming `.part`, hash sha256) e árvore `data/podcasts/` | F1.2 | concluído | Gemini CLI | 2026-11-04 |
| F3.1 | Transcrição Core: Protocolo `TranscriberEngine`, decodificador de áudio `PyAV` (16kHz) e `ModelRegistry` | F0.2, F1.1 | concluído | Gemini CLI | 2026-11-04 |
| F3.2 | Modelos SOTA: Engines `whisper-large-v3-turbo` (`faster-whisper`) + `parakeet-tdt-0.6b-v3` (`onnx-asr`) e script de download | F3.1 | concluído | Gemini CLI | 2026-11-04 |
| F4.1 | Backend Worker: Fila persistente e pipeline automático `Download Manual -> Transcrição em Background -> .txt` | F2.1, F3.1 | concluído | Gemini CLI | 2026-11-04 |
| F5.1 | Web API: Rotas FastAPI para listas, feeds, seleção de modelos, disparo de download, leitura web e download `.txt` | F4.1 | concluído | Gemini CLI | 2026-11-04 |
| F5.2 | Web UI: Interface Jinja2 + HTMX (listas de subscrições, botão de download manual, seletor de modelos, leitor e download `.txt`) | F5.1 | concluído | Gemini CLI | 2026-11-04 |
| F6.1 | Integração Final: CLI completa e teste E2E ponta a ponta no WSL Ubuntu 26.04 com troca entre os 2 modelos | F3.2, F5.2 | concluído | Gemini CLI | 2026-11-04 |
| F6.2 | Entrega: `README.md` completo e verificação final no WSL Ubuntu 26.04 | F6.1 | concluído | Gemini CLI | 2026-11-04 |

---

## Log de handoff

### 2026-11-04 — Implementação Completa do Plano (Fases F0.1 a F6.2) — Gemini CLI
- **Feito:**
  - Setup do ambiente virtual `.venv` no WSL `Ubuntu-26.04` com Python 3.14 e CUDA 12.9 ativo.
  - Implementado banco SQLite com modo WAL e repositório atômico para subscrições, feeds, episódios, transcrições e fila de jobs.
  - Implementado parser de RSS/Atom e OPML com garantia rigorosa de **zero download automático de áudio**.
  - Implementado serviço de download sob demanda (`DownloaderService`) com streaming e hash SHA-256.
  - Implementado protocolo plugável `TranscriberEngine`, decodificação universal via `PyAV` e as duas engines SOTA (`whisper-large-v3-turbo` e `parakeet-tdt-0.6b-v3`).
  - Implementado worker assíncrono em background (`BackgroundWorker`) que encadeia automaticamente download → transcrição → geração do `.txt`.
  - Implementada a API FastAPI e a interface Web (Jinja2 + HTMX + CSS responsivo) permitindo organizar listas, acionar download sob demanda, alternar modelos, ler transcrição no navegador e baixar `.txt`.
  - Criada CLI completa (`pod2bullets serve`, `pod2bullets models list`, `pod2bullets lists`).
  - Implementado teste de ponta a ponta (`tests/e2e/test_full_workflow.py`) validando todo o fluxo e a re-transcrição de áudio com múltiplos modelos.
- **Verificação (WSL Ubuntu-26.04):**
  - `ruff check .` e `ruff format --check .` 100% limpos sem avisos.
  - `pytest -v`: **19 testes passando (100% verde)**.


### 2026-11-04 — Refinamentos de UI, Terminal Verbose, Filtro por Podcast e Indicador de Sistema Ocupado (⏳) — Gemini CLI
- **Feito:**
  - **Terminal Verbose (`logging_config.py`):** Adicionado `setup_verbose_logging()` com `RichHandler`, timestamps e logs detalhados em tempo real para `pod2bullets.worker`, `pod2bullets.downloader`, `pod2bullets.transcriber`, `pod2bullets.feeds` e requisições HTTP.
  - **Indicador de Sistema Ocupado (`system_status.py` + `GET /system/status`):** Implementado `ActivityTracker` combinando tarefas em memória (instalação de modelos, sincronização RSS, importação OPML) e jobs SQLite (`pending`/`running`), exibindo ampulheta animada (`⏳ Sistema Ocupado: ...`) no topo da interface Web.
  - **Filtro Exclusivo por Podcast na Tela Principal (`app.py`, `base.html`, `index.html`):** A tela principal (`/`) não mistura mais episódios de todos os podcasts; exibe apenas os episódios do podcast selecionado no **Menu de Podcasts** da barra lateral esquerda (`/?feed_id=<id>`), ordenados do mais novo para o mais antigo (ISO-8601) e sem limite de 100 episódios.
  - **Gerenciamento Local de Modelos sem Login Hugging Face (`registry.py`, `models.py`):** Instalação e desinstalação direta pela GUI (`/models/manage`) usando `faster_whisper.download_model` (`mobiuslabsgmbh/faster-whisper-large-v3-turbo`) e `onnx_asr.load_model` (`nemo-parakeet-tdt-0.6b-v3`), com tamanho em MB e barra de status.
- **Verificação (WSL Ubuntu-26.04):**
  - `ruff check .` e `ruff format --check .`: OK (50 arquivos formatados).
  - `pytest -v`: **19 passed in 6.33s**.


### 2026-11-04 — Execução da Fase 7 (Itens 1 a 12: Sem Piscar, Limpeza de MP3, Fila Múltipla, Resumo LLM e Logs Duplos + Viewer) — Gemini CLI
- **Feito:**
  - **Itens 1 e 2 (Fim do Piscar na Interface):** `GET /system/status` retorna vazio (`""`) quando o sistema está ocioso (exibindo apenas a ampulheta `⏳ Sistema Ocupado` quando há trabalho real) e removido o `#global-htmx-indicator` ("Processando requisição...") que piscava a cada polling HTMX.
  - **Item 3 (Remoção do `.mp3` pós-processamento + Reprocessamento sob demanda):** `BackgroundWorker` apaga automaticamente o arquivo de áudio (`audio_path.unlink()`) assim que o `.txt` e `.meta.json` são gravados, adicionando o botão **"🔄 Reprocessar"** nos episódios concluídos e na tela de leitura para baixar novamente e re-transcrever quando solicitado.
  - **Itens 4 e 5 (Fila com Múltiplos Cliques + Fluidez em Background):** `POST /episodes/{id}/download` enfileira múltiplos episódios clicados em sequência exibindo a posição na fila (`🕒 Na fila de processamento (#N)`), com throttling de updates de progresso no SQLite e `busy_timeout=30000` + thread dedicada para download de modelos.
  - **Item 6 (Leitura na Íntegra e Exportação `.TXT`):** Botões **"📖 Ler na Íntegra"** e **"💾 Exportar .TXT"** nos cards de episódios e na página `/view/{episode_id}`.
  - **Item 7 (Resumo de Transcrições via LLM com Prompt Editável na GUI):** Criados `src/pod2bullets/llm/service.py`, `src/pod2bullets/web/routes/llm.py` e `llm_settings.html` suportando **ChatGPT (OpenAI)**, **Claude (Anthropic)**, **Gemini (Google)**, **DeepSeek** e **Qwen (Alibaba DashScope)**, com edição/salvamento do prompt via GUI e exportação do resumo em `.txt`.
  - **Itens 8, 9, 10, 11 e 12 (Logs Duplos em `logs/`, Log Viewer em Outra Janela e Supressão de Polling):** `logging_config.py` grava tudo que sai no bash em `logs/YYYY-MM-DD-HH-MM-APP.log` e logs de transcrição em `logs/YYYY-MM-DD-HH-MM-transcricao.log`, suprime as linhas `200 OK` de `/episodes/card/*`, `/system/status`, `/models/card/*` e `/logs/tail`, e disponibiliza o botão **"🖥️ Abrir Log Viewer"** (`/logs/viewer`) em janela separada.
- **Verificação (WSL Ubuntu-26.04):**
  - `ruff check .` e `ruff format --check .`: OK.
  - `pytest -v`: **19 passed in 7.73s**.
