# pod2bullets 🎙️

Cliente de podcasts e transcritor local com modelos de inteligência artificial open-source estado da arte (SOTA).

Desenvolvido para rodar no **WSL (`Ubuntu-26.04`)** aproveitando aceleração por GPU NVIDIA (CUDA) com fallback automático para CPU.

---

## 🌟 Principais Recursos

1. **Organização de Subscrições em Listas:** crie categorias (ex.: *Tecnologia*, *Notícias*, *História*), assine via URL RSS/Atom e importe/exporte arquivos **OPML**.
2. **Zero Download Automático de Áudio:** sincronizar feeds atualiza **apenas os metadados** (XML) no banco SQLite. O áudio do podcast **só é baixado quando você clica explicitamente para baixar**.
3. **Transcrição em Background pós-Download:** ao baixar o áudio sob demanda, o worker de background transcreve automaticamente para **texto puro (`.txt`)**.
4. **Leitura na Web e Download do `.txt`:** leia confortavelmente a transcrição no navegador com botão para copiar texto ou faça download direto do arquivo `.txt`.
5. **Modelos SOTA Open-Source Locais:**
   - **`whisper-large-v3-turbo`** (`faster-whisper` / CTranslate2)
   - **`parakeet-tdt-0.6b-v3`** (`onnx-asr` / ONNX Runtime)
6. **Modelos Facilmente Trocáveis:** mantenha mais de um modelo em disco (`data/models/`), alterne o modelo padrão na interface e re-transcreva episódios já baixados sem precisar baixar o áudio novamente.
7. **Decodificação Universal de Áudio:** usa `PyAV` para decodificar `.mp3`, `.m4a`, `.ogg`, `.opus`, `.wav` para 16 kHz mono sem depender de `ffmpeg` instalado no sistema operacional.

---

## 🚀 Instalação e Execução no WSL Ubuntu 26.04

### 1. Provisionar o ambiente virtual

No WSL `Ubuntu-26.04` (ou a partir do Windows via PowerShell):

```bash
cd /mnt/c/gits/pod2bullets
chmod +x scripts/setup_wsl.sh
./scripts/setup_wsl.sh
```

### 2. Ativar o ambiente

```bash
source .venv/bin/activate
```

### 3. Iniciar o servidor Web

```bash
pod2bullets serve
```

Por padrão, o servidor sobe na porta **`2121`**:
Abra no navegador em **http://localhost:2121** (ou `http://127.0.0.1:2121`).

> Se desejar customizar o host ou porta:
> ```bash
> pod2bullets serve --host 0.0.0.0 --port 2121
> ```

### 4. (Opcional) Baixar os modelos localmente

Para pré-carregar os pesos dos modelos em `data/models/`:

```bash
python scripts/download_models.py --model all
```

Ou listar os modelos via CLI:

```bash
pod2bullets models list
```

---

## 🧪 Testes Automatizados

Para rodar a suíte completa de testes no WSL `Ubuntu-26.04`:

```bash
pytest -v
ruff check . && ruff format --check .
```
