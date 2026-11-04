---
description: Prepara o handoff imediato e transparente para o Gemini CLI salvando o checkpoint completo em PROGRESS.md
argument-hint: "[observação opcional para o próximo agente]"
---

Siga a seção 3.3 ("Quando o usuário pedir Handoff") de `AGENTS.md`:

1. Verifique `git status --short` e `git diff --stat`.
2. Se já houver `.venv` configurado no WSL `Ubuntu-26.04`, rode um diagnóstico rápido (`pytest -q` e `ruff check .`) no WSL para registrar o estado exato dos testes.
3. Atualize a seção `## Checkpoint de Handoff Ativo` em `PROGRESS.md` com:
   - Passo em andamento (ou próximo passo se estiver entre passos);
   - Agente de origem: `Claude Code`;
   - Arquivos modificados/criados até o momento;
   - Sub-tarefas já concluídas e sub-tarefas pendentes para fechar o passo;
   - Resultado atual dos testes no WSL `Ubuntu-26.04`;
   - Instrução direta da primeira ação que o próximo agente deve executar.
4. Adicione uma entrada no fim de `## Log de handoff` em `PROGRESS.md` registrando a passagem de bastão.
5. Confirme ao usuário em pt-BR que o handoff está pronto e que basta abrir o **Gemini CLI** e digitar `/next` (ou pedir para continuar).

Observação adicional do usuário: $ARGUMENTS

