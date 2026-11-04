# AGENTS.md — Protocolo de Cooperação e Handoff Transparente (Claude Code & Gemini CLI)

Este repositório (`pod2bullets`) é desenvolvido em conjunto por **Claude Code** e **Gemini CLI** (e outros agentes compatíveis).
Qualquer agente deve conseguir assumir **automaticamente e transparentemente** do ponto exato onde o anterior parou — inclusive no meio de uma fase ou passo — sem que o usuário precise repetir o contexto.

> **Regra de ouro:** Este arquivo (`AGENTS.md`) é a **fonte única de instruções e convenções**.
> `CLAUDE.md` e `GEMINI.md` apenas importam este arquivo. Nunca duplique regras em arquivos específicos de um agente; atualize sempre aqui.

---

## 1. Arquivos de Coordenação

| Arquivo | Papel | Quem edita |
|---------|-------|------------|
| [PLAN.md](PLAN.md) | Arquitetura, requisitos, estrutura de pastas, modelos ASR e fases/passos (`F0.1`..`F6.2`) com critérios de aceite | Apenas quando o usuário pedir alteração de escopo ou ao registrar decisão arquitetural na seção de decisões |
| [PROGRESS.md](PROGRESS.md) | Tabela de status dos passos + **Checkpoint de Handoff Ativo** + **Log de Handoff** | **Todo agente**, ao iniciar, pausar/fazer handoff ou concluir um passo |
| [AGENTS.md](AGENTS.md) | Este protocolo e regras de ambiente/código | Apenas com pedido explícito do usuário |
| `.claude/` e `.gemini/` | Configurações e slash commands espelhados (`/status`, `/next`, `/handoff`, `/verify`) | Manter sempre sincronizados entre os dois agentes |

---

## 2. Ambiente de Execução Obrigatório: WSL Ubuntu 26.04

Todo o código Python, gerenciamento de ambiente virtual (`.venv`), downloads de modelos, servidor web e **todos os testes (`pytest`) e linters (`ruff`)** DEVEM rodar dentro do **WSL (`Ubuntu-26.04`)**:

- **Caminho no Windows:** `C:\gits\pod2bullets`
- **Caminho no WSL (`Ubuntu-26.04`):** `/mnt/c/gits/pod2bullets`
- **Python no WSL:** Python 3.14 (`/usr/bin/python3` na distro `Ubuntu-26.04`), com `.venv` Linux em `/mnt/c/gits/pod2bullets/.venv`
- **GPU disponível no WSL:** NVIDIA GeForce RTX 2060 SUPER (8 GB VRAM, CUDA 12.9 via `/usr/lib/wsl/lib/nvidia-smi`), com fallback automático para CPU (`int8`)

### Como executar comandos dependendo de onde o agente está rodando

1. **Se o agente já estiver rodando dentro do shell Linux do WSL (`Ubuntu-26.04`):**
   ```bash
   cd /mnt/c/gits/pod2bullets
   source .venv/bin/activate
   pytest
   ruff check . && ruff format --check .
   ```
2. **Se o agente estiver rodando no Windows (PowerShell / CMD):**
   Sempre prefixe comandos de execução/teste com `wsl -d Ubuntu-26.04 -- bash -lc`:
   ```powershell
   wsl -d Ubuntu-26.04 -- bash -lc "cd /mnt/c/gits/pod2bullets && source .venv/bin/activate && pytest"
   wsl -d Ubuntu-26.04 -- bash -lc "cd /mnt/c/gits/pod2bullets && source .venv/bin/activate && ruff check . && ruff format --check ."
   ```
   *(Nunca crie nem use `.venv` do Windows em `.venv`, para não sobrescrever os binários Linux do WSL).*

---

## 3. Protocolo de Handoff Automático e Transparente

O usuário pode alternar entre **Claude Code** e **Gemini CLI** a qualquer momento.

### 3.1. Ao iniciar sessão ou receber pedido para continuar / assumir
Sempre que o usuário iniciar uma tarefa ou disser algo como *"continue"*, *"próximo passo"*, *"assuma de onde o Claude/Gemini parou"*, ou usar `/next`:

1. **Inspecione o estado sem perguntar ao usuário:**
   - Leia [PROGRESS.md](PROGRESS.md) (especialmente a seção `## Checkpoint de Handoff Ativo` e a última entrada de `## Log de handoff`).
   - Rode `git status --short` e `git diff --stat`.
2. **Determine automaticamente o ponto de retomada:**
   - **Caso A — Há um `Checkpoint de Handoff Ativo` (passo `em andamento` deixado pelo outro agente):**
     Anuncie em 1–2 frases: *"Assumindo o passo `F<x.y>` iniciado por `<Agente Anterior>` a partir do checkpoint..."* e continue exatamente do sub-item pendente descrito no checkpoint.
   - **Caso B — Não há passo interrompido:**
     Selecione o primeiro passo com status `pendente` na tabela de [PROGRESS.md](PROGRESS.md) cujas dependências (`Depende de`) estejam todas `concluído` (ou o passo específico pedido pelo usuário).
3. **Reivindique o passo:**
   - Atualize a linha do passo em [PROGRESS.md](PROGRESS.md) para `em andamento`, preenchendo `Agente` (`Claude Code` ou `Gemini CLI`) e `Data` (`AAAA-MM-DD`).
   - Atualize a seção `## Checkpoint de Handoff Ativo` indicando que este passo está ativo.

### 3.2. Ao concluir um passo
1. **Verifique no WSL (`Ubuntu-26.04`):**
   - `ruff check .` e `ruff format --check .` sem erros;
   - `pytest` (ou `pytest -m "not slow"` + testes do escopo) 100% verde no WSL `Ubuntu-26.04`.
2. **Atualize [PROGRESS.md](PROGRESS.md):**
   - Mude o status do passo na tabela para `concluído`;
   - Limpe a seção `## Checkpoint de Handoff Ativo` (marcando `Nenhum passo interrompido no momento. Próximo passo elegível: F<x.y>`);
   - Adicione uma entrada completa no fim de `## Log de handoff` (seguindo o modelo da seção 4).
3. **Um passo por vez:** a menos que o usuário peça explicitamente para executar uma fase inteira ou múltiplos passos em sequência, conclua e registre cada passo antes de avançar.

### 3.3. Quando o usuário pedir Handoff (troca de agente a qualquer momento)
Se o usuário disser *"passe para o Gemini"*, *"passe para o Claude"*, *"vou trocar de agente"*, *"faça handoff"*, ou executar `/handoff`:

1. **Não deixe estado ambíguo:** garanta que todos os arquivos editados estão salvos em disco.
2. **Rode um diagnóstico rápido no WSL:** `pytest -q` e `git status --short`.
3. **Preencha imediatamente a seção `## Checkpoint de Handoff Ativo` em [PROGRESS.md](PROGRESS.md)** com:
   - Passo atual (`F<x.y>`) e agente que está entregando o bastão;
   - O que já foi feito neste passo (arquivos criados/editados);
   - O que falta fazer para concluir o passo (lista objetiva);
   - Estado atual dos testes no WSL (quais passam, quais falham ou faltam escrever);
   - Comando ou ação exata que o próximo agente deve executar ao abrir.
4. **Adicione também uma nota de handoff parcial no `## Log de handoff`** e responda ao usuário confirmando que o estado está salvo e que basta abrir o outro agente e digitar `/next` ou *"continue"*.

---

## 4. Modelo de Entrada no Log de Handoff (`PROGRESS.md`)

```markdown
### AAAA-MM-DD — F<x.y> (<concluído | handoff parcial>) — <Claude Code | Gemini CLI>
- **Feito:** <resumo objetivo do que foi implementado e arquivos principais>
- **Verificação (WSL Ubuntu-26.04):** <comandos rodados e resultado, ex.: `ruff check .` OK, `pytest` 18 passed>
- **Decisões:** <escolhas técnicas não óbvias e motivo>
- **Atenção próximo agente:** <armadilhas, detalhes de ambiente WSL/GPU, pendências se for handoff parcial>
- **Próximo passo sugerido:** F<x.z>
```

---

## 5. Convenções de Código e Arquitetura

1. **Linguagem e Estilo:**
   - Python ≥ 3.12 (executado em Python 3.14 no WSL `Ubuntu-26.04`).
   - Código, nomes de módulos, classes, funções e variáveis em **inglês** (`snake_case` para funções/módulos, `PascalCase` para classes).
   - Interface web, mensagens de CLI, docstrings explicativas, planos e relatórios em **português (pt-BR)**.
   - Type hints obrigatórios em todas as funções e métodos públicos.
   - Formatação e lint via `ruff` (configurado no `pyproject.toml`, linha máx. 100 chars).
2. **Regras de Negócio Inegociáveis do `pod2bullets`:**
   - **Zero download automático de áudio:** atualizar listas/subscrições baixa apenas o XML RSS/Atom e popula metadados no SQLite. O áudio de um episódio **só** pode ser baixado após ação explícita do usuário para aquele episódio.
   - **Transcrição automática em background pós-download:** terminar o download de um episódio enfileira automaticamente a tarefa de transcrição no worker de backend, gerando texto puro (`.txt`) acessível na Web e para download direto.
   - **Modelos 100% locais, open-source e gratuitos:** nenhuma chamada a APIs pagas ou em nuvem.
   - **Arquitetura de transcrição plugável (`TranscriberEngine` + `ModelRegistry`):** múltiplos modelos podem coexistir instalados em `data/models/`, e o usuário escolhe qual modelo usar (como padrão ou por episódio).
   - **Dois modelos SOTA já incluídos de fábrica:**
     1. `whisper-large-v3-turbo` (`Systran/faster-whisper-large-v3-turbo` via `faster-whisper` / CTranslate2)
     2. `parakeet-tdt-0.6b-v3` (`nemo-parakeet-tdt-0.6b-v3` via `onnx-asr` / ONNX Runtime)
   - **Decodificação de áudio sem depender de `ffmpeg` global:** usar `av` (`PyAV`) para normalizar qualquer formato de áudio de podcast (`.mp3`, `.m4a`, `.ogg`, `.opus`, `.wav`) para PCM 16 kHz mono `float32`, garantindo funcionamento 100% autocontido no `.venv` do WSL.
3. **Testes (`pytest` no WSL `Ubuntu-26.04`):**
   - Toda fase/passo deve vir acompanhada de testes automatizados em `tests/`.
   - Testes unitários e de integração rápida não devem fazer downloads da internet nem exigir download de GBs de modelos (usar fixtures locais sintéticas e `FakeTranscriberEngine` / fixture de áudio curto).
   - Testes que carregam os modelos reais completos (`whisper-large-v3-turbo` e `parakeet-tdt-0.6b-v3`) devem ser marcados com `@pytest.mark.real_models` para poderem rodar tanto isoladamente (`pytest -m real_models`) quanto na suíte completa.

---

## 6. Comandos Slash Compartilhados (Claude Code & Gemini CLI)

Ambos os agentes possuem os mesmos comandos configurados em `.claude/commands/` e `.gemini/commands/`:

- `/status` — Lê `PROGRESS.md` e `git status`, mostrando o passo atual, se há handoff ativo e qual é o próximo passo.
- `/next [ID]` — Assume automaticamente o checkpoint de handoff ativo ou inicia o próximo passo `pendente` do `PLAN.md`.
- `/handoff [nota]` — Salva imediatamente o estado atual no `Checkpoint de Handoff Ativo` do `PROGRESS.md` para troca transparente de agente.
- `/verify [ID]` — Executa `ruff` e `pytest` dentro do WSL `Ubuntu-26.04` e apresenta o relatório de validação.

