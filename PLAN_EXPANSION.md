# PLAN_EXPANSION — Melhorias de Interface, Feeds, Modelos e Progresso

Plano de ação faseado para atender às novas demandas do usuário.

---

## 1. Diagnósticos e Resoluções

### A. "Por que só vieram 100 episódios e não todos?"
- **Causa raiz:** No repositório SQLite (`src/pod2bullets/db/repository.py`), o método `list_episodes` possuía o parâmetro padrão `limit: int = 100`. Como a rota web chamava `repo.list_episodes()` sem passar o limite, apenas os primeiros 100 episódios eram retornados.
- **Solução:** Alterar `limit: Optional[int] = None` por padrão em `list_episodes`, retornando **todos** os episódios cadastrados na listagem principal.

### B. "Por que tem um 'nuvem/download' nos modelos?" e Login HuggingFace
- **Causa raiz:** O seletor no topo apenas lia `is_installed`. Como os pesos de 1.6 GB ainda não haviam sido baixados para a pasta `data/models/`, o sistema indicava `(Nuvem/Download)`.
- **Diagnóstico da API HuggingFace:**
  - `istupakov/parakeet-tdt-0.6b-v3-onnx`: **HTTP 200 (100% público e anônimo)**.
  - `Systran/faster-whisper-large-v3-turbo`: **HTTP 401**. O HuggingFace exige autenticação (token gratuito ou login HF via browser) para fazer snapshot do repositório da Systran.
- **Solução:**
  1. Adicionar na interface web um modal/painel **"Gerenciar Modelos"**:
     - Botão de login ou inserção de token do HuggingFace (com link direto para logar via Google/Browser no HF e obter o User Access Token com 1 clique).
     - Botão explícito **"Baixar para disco local"** com barra de progresso em tempo real (via SSE ou polling).
  2. Quando ambos os modelos estiverem em `data/models/`, a indicação muda automaticamente para `(Instalado Localmente ✅)`.

### C. Ordenação e Arte/Capa dos Episódios
- **Capa:** O feed parser já extrai `<itunes:image>` e `<image>`. Adicionar coluna `image_url` na tabela `episodes` para renderizar a miniatura na lista.
- **Ordenação:** Ordenar por `published_at DESC` com normalização de datas ISO 8601, garantindo que o mais novo fique no topo.

### D. Menu de Podcasts e Importação OPML
- **Menu de Podcasts:** Adicionar na barra lateral um menu com todos os podcasts assinados (com logo/ícone e link para filtrar).
- **Importação OPML:** Adicionar botão e modal de upload de arquivo `.opml`/`.xml` na barra lateral com feedback visual.

### E. Barra de Status para Download e Transcrição
- Apresentar barra de progresso percentual visual (`0% a 100%`) em cada card de episódio durante o download e a transcrição via HTMX polling.

---

## 2. Passos de Execução

- **P1:** `list_episodes` sem limite de 100 + ordenação cronológica decrescente rigorosa (`published_at DESC`).
- **P2:** Capa/arte do episódio: coluna no banco, parser RSS e card na interface web.
- **P3:** Menu de Podcasts na Sidebar com filtro por podcast específico.
- **P4:** Botão e formulário de importação de OPML na interface.
- **P5:** Barra de progresso visual nos cards para download e transcrição.
- **P6:** Gestor de Modelos: suporte a token/login HuggingFace, download acompanhado na Web e confirmação local.
- **P7:** Verificação geral com testes automatizados no WSL Ubuntu 26.04.
