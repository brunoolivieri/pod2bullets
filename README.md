# pod2bullets 🎙️✨

> **O cliente de podcasts inteligente, privado e local.**  
> Gerencie feeds, faça download sob demanda, transcreva episódios com modelos de IA de ponta (**Whisper Large v3 Turbo** e **NVIDIA Parakeet TDT**) 100% no seu computador e gere resumos estruturados com os melhores LLMs do mercado.

Desenvolvido para rodar nativamente no **WSL (`Ubuntu-26.04`)** com aceleração por GPU NVIDIA (CUDA 12) e fallback automático para CPU.

---

## 🌟 Principais Recursos

- 🛡️ **Zero Download Automático de Áudio:** Sincronizar feeds ou importar OPML baixa **exclusivamente os metadados (XML)**. Nenhum áudio é baixado sem o seu clique explícito.
- 🎙️ **Transcrição ASR 100% Local & Privada:** Seus arquivos de áudio nunca saem da sua máquina. O processamento acontece localmente usando:
  - **`whisper-large-v3-turbo`** (via `faster-whisper` / CTranslate2 — SOTA em 99 idiomas, excelente em PT-BR);
  - **`parakeet-tdt-0.6b-v3`** (via `onnx-asr` / ONNX Runtime — ultra-rápido, pontuação e capitalização automáticas);
  - **`whisper-small`** (opção leve para processamento econômico).
- 🤖 **Resumos Inteligentes com Múltiplos LLMs:** Escolha entre **Google Gemini**, **Anthropic Claude**, **OpenAI ChatGPT**, **DeepSeek** ou **Alibaba Qwen** para resumir o texto transcrito com prompts totalmente customizáveis na própria interface web.
- 📑 **Navegador de Resumos (`/summaries`):** Explore todos os resumos gerados, filtre por podcast ou provedor de LLM, compare múltiplos resumos de LLMs diferentes para o mesmo episódio e exporte em `.txt`.
- 💾 **Economia Extrema de Disco:** O arquivo de áudio temporário (`.mp3`/`.m4a`) é apagado automaticamente assim que a transcrição termina, economizando gigabytes de armazenamento. Se quiser o áudio de volta, basta clicar em *"🔄 Reprocessar Tudo"*.
- 📋 **Fila Visual com Cancelamento (`/queue/manage`):** Clique em múltiplos episódios e acompanhe o progresso em tempo real (em marcos de 5% em 5%), com opção de cancelar jobs individuais ou limpar a fila toda.
- 📂 **Gestão de Listas & Importação OPML:** Organize seus podcasts em categorias (*Tecnologia*, *Notícias*, *História*, *Favoritos*) e importe suas assinaturas direto do Pocket Casts, AntennaPod, Apple Podcasts ou Google Podcasts.
- 🖥️ **Log Viewer ao Vivo (`/logs/viewer`):** Acompanhe o terminal em tempo real em uma janela popup separada com tema escuro.
- 🎵 **Decodificação Universal sem FFmpeg Global:** Utiliza a biblioteca `PyAV` embutida para decodificar `.mp3`, `.m4a`, `.aac`, `.opus`, `.ogg` e `.wav` sem precisar instalar nada no sistema operacional.

---

## 🚀 Instalação e Início Rápido no WSL Ubuntu 26.04

O projeto foi construído para operar de maneira rápida e autocontida no **WSL (`Ubuntu-26.04`)**.

### Passo 1: Clonar o Repositório e Provisionar o Ambiente

No terminal do seu WSL `Ubuntu-26.04` (ou PowerShell apontando para o WSL):

```bash
cd /mnt/c/gits/pod2bullets

# Executar o script de provisionamento automático
chmod +x scripts/setup_wsl.sh
./scripts/setup_wsl.sh
```

O script criará o ambiente virtual `.venv` em Linux, instalará todas as dependências (incluindo runtime CUDA 12 para GPU) e validará seu hardware.

### Passo 2: Ativar o Ambiente Virtual

```bash
source .venv/bin/activate
```

### Passo 3: Iniciar o Servidor Web

```bash
pod2bullets serve
```

Por padrão, a interface estará acessível em:
👉 **[http://localhost:2121](http://localhost:2121)** (ou `http://127.0.0.1:2121`)

> Para especificar outro host ou porta:
> ```bash
> pod2bullets serve --host 0.0.0.0 --port 8080
> ```

---

## 📖 Manual de Uso da Interface Web

### 1. Adicionando Podcasts e Listas
- **Criar Listas:** Na barra lateral esquerda, clique em **"+ Nova Lista"** para criar categorias (ex.: *Tecnologia*, *Negócios*).
- **Adicionar Feed:** Clique em **"+ Assinar Feed"** e insira a URL do RSS do podcast.
- **Importar OPML:** Clique em **"📥 Importar OPML"** para carregar todas as suas assinaturas de uma só vez a partir de outros agregadores.
- **Zero Download:** Ao adicionar ou sincronizar feeds, o sistema baixa apenas os títulos e descrições dos episódios. Nenhum áudio é baixado neste momento!

### 2. Baixando e Transcrevendo Episódios
Na listagem de episódios, cada card oferece opções de processamento:
1. **Selecione o Modelo ASR Local:**
   - `whisper-large-v3-turbo` *(Recomendado — melhor precisão)*
   - `parakeet-tdt-0.6b-v3` *(Mais rápido)*
   - `whisper-small` *(Leve)*
   *(Se o modelo não estiver baixado, o sistema faz o download automaticamente na primeira execução).*
2. **Selecione o Modelo de Resumo LLM (Opcional):**
   - Escolha entre *Apenas Transcrever Localmente* ou gerar resumo com *Gemini*, *Claude*, *ChatGPT*, *DeepSeek* ou *Qwen*.
3. **Clique em `⬇️ Baixar e Transcrever`:**
   - O episódio entra na fila com acompanhamento percentual (5% em 5%).
   - Ao finalizar, o `.mp3` é excluído para economizar seu disco e o `.txt` fica pronto para leitura!

### 3. Configurando Chaves de API das LLMs
Acesse a página **🤖 Central de APIs & LLMs** no menu superior:
- Insira as chaves de API dos provedores desejados (**Google Gemini**, **Anthropic Claude**, **OpenAI**, **DeepSeek** ou **Qwen DashScope**).
- As chaves são armazenadas localmente de forma segura no seu banco SQLite (`data/db/pod2bullets.sqlite`).
- **Prompt Customizável:** Edite as instruções de geração do resumo (ex.: tópicos principais, insights acionáveis, conclusões) com salvamento em 1 clique.

### 4. Navegador de Resumos (`/summaries`)
Clique em **📑 Resumos** no menu superior:
- Veja todos os resumos gerados no sistema em formato de cards visuais.
- **Filtro Rápido:** Filtre por podcast ou por provedor LLM.
- **Transparência:** Clique em *"🔍 Ver prompt utilizado"* para conferir exatamente quais instruções geraram o resumo.
- **Ações:** Leia o resumo na íntegra, copie com 1 clique, baixe o arquivo `.txt` ou exclua resumos individuais.

### 5. Reprocessando Episódios
Para episódios já concluídos, você tem total flexibilidade:
- **`✨ Só Texto (LLM)`:** Gera um novo resumo por outra inteligência artificial usando a transcrição local existente, sem precisar baixar o áudio de novo.
- **`🔄 Reprocessar Tudo`:** Baixa o arquivo de áudio novamente caso queira re-transcrever com outro modelo ASR.

### 6. Acompanhamento de Fila e Logs
- **Fila de Execução (`/queue/manage`):** Clique no botão **"📋 Fila & Andamento"** para visualizar a ordem de processamento de múltiplos downloads e transcrições, com opção de cancelamento instantâneo.
- **Log Viewer (`/logs/viewer`):** Clique em **"🖥️ Abrir Log Viewer"** para abrir uma janela dedicada acompanhando os logs do terminal em tempo real.

---

## 💻 Referência de Comandos CLI

O executável de linha de comando `pod2bullets` oferece controle total:

| Comando | Descrição |
| :--- | :--- |
| `pod2bullets serve` | Inicia o servidor Web (padrão porta 2121). |
| `pod2bullets serve --port 8000` | Inicia o servidor em porta customizada. |
| `pod2bullets models list` | Lista todos os modelos ASR locais e status de instalação em disco. |
| `pod2bullets models install <model_id>` | Faz pré-download dos pesos de um modelo para `data/models/`. |
| `pod2bullets lists` | Exibe as listas e categorias de podcasts cadastradas. |
| `pod2bullets feeds list` | Lista todos os feeds RSS assinados no banco de dados. |
| `pod2bullets feeds sync` | Sincroniza todos os feeds RSS (apenas metadados XML). |
| `pod2bullets --help` | Mostra ajuda e opções gerais. |

---

## ⚡ Aceleração por Hardware (NVIDIA CUDA & CPU)

O sistema detecta e pré-carrega automaticamente as bibliotecas de GPU do CUDA 12:
- **Placa Recomendada:** GPUs NVIDIA com pelo menos 6–8 GB de VRAM (ex.: RTX 2060 SUPER, RTX 3060, etc.).
- **VRAM Típica:**
  - `whisper-large-v3-turbo`: ~1.8 GB VRAM (`int8_float16`)
  - `parakeet-tdt-0.6b-v3`: ~1.2 GB VRAM
- **Modo CPU:** Caso não haja GPU NVIDIA disponível, o sistema opera automaticamente em modo CPU com quantização `int8`.

---

## 🧪 Testes Automatizados e Qualidade de Código

Para executar os testes automatizados dentro do WSL `Ubuntu-26.04`:

```bash
# Rodar todos os testes unitários, integração e E2E
pytest -v

# Rodar verificação de lint e formatação com ruff
ruff check . && ruff format --check .
```

---

## 📚 Documentação Adicional

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Documentação técnica completa, diagramas de componentes, fluxo de dados e decisões arquiteturais (ADRs).
- [docs/AI_GUIDE.md](docs/AI_GUIDE.md) — Guia de desenvolvimento e regras de concorrência para agentes autônomos de IA (Gemini CLI / Claude Code).
- [AGENTS.md](AGENTS.md) — Protocolo de cooperação e handoff transparente entre agentes de IA.
- [PROGRESS.md](PROGRESS.md) — Registro histórico de execução de fases e checkpoints.

---

## 📄 Licença

Distribuído sob a licença open-source MIT. Modelos ASR e bibliotecas de terceiros respeitam suas respectivas licenças de código aberto (`faster-whisper`, `ctranslate2`, `onnx-asr`, `PyAV`, `FastAPI`).
