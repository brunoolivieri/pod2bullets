# Guia de Desenvolvimento para Agentes de IA (`pod2bullets`)

Este documento serve como mapa de navegação, referência de engenharia e guia de boas práticas para **Agentes de IA autônomos** (Gemini CLI, Claude Code e compatíveis) que operam neste repositório.

---

## 1. Contexto de Execução e Regras Inegociáveis

1. **Ambiente Obrigatório — WSL (`Ubuntu-26.04`):**
   - O código roda exclusivamente no ambiente Linux do WSL `Ubuntu-26.04`.
   - Caminho Linux: `/mnt/c/gits/pod2bullets`
   - Python: 3.14 (`/usr/bin/python3`) com ambiente virtual em `.venv`.
   - **Regra de Ouro do Terminal:** Sempre que executar comandos do host Windows, utilize o prefixo:
     ```powershell
     wsl -d Ubuntu-26.04 -- bash -lc "cd /mnt/c/gits/pod2bullets && source .venv/bin/activate && <comando>"
     ```
   - **Nunca** crie ou execute `.venv` com Python do Windows na raiz para não corromper os binários do Linux.

2. **Aceleração por GPU & Preload CUDA 12:**
   - GPU disponível: NVIDIA GeForce RTX 2060 SUPER (8 GB VRAM, CUDA 12.9).
   - O módulo `src/pod2bullets/transcriber/cuda_env.py` (`ensure_cuda_libraries_loaded()`) é invocado no boot da CLI, FastAPI e engines. Ele localiza as bibliotecas `nvidia/*/lib` do `.venv` e faz pré-carregamento com `ctypes.RTLD_GLOBAL` (`libcublas.so.12`, `libcudart.so.12`, `libcudnn.so.9`).
   - Mantenha sempre suporte a fallback automático para CPU (`int8`) caso CUDA não esteja presente.

3. **Regras de Negócio Fundamentais:**
   - **Zero Download Automático de Áudio:** Sincronizar feeds RSS (`POST /feeds/sync` ou `/feeds/add`) faz download **apenas do XML**. O áudio só pode ser baixado se o usuário solicitar explicitamente para o episódio (`POST /episodes/{id}/download`).
   - **Áudio Temporário:** O arquivo de áudio (`.mp3`, `.m4a`, etc.) é automaticamente excluído do disco pelo `BackgroundWorker` assim que a transcrição `.txt` e o `.meta.json` são salvos com sucesso.
   - **Transcrição 100% Local:** O processamento ASR é sempre local (Whisper ou Parakeet). Nunca envie áudios para APIs de nuvem. As APIs de LLM externas recebem apenas o texto já transcrito para geração de resumos.
   - **Decodificação de Áudio sem FFmpeg Global:** Todas as decodificações utilizam a biblioteca `av` (`PyAV`), convertendo qualquer formato de áudio para PCM 16 kHz mono `float32` em memória/streaming.

---

## 2. Mapa do Código-Fonte (`src/pod2bullets/`)

| Módulo / Arquivo | Responsabilidade | Pontos de Atenção para IA |
| :--- | :--- | :--- |
| `models.py` | Dataclasses de domínio (`PodcastFeed`, `Episode`, `Transcript`, `Job`, `SubscriptionList`, `ModelInfo`, `Summary`) | Mantenha consistência de tipos e enums (`EpisodeStatus`, `JobStatus`). |
| `config.py` | Configurações globais via `Settings` (paths, portas, modelo ASR padrão, timeouts) | Usa caminhos relativos à raiz do projeto. |
| `naming.py` | Sanitização e criação de slugs para diretórios e arquivos | Garante nomes de arquivos determinísticos e seguros no SO. |
| `db/connection.py` | Pool e conexão SQLite em modo WAL (`busy_timeout=30000`, `foreign_keys=ON`) | Sempre feche conexões manuais ou utilize context managers. |
| `db/repository.py` | CRUD atômico para todas as entidades (feeds, listas, episódios, transcrições, jobs, resumos, settings) | Evite queries diretas fora desta camada; use métodos existentes. |
| `feeds/parser.py` | Parsing de XML RSS/Atom via `feedparser` e `httpx` | Extrai enclosures de áudio, capa e metadados com timeout resiliente. |
| `feeds/opml.py` | Importação e exportação de subscrições e listas em formato OPML | Preserva listas/categorias do OPML. |
| `downloader/service.py` | Streaming de download do áudio sob demanda | Grava em `data/tmp/*.part` e faz rename atômico para `data/podcasts/`. |
| `transcriber/base.py` | Protocolo `TranscriberEngine` e classes `TranscriptionResult`, `Segment` | Todo transcritor deve implementar `transcribe(audio_path, **kwargs)`. |
| `transcriber/registry.py` | Catálogo de modelos suportados, verificação de disco e factory | Ponto único para adicionar ou listar modelos ASR locais. |
| `transcriber/faster_whisper_engine.py` | Implementação para modelos CTranslate2 (ex.: `whisper-large-v3-turbo`) | Emite progresso de 5% em 5% sem poluir o terminal com frases. |
| `transcriber/onnx_asr_engine.py` | Implementação para NVIDIA Parakeet TDT via ONNX Runtime | Rápido e multilíngue (PT/EN); usa chunks e callback de progresso. |
| `worker/queue.py` | Worker em background assíncrono (`BackgroundWorker`) | Processa fila de jobs (`download` -> `transcribe` -> `summarize`). Atualiza progresso e remove MP3. |
| `llm/service.py` | Integração com LLMs (Gemini, Claude, ChatGPT, DeepSeek, Qwen) | Suporta múltiplos provedores, fallback dinâmico para modelos recentes e histórico de tentativas. |
| `web/app.py` | Setup do FastAPI, montagem de rotas, inicialização do worker e logging | Configura Jinja2, HTMX estático e handlers de erro. |
| `web/routes/` | Endpoints da aplicação divididos por domínio (`episodes`, `feeds`, `lists`, `llm`, `logs`, `models`, `queue`, `summaries`) | Respondem requisições HTMX com parciais HTML ou redirecionamentos. |
| `web/templates/` | Templates Jinja2 estruturados com base em HTMX | Reatividade declarativa sem frameworks JavaScript externos. |
| `cli.py` | Interface de linha de comando com Typer | Comandos: `serve`, `models`, `feeds`, `lists`, `transcribe`. |

---

## 3. Padrões de Concorrência, Estado e HTMX

### 3.1. Máquina de Estados do Episódio e Job
O ciclo de vida do episódio e de seus jobs é controlado via SQLite:

```
[available] -> Usuário clica p/ baixar -> [queued_download] (job: pending)
  -> Worker assume -> [downloading] (job: running, progresso 0%..100%)
  -> Áudio salvo -> [downloaded] -> [queued_transcription] (job: pending)
  -> Worker assume -> [transcribing] (job: running, progresso 0%..100% de 5 em 5%)
  -> Grava .txt + .meta.json -> [completed] -> Audio MP3 apagado
  -> Se LLM foi solicitado: [summarizing] -> Grava resumo no banco e disco -> Concluído
```

### 3.2. Regras para Endpoints HTMX
- **Respostas Parciais:** Rotas disparadas por `hx-post` ou `hx-get` devem retornar apenas o fragmento HTML relevante para o target (ex.: `<div class="episode-card" id="ep-card-123">...</div>`), nunca a página completa com `<head>` e `<body>`.
- **Prevenção de Fórmulas Quebradas em Python:** Se for construir HTML com f-strings Python (como em `summaries.py` ou `episodes.py`), **nunca** misture sintaxe Jinja2 (`{% if %}`) diretamente dentro da string Python. Use operadores ternários ou condicionais Python normais.
- **Supressão de Polling Inútil:** Rotas que sofrem polling frequente (como `/system/status` ou `/episodes/card/{id}`) devem retornar vazio (`""`) quando ociosas ou status `200` silencioso para evitar sobrecarga no log.

---

## 4. Como Estender o Sistema (Cookbook para IA)

### 4.1. Adicionar um Novo Modelo ASR
1. Em `src/pod2bullets/transcriber/`:
   - Se for CTranslate2 / Faster-Whisper, registre a especificação em `src/pod2bullets/transcriber/registry.py` no dicionário `_CATALOG`.
   - Se for uma biblioteca ou arquitetura nova, crie `minha_nova_engine.py` implementando o protocolo `TranscriberEngine` e adicione o carregamento na factory `ModelRegistry.get_engine(model_id)`.
2. Adicione os metadados de exibição (nome, tamanho aproximado, VRAM recomendada) em `ModelInfo`.
3. Escreva testes unitários cobrindo o carregamento da engine com mocks/áudio sintético.

### 4.2. Adicionar um Novo Provedor de LLM
1. Em `src/pod2bullets/llm/service.py`:
   - Adicione o provedor ao dicionário `LLM_PROVIDERS` com nome, URL base, variável de ambiente da API Key e lista de modelos padrão/sugeridos.
   - Implemente ou reaproveite a chamada HTTP em `_call_provider()`.
2. Em `src/pod2bullets/web/templates/llm_settings.html`:
   - Adicione o card de configuração do novo provedor na Central de Controle de APIs.
3. Garanta que testes em `tests/unit/test_llm_service.py` validem o fluxo com respostas mockadas.

---

## 5. Checklist de Verificação Antes de Fazer Handoff ou Concluir

Sempre execute os passos abaixo no WSL `Ubuntu-26.04`:

```bash
# 1. Checagem e formatação de estilo
ruff check . && ruff format --check .

# 2. Execução da suíte completa de testes
pytest -v

# 3. Status e diff limpo no git
git status --short
```

Mantenha sempre o [`PROGRESS.md`](../PROGRESS.md) atualizado com o resumo claro do que foi implementado e qualquer detalhe relevante para o próximo agente.
