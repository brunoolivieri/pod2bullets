# PLAN — pod2bullets

Cliente web e de linha de comando em Python para gestão de subscrições de podcasts, download manual sob demanda e transcrição local automática em background com modelos open-source estado da arte, rodando integralmente no **WSL (`Ubuntu-26.04`)**.

> Este plano é executado de maneira faseada e cooperativa por **Claude Code** e **Gemini CLI**.
> Antes de qualquer implementação, leia [AGENTS.md](AGENTS.md) (protocolo e handoff) e [PROGRESS.md](PROGRESS.md) (estado atual e checkpoint ativo).

---

## 1. Requisitos e Regras de Negócio

1. **Organização de listas de subscrições:**
   - O usuário pode criar, renomear e excluir **listas/categorias de subscrição** (ex.: *Tecnologia*, *Notícias*, *História*, *Estudos*, *Favoritos*).
   - O usuário pode assinar podcasts informando a URL do feed RSS/Atom ou importando/exportando arquivos **OPML** (preservando as listas/categorias do OPML).
   - Uma subscrição pode ser associada a uma ou mais listas e filtrada na interface web.
2. **Zero download automático de áudio:**
   - Cadastrar um podcast ou clicar em *"Atualizar Feed(s)"* baixa **exclusivamente o XML do RSS/Atom**, populando/atualizando os metadados dos episódios no banco SQLite com status `available`.
   - **Nenhum arquivo de áudio é baixado sem ação explícita do usuário.** O download de um episódio ocorre unicamente quando o usuário clica no botão *"Baixar e Transcrever"* (ou *"Baixar"*) daquele episódio específico.
3. **Transcrição automática em background pós-download + Leitura Web e Download `.txt`:**
   - Assim que o download do áudio de um episódio termina (`downloaded`), o backend enfileira automaticamente a tarefa de transcrição (`queued_transcription` → `transcribing` → `completed`).
   - Tudo roda em um **worker assíncrono em background** no backend Python, sem travar a navegação na interface web.
   - O resultado é salvo como **texto puro (`.txt`)** (além de um `.meta.json` com segmentos, timestamps, idioma detectado, tempo de processamento e modelo utilizado).
   - Na interface web, qualquer episódio transcrito exibe:
     - **Visualização direta na Web:** leitura limpa do texto puro no navegador (com busca, botão de copiar texto e alternância opcional para visualizar marcadores de tempo);
     - **Botão de Download `.txt`:** entrega o arquivo `.txt` (`Content-Type: text/plain; charset=utf-8` com `Content-Disposition: attachment`).
4. **Transcrição 100% local, open-source, gratuita e estado da arte:**
   - Execução local no WSL (`Ubuntu-26.04`), aproveitando a GPU **NVIDIA GeForce RTX 2060 SUPER (8 GB VRAM, CUDA 12.9)** quando disponível e caindo automaticamente para CPU (`int8`) se necessário.
   - Decodificação de áudio via `PyAV` (`av`), que embute as bibliotecas FFmpeg no próprio wheel Python (funciona para `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wav` sem exigir instalação global de pacotes fora do `.venv`).
5. **Modelo de transcrição facilmente trocável + múltiplos modelos instalados + 2 modelos de fábrica:**
   - Arquitetura baseada no protocolo `TranscriberEngine` + catálogo `ModelRegistry`.
   - O usuário pode manter vários modelos baixados simultaneamente em `data/models/`, visualizar na interface web quais estão instalados em disco, definir o **modelo padrão** e **escolher qual modelo rodar** ao clicar para baixar/transcrever (ou re-transcrever um episódio já baixado com outro modelo para comparar).
   - O projeto já traz **2 modelos SOTA open-source e gratuitos** pré-configurados e suportados nativamente:
     1. **`whisper-large-v3-turbo`** (`Systran/faster-whisper-large-v3-turbo` via `faster-whisper` / CTranslate2)
     2. **`parakeet-tdt-0.6b-v3`** (`nemo-parakeet-tdt-0.6b-v3` via `onnx-asr` / ONNX Runtime)
6. **Execução e testes no Linux do WSL (`Ubuntu-26.04`):**
   - Todo o ciclo de vida (setup, execução do servidor, worker, linters e testes unitários/integração/e2e) roda dentro do WSL `Ubuntu-26.04` em `/mnt/c/gits/pod2bullets`.

---

## 2. Os Dois Modelos de Transcrição Incluídos

| ID no Sistema | Modelo / Checkpoint | Engine / Biblioteca | Arquitetura & Tamanho | Perfil e Pontos Fortes |
|---------------|---------------------|---------------------|-----------------------|------------------------|
| `whisper-large-v3-turbo` *(Padrão)* | [`Systran/faster-whisper-large-v3-turbo`](https://huggingface.co/Systran/faster-whisper-large-v3-turbo) | `faster-whisper` (`ctranslate2`) | OpenAI Whisper Large v3 Turbo (809M params, ~1.5 GB) | **Estado da arte multilíngue (99 idiomas, excelente em PT-BR e EN).** ~6× mais rápido que o `large-v3` original mantendo precisão quase idêntica. Possui filtro VAD Silero integrado para pular silêncios e vinhetas musicais. Usa ~1.8 GB de VRAM em `float16`/`int8_float16`. |
| `parakeet-tdt-0.6b-v3` | [`istupakov/parakeet-tdt-0.6b-v3-onnx`](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx) (`nemo-parakeet-tdt-0.6b-v3`) | `onnx-asr` (`onnxruntime`) | NVIDIA FastConformer-TDT v3 (600M params, ~650 MB em INT8 / 1.2 GB FP16) | **Estado da arte da NVIDIA (#1 em eficiência/WER no Open ASR Leaderboard).** Suporta 25 idiomas nativamente (**incluindo Português e Inglês**) com pontuação e capitalização automáticas, rodando em velocidade extrema tanto em GPU quanto em CPU. |

> **Extensibilidade imediata:** O `ModelRegistry` também permite adicionar novos modelos apenas editando a configuração ou via UI/CLI (por exemplo, `whisper-large-v3` completo de 1.55B params ou `whisper-small` já ficam catalogados como opções extras instaláveis com 1 clique).

---

## 3. Organização de Pastas do Projeto

```text
pod2bullets/
├── AGENTS.md                        # Protocolo único multiagente e handoff transparente
├── CLAUDE.md                        # Configuração Claude Code -> @AGENTS.md
├── GEMINI.md                        # Configuração Gemini CLI -> @./AGENTS.md
├── PLAN.md                          # Este plano faseado
├── PROGRESS.md                      # Tabela de progresso + Checkpoint de Handoff Ativo + Log
├── pyproject.toml                   # Metadados Python, dependências, ruff, pytest
├── .gitattributes                   # Garante LF em scripts/código para interoperabilidade Windows <-> WSL
├── .gitignore                       # Ignora .venv, caches e dados locais pesados (data/models, data/podcasts)
├── .claude/
│   ├── settings.json
│   └── commands/                    # /status, /next, /handoff, /verify
├── .gemini/
│   ├── settings.json
│   └── commands/                    # /status, /next, /handoff, /verify (espelhados em TOML)
├── scripts/
│   ├── setup_wsl.sh                 # Cria .venv no Ubuntu-26.04, instala pacotes e valida GPU/CPU
│   └── download_models.py           # Faz pré-download / verificação dos 2 modelos SOTA em data/models/
├── src/
│   └── pod2bullets/
│       ├── __init__.py
│       ├── config.py                # Configurações (paths, porta, device CUDA/CPU, modelo default)
│       ├── models.py                # Entidades e DTOs (SubscriptionList, PodcastFeed, Episode, Transcript, ModelInfo)
│       ├── naming.py                # Slugify seguro e determinístico para pastas e arquivos
│       ├── db/
│       │   ├── __init__.py
│       │   ├── schema.sql           # Schema SQLite (lists, feeds, feed_lists, episodes, transcripts, jobs, settings)
│       │   ├── connection.py        # Gerenciador de conexão SQLite (WAL mode para leitura/escrita concorrente)
│       │   └── repository.py        # Operações CRUD atômicas e consultas filtradas
│       ├── feeds/
│       │   ├── __init__.py
│       │   ├── parser.py            # Parse de RSS/Atom (feedparser + httpx) extraindo enclosures de áudio
│       │   ├── opml.py              # Importação e exportação de listas de subscrição via OPML
│       │   └── service.py           # Sincronização de feeds (apenas metadados, ZERO download de áudio)
│       ├── downloader/
│       │   ├── __init__.py
│       │   └── service.py           # Download sob demanda com escrita atômica (.part -> final), progresso e sha256
│       ├── transcriber/
│       │   ├── __init__.py
│       │   ├── base.py              # Protocol TranscriberEngine + TranscriptionResult / Segment
│       │   ├── audio.py             # Decodificação PyAV (qualquer formato -> numpy 16kHz mono float32)
│       │   ├── registry.py          # Catálogo de modelos, verificação de instalação em data/models/ e factory
│       │   ├── faster_whisper_engine.py  # Implementação Engine 1 (whisper-large-v3-turbo e outros CTranslate2)
│       │   ├── onnx_asr_engine.py        # Implementação Engine 2 (parakeet-tdt-0.6b-v3 via ONNX Runtime)
│       │   └── fake_engine.py       # Engine leve e determinística para testes automatizados rápidos
│       ├── worker/
│       │   ├── __init__.py
│       │   └── queue.py             # Worker em background: encadeia Download -> Transcrição automaticamente
│       ├── web/
│       │   ├── __init__.py
│       │   ├── app.py               # Aplicação FastAPI + ciclo de vida do worker
│       │   ├── routes/
│       │   │   ├── lists.py         # Gestão de listas/categorias e OPML
│       │   │   ├── feeds.py         # Subscrições e atualização de metadados RSS
│       │   │   ├── episodes.py      # Listagem, clique para baixar, status em tempo real, leitura e download .txt
│       │   │   └── models.py        # Seleção do modelo ativo, status dos modelos instalados, download de modelo
│       │   ├── templates/           # Jinja2 + HTMX (interface responsiva, limpa e reativa sem build JS)
│       │   └── static/              # CSS moderno e assets estáticos
│       └── cli.py                   # CLI Typer: `pod2bullets serve`, `models`, `feeds`, `transcribe`
├── data/                            # Diretório de dados em tempo de execução
│   ├── db/                          # Banco SQLite (`pod2bullets.sqlite`)
│   ├── models/                      # Pesos dos modelos ASR baixados localmente
│   │   ├── whisper-large-v3-turbo/
│   │   └── parakeet-tdt-0.6b-v3/
│   ├── podcasts/                    # Áudios e transcrições organizados por podcast e episódio
│   │   └── <podcast-slug>/
│   │       └── <YYYY-MM-DD>__<episode-slug>/
│   │           ├── audio.<ext>
│   │           ├── episode.json
│   │           └── transcripts/
│   │               ├── <episode-slug>__whisper-large-v3-turbo.txt
│   │               ├── <episode-slug>__whisper-large-v3-turbo.meta.json
│   │               ├── <episode-slug>__parakeet-tdt-0.6b-v3.txt
│   │               └── <episode-slug>__parakeet-tdt-0.6b-v3.meta.json
│   └── tmp/                         # Downloads parciais em andamento (.part)
└── tests/
    ├── conftest.py                  # Fixtures globais (DB temporário, áudio sintético WAV/MP3, RSS local)
    ├── fixtures/
    │   └── make_audio_fixtures.py   # Gera arquivos de áudio curtos e XMLs RSS para testes offline
    ├── unit/                        # Testes unitários por módulo
    ├── integration/                 # Testes de integração (FastAPI TestClient, Worker, Engines ASR)
    └── e2e/                         # Fluxo completo do usuário de ponta a ponta
```

---

## 4. Fluxo de Estado do Episódio e Pipeline em Background

```mermaid
stateDiagram-v2
    [*] --> available : Sincronização do Feed RSS (apenas metadados, sem baixar áudio)
    available --> queued_download : Usuário clica em "Baixar e Transcrever" (escolhendo modelo ou usando o padrão)
    queued_download --> downloading : Worker inicia streaming do áudio para data/tmp/*.part
    downloading --> downloaded : Áudio salvo em data/podcasts/<pod>/<ep>/audio.<ext>
    downloaded --> queued_transcription : Enfileirado automaticamente pelo Worker pós-download
    queued_transcription --> transcribing : Engine escolhida (whisper-large-v3-turbo ou parakeet-tdt-0.6b-v3) processa o áudio
    transcribing --> completed : Grava .txt puro + .meta.json em transcripts/ e indexa no SQLite
    downloading --> failed : Erro de rede/disco (permite tentar novamente com 1 clique)
    transcribing --> failed : Erro na transcrição (mantém o áudio já baixado; permite re-transcrever sem baixar de novo)
    completed --> queued_transcription : Usuário solicita nova transcrição com outro modelo instalado
```

---

## 5. Passos de Execução Faseados

Cada passo (`F<fase>.<item>`) é dimensionado para ser implementado, testado no **WSL (`Ubuntu-26.04`)** e registrado em [PROGRESS.md](PROGRESS.md) em uma única etapa coesa.
Qualquer agente (**Claude Code** ou **Gemini CLI**) pode executar qualquer passo ou assumir um passo em andamento via handoff.

### Fase 0 — Fundação, Ambiente WSL Ubuntu 26.04 e Fixtures de Teste
- **F0.1 Scaffolding Python e Ambiente WSL (`Ubuntu-26.04`)**
  - Criar `pyproject.toml` (Python ≥ 3.12, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`, `feedparser`, `av`, `faster-whisper`, `onnx-asr`, `typer`, `rich`, e dev: `pytest`, `pytest-asyncio`, `ruff`).
  - Criar `scripts/setup_wsl.sh` que cria e provisiona `.venv` no WSL `Ubuntu-26.04`, configura suporte GPU/CPU e valida os imports.
  - Criar `src/pod2bullets/__init__.py`, `src/pod2bullets/config.py`, `src/pod2bullets/naming.py` e CLI inicial (`src/pod2bullets/cli.py`).
  - **Critério de aceite (WSL):** `./scripts/setup_wsl.sh` conclui sem erros no `Ubuntu-26.04`; `ruff check .` e `pytest` passam; `pod2bullets --help` funciona.
- **F0.2 Gerador de Fixtures Offline (RSS + Áudios Sintéticos)**
  - Criar `tests/fixtures/make_audio_fixtures.py` e `tests/conftest.py` que geram programaticamente (usando `wave` / `av` + XML local) arquivos de áudio curtos de teste (`.wav` e `.mp3`/`ogg` com fala sintética ou tom/fala de fixture) e feeds RSS válidos apontando para um servidor HTTP local de teste.
  - **Depende de:** `F0.1`.
  - **Critério de aceite (WSL):** `pytest tests/unit/test_fixtures.py` valida a criação de feeds RSS e áudios decodificáveis por `PyAV`.

### Fase 1 — Banco de Dados e Gestão de Listas de Subscrições (Requisito 1)
- **F1.1 Camada de Persistência SQLite e Modelos de Domínio**
  - Implementar `src/pod2bullets/models.py`, `src/pod2bullets/db/schema.sql`, `src/pod2bullets/db/connection.py` e `src/pod2bullets/db/repository.py`.
  - Tabelas: `subscription_lists` (id, name, slug, description, created_at), `feeds` (id, title, slug, rss_url, site_url, description, image_url, last_synced_at), `feed_list_members` (relação N:N entre feeds e listas), `episodes` (id, feed_id, guid, title, slug, published_at, duration_seconds, audio_url, audio_ext, summary, status, local_audio_path, file_size_bytes, sha256, error_message), `transcripts` (id, episode_id, model_id, engine_name, language, plain_text_path, meta_json_path, char_count, word_count, duration_proc_seconds, created_at), `jobs` (fila persistente de download/transcrição) e `settings` (chave/valor, incluindo `default_model_id`).
  - **Depende de:** `F0.1`.
  - **Critério de aceite (WSL):** `pytest tests/unit/test_repository.py` cobre criação de listas, associação de feeds a múltiplas listas, busca de episódios por lista/status e registro de transcrições.
- **F1.2 Parser de Feeds RSS/Atom, OPML e Sincronização Sem Download Automático**
  - Implementar `src/pod2bullets/feeds/parser.py`, `src/pod2bullets/feeds/opml.py` e `src/pod2bullets/feeds/service.py`.
  - Sincronizar um feed busca apenas o XML via `httpx`, extrai episódios com enclosure de áudio e insere novos episódios no SQLite com `status = 'available'` e `local_audio_path = NULL`.
  - Importar/exportar OPML mapeia categorias `<outline text="Categoria">` diretamente para `subscription_lists`.
  - **Depende de:** `F0.2`, `F1.1`.
  - **Critério de aceite (WSL):** `pytest tests/unit/test_feeds.py` garante que atualizar um feed cadastra todos os episódios como `available`, **não faz nenhuma requisição HTTP para as URLs de áudio** (verificado por spy/mock do `httpx`), e importa/exporta OPML preservando as listas.

### Fase 2 — Download Manual Sob Demanda e Organização de Pastas (Requisitos 2 e 5)
- **F2.1 Serviço de Download Sob Demanda e Layout de Pastas**
  - Implementar `src/pod2bullets/downloader/service.py`.
  - Somente quando acionado para um `episode_id` específico, faz streaming do áudio via `httpx` para `data/tmp/<episode_id>.part`, calcula `sha256` e move atomicamente para `data/podcasts/<podcast-slug>/<YYYY-MM-DD>__<episode-slug>/audio.<ext>`, gravando também `episode.json` na pasta do episódio e atualizando o status para `downloaded`.
  - Suporta callback de progresso (bytes baixados / total) e tratamento de falhas sem deixar arquivos corrompidos.
  - **Depende de:** `F1.2`.
  - **Critério de aceite (WSL):** `pytest tests/unit/test_downloader.py` valida a árvore exata de pastas criadas, escrita atômica, cálculo de hash e transição `available` → `downloading` → `downloaded` (e `failed` em erro HTTP).

### Fase 3 — Motor de Transcrição Local Plugável + 2 Modelos SOTA (Requisitos 4, 7 e 8)
- **F3.1 Protocolo `TranscriberEngine`, Decodificador `PyAV` e `ModelRegistry`**
  - Implementar `src/pod2bullets/transcriber/base.py` (protocolo `TranscriberEngine`, dataclasses `TranscriptionSegment` e `TranscriptionResult` com texto puro limpo + segmentos com timestamps).
  - Implementar `src/pod2bullets/transcriber/audio.py` usando `av` (`PyAV`) para converter qualquer arquivo de áudio em array `numpy` 16 kHz mono `float32` (zero dependência de binário externo `ffmpeg`).
  - Implementar `src/pod2bullets/transcriber/registry.py` com catálogo contendo os dois modelos principais pré-configurados (`whisper-large-v3-turbo` e `parakeet-tdt-0.6b-v3`), detecção de modelos já baixados em `data/models/<model_id>/`, troca de modelo ativo e registro fácil de novos modelos.
  - **Depende de:** `F0.2`, `F1.1`.
  - **Critério de aceite (WSL):** `pytest tests/unit/test_transcriber_registry.py` testa decodificação de áudio via `PyAV`, listagem dos modelos, verificação de status de instalação, seleção do modelo pelo usuário e transcrição via `FakeTranscriberEngine`.
- **F3.2 Implementação dos 2 Modelos SOTA (`whisper-large-v3-turbo` + `parakeet-tdt-0.6b-v3`) e Script de Provisionamento**
  - Implementar `src/pod2bullets/transcriber/faster_whisper_engine.py` (CTranslate2, auto-detecção CUDA `float16`/`int8_float16` na RTX 2060 SUPER ou CPU `int8`, `vad_filter=True`, cache local em `data/models/whisper-large-v3-turbo`).
  - Implementar `src/pod2bullets/transcriber/onnx_asr_engine.py` (ONNX Runtime, `nemo-parakeet-tdt-0.6b-v3`, cache local em `data/models/parakeet-tdt-0.6b-v3`, suporte a áudios longos com chunking limpo).
  - Criar `scripts/download_models.py` e o subcomando `pod2bullets models download [--model <id> | --all]` para baixar/verificar os 2 modelos em `data/models/`.
  - **Depende de:** `F3.1`.
  - **Critério de aceite (WSL):** Testes unitários das duas engines com mocks + teste de integração real (`@pytest.mark.real_models`) rodando os 2 modelos localmente no WSL `Ubuntu-26.04` sobre um áudio em português/inglês e gerando texto puro válido.

### Fase 4 — Worker de Backend: Pipeline Download → Transcrição Automática (Requisito 3)
- **F4.1 Fila Persistente e Worker Assíncrono em Background**
  - Implementar `src/pod2bullets/worker/queue.py`.
  - Quando o usuário clica para baixar um episódio (escolhendo o modelo `model_id` ou usando o modelo padrão ativo), o sistema cria um job `download_and_transcribe` no SQLite.
  - O worker em background:
    1. Executa o download do áudio (se ainda não estiver baixado localmente);
    2. **Automaticamente** inicia a transcrição em background com o modelo escolhido;
    3. Grava o texto puro em `data/podcasts/<podcast-slug>/<YYYY-MM-DD>__<episode-slug>/transcripts/<episode-slug>__<model-id>.txt` e os metadados/segmentos em `.meta.json`;
    4. Registra a transcrição na tabela `transcripts` e marca o episódio como `completed`.
  - Se o episódio já foi baixado antes e o usuário escolher outro modelo para transcrever, o worker pula o download e roda apenas a transcrição no segundo modelo, preservando ambos os `.txt`!
  - **Depende de:** `F2.1`, `F3.1`.
  - **Critério de aceite (WSL):** `pytest tests/integration/test_worker_pipeline.py` comprova que acionar o download de um episódio dispara automaticamente a transcrição em background até gerar o `.txt`, e que re-transcrever com um 2º modelo reaproveita o áudio local sem baixá-lo novamente.

### Fase 5 — Interface Web e API FastAPI (Requisitos 1, 2, 3 e 7)
- **F5.1 Backend FastAPI: Rotas de Listas, Subscrições, Modelos e Episódios**
  - Implementar `src/pod2bullets/web/app.py` e as rotas em `src/pod2bullets/web/routes/`.
  - Endpoints REST + HTML/HTMX para:
    - Criar/editar/excluir listas de subscrições (`subscription_lists`);
    - Adicionar feed RSS a uma ou mais listas, importar/exportar OPML e sincronizar metadados (`POST /feeds/sync` — nunca baixa áudio);
    - Listar e gerenciar modelos de transcrição (`GET /models`, `POST /models/default`, `POST /models/{model_id}/download`);
    - Acionar manualmente o download + transcrição de um episódio (`POST /episodes/{id}/download` recebendo `model_id` opcional);
    - Acionar nova transcrição de episódio já baixado com outro modelo (`POST /episodes/{id}/transcribe`);
    - **Visualizar a transcrição em texto puro na Web** (`GET /episodes/{id}/transcripts/{model_id}` em página HTML de leitura limpa e `GET /api/episodes/{id}/transcripts/{model_id}/text` em texto puro `text/plain`);
    - **Baixar o arquivo `.txt` da transcrição** (`GET /episodes/{id}/transcripts/{model_id}/download` com `Content-Disposition: attachment; filename="...txt"`).
  - **Depende de:** `F4.1`.
  - **Critério de aceite (WSL):** `pytest tests/integration/test_web_api.py` valida todas as rotas com `TestClient`, verificando leitura web da transcrição, headers de download `.txt` e troca de modelo.
- **F5.2 Interface Web Completa (Jinja2 + HTMX + CSS Moderno)**
  - Implementar templates em `src/pod2bullets/web/templates/` e estilos em `src/pod2bullets/web/static/`:
    - **Sidebar de Listas de Subscrições:** filtrar feeds por lista/categoria, criar nova lista, adicionar feed RSS, importar/exportar OPML, botão "Atualizar Feeds (apenas catálogo)".
    - **Seletor de Modelo de Transcrição no Topo:** mostra os modelos instalados (`whisper-large-v3-turbo`, `parakeet-tdt-0.6b-v3`, etc.), permite escolher o modelo padrão com 1 clique e baixar modelos adicionais.
    - **Lista de Episódios do Podcast/Lista:** mostra status claro (`Disponível para baixar`, `Baixando...`, `Transcrevendo com <modelo>...`, `Transcrito`), botão explícito **"Baixar e Transcrever"** (com seletor rápido de modelo) e atualização automática de status em tempo real via HTMX polling enquanto houver jobs ativos.
    - **Página/Painel de Leitura da Transcrição na Web:** exibe o texto puro formatado para leitura confortável, busca rápida no texto, botão **"Copiar Texto"**, botão **"Baixar .txt"**, abas para alternar entre transcrições feitas com modelos diferentes (ex.: comparar `whisper-large-v3-turbo` vs `parakeet-tdt-0.6b-v3`) e botão para rodar outro modelo sobre o mesmo áudio.
  - **Depende de:** `F5.1`.
  - **Critério de aceite (WSL):** `pytest tests/integration/test_web_ui.py` verifica a renderização HTML de todas as telas, presença dos botões de download manual, seletor de modelos e links de visualização/download `.txt`.

### Fase 6 — CLI Completa, Teste Ponta a Ponta (E2E) com os 2 Modelos e Documentação
- **F6.1 CLI Completa e Teste Ponta a Ponta (E2E) no WSL Ubuntu 26.04**
  - Completar `src/pod2bullets/cli.py` (`pod2bullets serve`, `pod2bullets models list/download/use`, `pod2bullets lists`, `pod2bullets feeds`, `pod2bullets episodes`).
  - Criar `tests/e2e/test_full_workflow.py` testando o fluxo completo no WSL `Ubuntu-26.04`:
    1. Criar lista de subscrição;
    2. Cadastrar feed RSS na lista e sincronizar catálogo;
    3. Confirmar que **nenhum** áudio foi baixado automaticamente;
    4. Clicar/acionar download de 1 episódio escolhendo o Modelo 1 (`whisper-large-v3-turbo`);
    5. Aguardar o worker concluir download + transcrição em background;
    6. Ler a transcrição via Web e baixar o arquivo `.txt`;
    7. Trocar para o Modelo 2 (`parakeet-tdt-0.6b-v3`), transcrever o mesmo episódio e validar que ambos os arquivos `.txt` estão disponíveis na Web e em disco.
  - **Depende de:** `F3.2`, `F5.2`.
  - **Critério de aceite (WSL):** `pytest` completo (unit + integration + e2e) 100% verde no WSL `Ubuntu-26.04`.
- **F6.2 Documentação Final (`README.md`) e Guia de Operação no WSL**
  - Escrever `README.md` em português detalhando instalação no WSL `Ubuntu-26.04`, como iniciar o servidor web, como gerenciar os modelos de transcrição, estrutura das pastas `data/podcasts/` e `data/models/`, e como usar o handoff entre Claude Code e Gemini CLI.
  - **Depende de:** `F6.1`.
  - **Critério de aceite (WSL):** `ruff check .`, `ruff format --check .` e `pytest` 100% verdes.

---

## 6. Registro de Decisões Arquiteturais

1. **FastAPI + Jinja2 + HTMX em vez de SPA separada em Node/React:** mantém 100% da stack em Python (Requisito 6), elimina necessidade de manter ambiente Node/npm em paralelo no WSL e entrega atualização em tempo real do progresso de download/transcrição em background com código enxuto e fácil de manter por qualquer agente.
2. **SQLite em modo WAL (`Write-Ahead Logging`):** permite que o worker de transcrição em background atualize o progresso dos jobs simultaneamente às leituras da interface web sem bloqueios (`database is locked`).
3. **Decodificação de áudio universal via `PyAV` (`av`):** a distro `Ubuntu-26.04` no WSL não traz o binário `/usr/bin/ffmpeg` pré-instalado por padrão; usar `PyAV` resolve 100% dos formatos de podcast usando as bibliotecas FFmpeg embutidas no wheel Python, sem exigir `sudo apt install`.
4. **Dois motores e modelos SOTA complementares (`faster-whisper` + `onnx-asr`):**
   - `whisper-large-v3-turbo` (OpenAI / CTranslate2) e `parakeet-tdt-0.6b-v3` (NVIDIA NeMo / ONNX Runtime) possuem wheels nativos para Python 3.14 no Linux (`cp314` / `py3-none-any`), rodam localmente sem custo e permitem ao usuário escolher entre as duas melhores famílias de ASR open-source da atualidade.

