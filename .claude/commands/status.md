---
description: Resume o estado atual do projeto, checkpoints de handoff e próximo passo elegível (somente leitura)
argument-hint: "[foco opcional]"
---

Leia `PROGRESS.md` (seção `Checkpoint de Handoff Ativo`, tabela de `Passos` e as últimas 3 entradas do `Log de handoff`) e `PLAN.md`.
Rode `git status --short` e `git log --oneline -5` (se houver commits).

Responda em pt-BR, de forma concisa:
1. **Estado do Repositório:** branch atual, working tree (limpo ou arquivos modificados).
2. **Checkpoint de Handoff Ativo:** se há algum passo `em andamento` interrompido por outro agente, quem parou e o que falta fazer.
3. **Progresso Geral:** quantos passos estão `concluído` por fase.
4. **Próximo Passo Elegível:** qual passo (`F<x.y>`) deve ser executado agora segundo o protocolo do `AGENTS.md`.

Não altere nenhum arquivo.
Foco opcional: $ARGUMENTS

