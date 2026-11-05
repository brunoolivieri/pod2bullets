# Arquitetura do Sistema (`pod2bullets`)

Este documento descreve detalhadamente a arquitetura de software, decisões de design, modelos de dados e fluxos de execução do **`pod2bullets`**.

---

## 1. Visão Geral e Princípios Arquiteturais

O `pod2bullets` é um sistema web e CLI projetado para rodar inteiramente no ambiente **WSL (`Ubuntu-26.04`)**, com aceleração por GPU NVIDIA (CUDA 12) e fallback para CPU. Ele permite gerenciar subscrições de podcasts, baixar áudios sob demanda, transcrever localmente via modelos SOTA de IA e gerar resumos inteligentes por LLMs.

### Pilares de Design
1. **Privacidade e Autonomia Total:** A transcrição ASR é 100% local. Áudios nunca saem da máquina do usuário.
2. **Zero Download Automático de Áudio:** O consumo de banda só ocorre por ordem explícita do usuário para episódios individuais.
3. **Eficiência de Disco:** O arquivo de áudio (`.mp3`, `.m4a`) é automaticamente descartado pós-transcrição, mantendo apenas o texto puro (`.txt`) e metadados (`.meta.json`).
4. **Resiliência e Concorrência:** O banco de dados SQLite opera em modo **WAL (Write-Ahead Logging)** com timeout estendido (`busy_timeout=30000`), permitindo leituras concorrentes pela interface web enquanto o worker processa jobs pesados em background.
5. **Simplicidade Operacional:** Interface reativa construída com **FastAPI + Jinja2 + HTMX**, dispensando etapas de compilação de JavaScript ou dependências em Node.js.

---

## 2. Diagrama Geral de Componentes

```mermaid
flowchart TB
    subgraph Client["Camada de Apresentação & Clientes"]
        Browser["Navegador Web (HTMX + Jinja2 + CSS)"]
        CLI["CLI Typer (pod2bullets serve / models / feeds)"]
        LogPopup["Log Viewer Popup (/logs/viewer)"]
    end

    subgraph API["Servidor Web (FastAPI)"]
        RouterEp["Routes: Episodes (/episodes)"]
        RouterFeeds["Routes: Feeds & Lists (/feeds, /lists)"]
        RouterSum["Routes: Summaries (/summaries)"]
        RouterLLM["Routes: LLM Settings (/llm)"]
        RouterQueue["Routes: Queue & Jobs (/queue)"]
        RouterLogs["Routes: Logs (/logs)"]
        ActTracker["ActivityTracker (Indicador ⏳)"]
    end

    subgraph Core["Camada de Serviços & Domínio"]
        FeedService["Feed & OPML Service"]
        DownloadService["DownloaderService (Streaming .part)"]
        Worker["BackgroundWorker (Fila Assíncrona)"]
        LLMService["LLMService (Gemini, Claude, GPT, DeepSeek, Qwen)"]
        CUDAEnv["CUDA Preloader (libcublas.so.12)"]
    end

    subgraph Engines["Engines de Transcrição ASR"]
        Registry["ModelRegistry (Catálogo & Factory)"]
        FWEngine["FasterWhisperEngine (whisper-large-v3-turbo)"]
        ONNXEngine["OnnxAsrEngine (parakeet-tdt-0.6b-v3)"]
        PyAV["Audio Normalizer (PyAV 16kHz float32 mono)"]
    end

    subgraph Storage["Persistência & Armazenamento"]
        SQLite[("SQLite WAL: data/db/pod2bullets.sqlite")]
        Filesystem["Sistema de Arquivos Local (data/podcasts/ e data/models/)"]
        LogsFolder["Logs Duplos (logs/*-APP.log e *-transcricao.log)"]
    end

    Browser <--> |"HTTP / HTMX Partials"| API
    CLI --> Core
    LogPopup <--> |"HTMX Polling /logs/tail"| RouterLogs

    API --> Core
    Core --> Storage
    Worker --> Engines
    Worker --> Storage
    Worker --> LLMService
    Engines --> PyAV
    CUDAEnv -.-> Engines
```

---

## 3. Fluxo de Processamento de Ponta a Ponta

O diagrama de sequência a seguir ilustra o ciclo completo de um episódio: da sincronização do feed ao resumo final.

```mermaid
sequenceDiagram
    autonumber
    actor User as Usuário
    participant Web as Web UI (HTMX)
    participant API as FastAPI / Repositório
    participant Worker as BackgroundWorker
    participant Downloader as DownloaderService
    participant ASR as TranscriberEngine (Whisper/Parakeet)
    participant LLM as LLMService (APIs Externas)
    participant Disk as Disco (data/podcasts & transcripts)

    User->>Web: Clica em "Atualizar Feed" ou cadastra URL
    Web->>API: POST /feeds/sync
    API->>API: Baixa apenas XML RSS e indexa episódios (status: available)
    API-->>Web: Lista episódios (ZERO áudio baixado)

    User->>Web: Clica em "⬇️ Baixar e Transcrever" (Seleciona Modelo ASR + LLM)
    Web->>API: POST /episodes/{id}/download (model_id, llm_provider)
    API->>API: Cria Job no SQLite (status: pending)
    API-->>Web: Card atualizado com estado "🕒 Na Fila (#1)"

    loop Worker em Background
        Worker->>API: Busca próximo job pendente
        Worker->>Downloader: Inicia download do enclosure de áudio
        Downloader->>Disk: Streaming para data/tmp/xyz.part -> final audio.mp3
        Worker->>API: Atualiza progresso do Download (0% a 100%)
        Worker->>ASR: Transcreve áudio (PyAV 16kHz mono -> Ingestão ASR)
        ASR-->>Worker: Emite progresso em marcos de 5% em 5%
        Worker->>API: Atualiza progresso da Transcrição
        Worker->>Disk: Grava .txt puro e .meta.json em transcripts/
        Worker->>Disk: Remove arquivo temporário audio.mp3 (unlink)
        
        alt Usuário escolheu resumir via LLM
            Worker->>LLM: Envia texto da transcrição com prompt customizado
            LLM-->>Worker: Retorna resumo estruturado
            Worker->>Disk: Grava resumo em .txt
            Worker->>API: Registra resumo na tabela 'summaries'
        end
        
        Worker->>API: Marca Job como completed
    end

    Web->>API: Polling reativo no card do episódio
    API-->>Web: Exibe botões "📖 Ler Transcrição", "📑 Ver Resumo" e "💾 Baixar .TXT"
```

---

## 4. Modelo de Dados Relacional (SQLite WAL)

O banco de dados é estruturado em SQLite com chaves estrangeiras ativas e índices em colunas de alta consulta.

```mermaid
erDiagram
    lists ||--o{ feed_lists : contem
    feeds ||--o{ feed_lists : associado
    feeds ||--o{ episodes : possui
    episodes ||--o{ transcripts : gera
    episodes ||--o{ summaries : gera
    episodes ||--o{ jobs : enfileira

    lists {
        int id PK
        string name
        datetime created_at
    }

    feeds {
        int id PK
        string url
        string title
        string description
        string image_url
        string feed_type
        datetime last_fetched_at
    }

    feed_lists {
        int feed_id FK
        int list_id FK
    }

    episodes {
        int id PK
        int feed_id FK
        string title
        string audio_url
        string status
        int duration_seconds
        datetime published_at
    }

    transcripts {
        int id PK
        int episode_id FK
        string model_id
        string txt_path
        string json_path
        float duration_proc_seconds
        datetime created_at
    }

    summaries {
        int id PK
        int episode_id FK
        string provider
        string model
        string prompt_used
        string summary_text
        string txt_path
        float duration_proc_seconds
        datetime created_at
    }

    jobs {
        int id PK
        int episode_id FK
        string job_type
        string status
        float progress_percent
        string model_id
        string error_message
        datetime created_at
        datetime updated_at
    }

    settings {
        string key PK
        string value
    }
```

---

## 5. Subsistemas Críticos em Detalhe

### 5.1. Normalização de Áudio com PyAV (`audio.py`)
Podcasts utilizam uma variedade enorme de codecs e containers (`.mp3`, `.m4a`, `.aac`, `.opus`, `.ogg`, `.wav`).
Em vez de depender de um binário do `ffmpeg` instalado no sistema operacional do host:
- A biblioteca `av` (`PyAV`) decodifica o fluxo de áudio diretamente em memória.
- O reamostrador (`AudioResampler`) converte os frames para taxa de amostragem de **16.000 Hz, 1 canal (mono) e formato `fltp` (float32)**.
- O resultado é um array NumPy unidimensional pronto para ingestão direta pelos tensores dos modelos Whisper ou Parakeet.

### 5.2. Preloader de CUDA 12 (`cuda_env.py`)
No WSL com Python 3.14 e bibliotecas instaladas via wheel (como `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`), bibliotecas nativas de C++ não são automaticamente descobertas pelo `ctranslate2` sem prévia configuração:
- `ensure_cuda_libraries_loaded()` inspeciona os diretórios `.venv/lib/python3.14/site-packages/nvidia/*/lib` e `/usr/lib/wsl/lib`.
- Configura a variável `LD_LIBRARY_PATH`.
- Executa chamadas `ctypes.CDLL(..., mode=ctypes.RTLD_GLOBAL)` para as bibliotecas `libcudart.so.12`, `libcublasLt.so.12`, `libcublas.so.12` e `libcudnn*.so.9`.
- Se necessário, efetua um auto-reexec do processo para que o linker dinâmico do Linux reconheça os novos paths antes da inicialização do CTranslate2.

### 5.3. Gerenciamento de Filas e Throttling (`queue.py`)
- O `BackgroundWorker` opera em uma thread dedicada no mesmo processo do FastAPI.
- Ele faz polling na tabela `jobs` a cada segundo quando ocioso.
- Durante o processamento de áudio ou transcrição, atualizações de progresso para a tabela `jobs` sofrem **throttling** (máximo de uma gravação a cada 0.5s ou a cada marco de 5%), eliminando contention no banco SQLite.
- O cancelamento de jobs interrompe o fluxo imediatamente, encerra subprocessos/loops de inferência e limpa arquivos residuais `.part`.

### 5.4. Integração Multi-LLM Resiliente (`llm/service.py`)
- Suporta 5 provedores líderes: **Google Gemini**, **Anthropic Claude**, **OpenAI ChatGPT**, **DeepSeek** e **Alibaba Qwen**.
- **Descoberta Dinâmica de Modelos:** Em caso de erro `404 / Model Not Found` ou obsolescência de modelos, o serviço consulta dinamicamente a rota `/models` do provedor para eleger o modelo equivalente mais moderno.
- **Histórico Transparente de Tentativas:** Registra cada tentativa (`Tentativa 1/3`, `Tentativa 2/3`) no log da aplicação sem lançar stack traces alarmantes na interface.
- **Coexistência de Múltiplos Resumos:** O usuário pode gerar um resumo com Gemini e outro com Claude para o mesmo episódio. O repositório armazena todos na tabela `summaries` com seus respectivos caminhos `.txt`, permitindo comparação visual na tela `/summaries`.

### 5.5. Arquitetura de Logging Duplo (`logging_config.py`)
O sistema divide automaticamente a telemetria em dois fluxos persistentes em disco na pasta `logs/`:
1. `YYYY-MM-DD-HH-MM-APP.log`: Registra requisições da web, inicializações de serviços, sync de RSS, downloads e erros gerais.
2. `YYYY-MM-DD-HH-MM-transcricao.log`: Registra exclusivamente eventos de inferência ASR, checkpoints de 5% em 5%, troca de modelos e resumos LLM.
3. `/logs/viewer`: Endpoint HTML com HTMX polling que renderiza os logs em uma janela popup com tema escuro e visualização em tempo real.

---

## 6. Registro de Decisões Arquiteturais (ADRs)

| Decisão | Escolha | Motivo |
| :--- | :--- | :--- |
| **ADR-001** | Zero download automático de áudio | Feeds de podcasts acumulam dezenas de GBs de dados. Baixar apenas metadados protege a banda e o disco do usuário. |
| **ADR-002** | Exclusão do MP3 pós-transcrição | Podcasts são efêmeros após transcritos. Manter apenas o `.txt` e `.meta.json` reduz o consumo de disco em mais de 98%. O botão "Reprocessar Tudo" permite baixar novamente se necessário. |
| **ADR-003** | HTMX + Jinja2 em vez de SPA (React/Vue) | Elimina a necessidade de ambiente Node.js, `npm`, bundlers (Vite/Webpack) e complexidade de autenticação por tokens, mantendo a aplicação 100% Python e rápida. |
| **ADR-004** | SQLite WAL com timeout de 30s | Dispensou a instalação de um servidor pesado de banco de dados (como PostgreSQL), preservando portabilidade máxima sem riscos de bloqueio (`sqlite3.OperationalError: database is locked`). |
| **ADR-005** | PyAV para normalização de áudio | O usuário não precisa rodar `apt-get install ffmpeg` nem depender de codecs globais da distribuição Linux. O PyAV empacota o libav em C dentro do wheel Python. |
