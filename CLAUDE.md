# CLAUDE.md

As instruções, convenções e o protocolo de handoff automático deste repositório são compartilhados com o Gemini CLI e vivem em `AGENTS.md`:

@AGENTS.md

## Inicialização e Handoff Transparente

- Ao iniciar uma sessão ou quando o usuário pedir para continuar/avançar: leia `@PROGRESS.md` (especialmente `## Checkpoint de Handoff Ativo` e a última entrada de `## Log de handoff`) e o passo correspondente em `@PLAN.md`.
- Todos os comandos Python, `pytest` e `ruff` devem ser executados no **WSL (`Ubuntu-26.04`)** conforme a seção 2 de `AGENTS.md`.
- Quando o usuário pedir para passar o trabalho ao Gemini CLI (ou usar `/handoff`), atualize imediatamente o `## Checkpoint de Handoff Ativo` e o `## Log de handoff` em `PROGRESS.md`.

Comandos disponíveis:
- `/status` — resume o estado atual do `PROGRESS.md` e do git.
- `/next [ID]` — retoma o handoff ativo ou executa o próximo passo elegível do `PLAN.md`.
- `/handoff [nota]` — salva checkpoint detalhado em `PROGRESS.md` para o Gemini CLI assumir.
- `/verify [ID]` — roda `ruff` e `pytest` no WSL `Ubuntu-26.04` e valida critérios de aceite.

