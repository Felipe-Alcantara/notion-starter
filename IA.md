# 🤖 IA.md — Contexto operacional do notion-starter

> **O que é**: Memória técnica deste repositório para retomada de contexto por IA ou
> por um novo mantenedor, sem reler todo o código. Baseado no template de contexto do
> Felixo System Design.
>
> **Histórico anterior**: este módulo nasceu da separação do monorepo
> [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion)
> em 2026-07-02. Toda a linha do tempo anterior (decisões de arquitetura, bugs e
> validações do core) permanece registrada no `IA.md` do hub — este arquivo cobre a
> vida do módulo a partir da separação.

---

## 📊 ESTADO ATUAL (RESUMO VIVO)

Última atualização: [2026-07-18]

- Fase: biblioteca base estável, consumida pelo CLI e pelo app do ecossistema.
- Qualidade: 235 testes verdes e `ruff` limpo; CI cobre Python 3.10–3.13.
- Documentação: README alinhado ao Felixo System Design e contrato de qualidade
  centralizado em `QUALIDADE.md`.
- Próximos passos abertos: mais tipos de propriedade/bloco e escrita em data
  sources.
- Risco conhecido: consumidores devem fixar suas próprias resoluções de
  dependências quando precisarem de builds reproduzíveis.

---

## 🎯 OBJETIVO DO PROJETO

[2026-07-02] `notion-starter` é a biblioteca Python base do ecossistema: cliente
resiliente para a API do Notion (retry/backoff, cache de schema), helpers de
propriedade e leitura, conversor Markdown ↔ blocos, camada de tarefas (`TaskList`),
inventário do workspace e a camada compartilhada `notion_starter.services`
(clonagem, conteúdo, ingestão, sincronização GitHub, exportação DOCX). É consumida
pelo `notion-tasks-cli` e pelo `notion-workspace-app`.

---

## 📐 DECISÕES DE ARQUITETURA

- [2026-07-02] Fronteiras herdadas do monorepo (registradas no hub): só o
  `NotionClient` fala HTTP com o Notion; `services` orquestra casos de uso sem
  conhecer HTTP de borda; conversões e leituras (`content`, `properties`,
  `readers`, `inventory`) são lógica pura testável sem rede.
- [2026-07-02] Exceções continuam derivando de `NotionSyncError` (compatibilidade).
- [2026-07-08] O repositório **não tem `start_app.py`**: é uma biblioteca importável,
  não um programa. A porta de entrada interativa do ecossistema vive no hub
  (`Automa-es-do-Notion/start_app.py`) e no `notion-workspace-app`. Os exemplos de
  `examples/` são executados diretamente (`python examples/<nome>.py`) e documentados
  no README. Exceção registrada conforme o padrão de qualidade.

---

## 🛠️ STACK & DEPENDÊNCIAS

- Python 3.10+ (CI: 3.10–3.13). Runtime: `requests`, `python-docx` (exportação DOCX),
  `typing_extensions` só em Python < 3.11.
- Dev: `pytest`, `responses` (HTTP mockado), `ruff`.

---

## 🧪 TESTES & GATE

- Gate: `ruff check .` + `python -m pytest` (193 testes em 2026-07-13, sem rede).
- CI: GitHub Actions (`.github/workflows/ci.yml`) com matriz Python 3.10–3.13.

---

## 🧠 LINHA DO TEMPO

- [2026-07-02] ✅ Módulo extraído do monorepo. Recebeu depois a consolidação da
  camada compartilhada: `integrations` (GitHub/OpenRouter) e `services` comuns dos
  consumidores viraram shims apontando para cá.
- [2026-07-08] ✅ Alinhamento ao padrão de qualidade Felixo: adicionados
  `CONTRIBUTING.md`, `IA.md`, `.env.example` e CI GitHub Actions. Decisão registrada:
  sem `start_app.py` por ser biblioteca. Validação: `ruff check .` limpo e 183 testes
  verdes.
- [2026-07-13] ✅ Merge do PR #1 (contribuição externa): `mover_pagina`,
  `mover_database` (re-parent, versão 2025-09-03 por chamada) e `enviar_arquivo`
  (File Upload API) + `properties.arquivo_enviado`. Em seguida, hardening no
  `main`: o passo multipart do upload passou a usar retry/backoff próprio
  (`_enviar_multipart`, espelhando a política do `_request_json` — antes era um
  `requests.post` cru, sem resiliência) e `enviar_arquivo` valida o limite de
  20 MB (`NOTION_UPLOAD_MAX_BYTES`) antes de tocar a API. Motivo: migrações com
  dezenas de uploads quebravam no primeiro 429 do `/send`. Validação:
  `ruff check .` limpo e 193 testes verdes (3 novos: limite, retry em 429 e
  retry em falha de rede).
- [2026-07-13] ✅ Fechadas as melhorias propostas no relatório de 10/07 (5.2):
  `criar_database` estendido (is_inline, icone, descricao, prefixo_id/unique_id),
  `valores_br` (números e datas BR), `FontePlanilha` (.xlsx via extra
  `planilha`, .csv via stdlib) com `ItemColetado.propriedades` tipadas,
  `services/importacao` (import em lote retomável por estado local),
  `properties.schema_propriedade` e `services/anexos.anexar_arquivo` (upload +
  propriedade files preservando anexos). Validação: 230 testes verdes, ruff
  limpo, CI verde.
- [2026-07-18] ✅ Documentação alinhada ao Felixo System Design: README passou a
  ter badges, índice, árvore real, guia de uso e rodapé open source;
  `QUALIDADE.md` centralizou o gate e registrou a exceção motivada de versões
  mínimas para uma biblioteca instalável. Motivo: tornar setup, manutenção e
  critérios de pronto verificáveis sem quebrar a resolução dos consumidores.
  Validação: 235 testes verdes e `ruff` limpo.

- [2026-07-23] ✅ `services/inventario_github.atualizar_repos`/`exportar_repos`
  passam a aceitar um **repositório específico** em `contas` (`owner/repo` ou
  URL completa do repo), além de contas inteiras. Nova função privada
  `_repo_completo_da_entrada` distingue os dois formatos (via `_PADRAO_URL_REPO`
  e checagem de `/` fora de URL de perfil) e `_listar_repos_da_entrada` chama
  `GitHubClient.detalhar_repo` nesse caso, em vez de `listar_repos`. Motivo:
  inventariar um projeto pontual de terceiros (ex.: um repo de outra conta)
  sem trazer o resto dos repositórios dela para a database. Validação: 6 novos
  testes em `notion-tasks-cli/tests/test_services_inventario_github.py`
  (reconhecimento de owner/repo, URL de repo, URL de perfil sem repo, coleta
  sem duplicar quando o mesmo repo aparece via conta e via entrada avulsa);
  235 testes do notion-starter e 132 do notion-tasks-cli seguem verdes, ruff
  limpo em ambos.

- [2026-07-23] ✅ Novo módulo `services/estrutura_projeto.py` com três casos de
  uso para a moldura fixa de projeto do workspace (README + `## Acompanhamento`
  com 4 subpáginas + `## Planejamento e documentação` com 2 databases, ver
  `DESIGN-WORKSPACE-NOTION.md` no hub): `inspecionar_estrutura` (lê
  recursivamente subpáginas/databases de uma página de referência, read-only),
  `clonar_estrutura_projeto` (recria a forma — títulos de subpágina + schema de
  databases via `clonar_database` — em outra página, sem herdar conteúdo) e
  `montar_estrutura_projeto` (aplica o padrão do zero). Também
  `services/conteudo.criar_subpagina`, que expõe `client.criar_subpagina` como
  caso de uso reutilizável (antes só usado internamente pelo README do
  GitHub). Motivo: montar essa estrutura manualmente (como feito para o
  projeto Audiofy) exigiu inspecionar várias páginas de exemplo bloco a bloco,
  sem nenhuma ferramenta reutilizável — o padrão documentado não tinha
  automação correspondente. Validação: 9 novos testes em
  `notion-tasks-cli/tests/test_services_estrutura_projeto.py`; 244 testes do
  notion-starter e 137 do notion-tasks-cli seguem verdes, ruff limpo em ambos.

- [2026-07-23] ✅ `NotionClient.anexar_blocos` ganhou o parâmetro opcional
  `apos_bloco_id`, usando `position: after_block` da API do Notion (confirmado
  na doc oficial, `developers.notion.com/reference/patch-block-children` —
  substitui o antigo `after` no nível raiz, hoje legado) para inserir blocos
  novos depois de um irmão específico, não só no final. Novo
  `services/reordenacao.py` com `reordenar_bloco`: como a API do Notion não
  tem endpoint para mover um bloco existente, a implementação apaga e recria
  na posição pedida — sempre grava um backup em JSON do bloco original antes
  de apagar. **Risco documentado e ativamente bloqueado por padrão**: para
  `child_page`/`child_database`, apagar e recriar gera um **ID novo**,
  quebrando links/backlinks/referências externas salvas para o ID antigo; a
  função levanta `BlocoArriscadoError` nesses tipos a menos que o chamador
  passe `forcar_tipos_arriscados=True` explicitamente. Motivo: precisei
  reordenar um database solto numa página de projeto (Audiofy) e não havia
  ferramenta alguma para isso — o único caminho seria apagar manualmente e
  reimportar dados. Validação: 7 novos testes em
  `tests/test_services_reordenacao.py`, mais os testes existentes de
  `anexar_blocos`; 251 testes do notion-starter e 140 do notion-tasks-cli
  seguem verdes, ruff limpo em ambos.

- [2026-07-23] ✅ Correção: `montar_estrutura_projeto` criava "Próximos passos"
  e "Documentações" com um schema mínimo genérico (título + Observações), que
  não batia com o schema real observado nas páginas de projeto existentes do
  workspace ("Próximos passos": Tarefa/Status/Prioridade/Concluída/
  Observações; "Documentações": Documento/Tipo/Status/Criado em/Atualizado
  em/URL/Observações — com `select` de opções coerentes, não `rich_text`
  solto). `DATABASES_PLANEJAMENTO` virou um dict `título -> schema` em vez de
  uma tupla de títulos. Motivo: ao aplicar a ferramenta na página real do
  projeto Audiofy, os databases criados ficaram visivelmente fora do padrão
  das páginas de referência lidas anteriormente. Validação: teste ajustado
  para checar as colunas específicas de cada database (não mais um schema
  genérico); 251 testes do notion-starter e 140 do notion-tasks-cli seguem
  verdes, ruff limpo.

- [2026-07-23] ✅ Correção crítica em `services/reordenacao.reordenar_bloco`:
  `child_database` foi movido de `_TIPOS_ARRISCADOS` (bloqueável com
  `forcar_tipos_arriscados=True`) para uma nova categoria `_TIPOS_IMPOSSIVEIS`,
  recusada **sempre**, sem flag de escape (`BlocoImpossivelError`, distinta de
  `BlocoArriscadoError`). Motivo: confirmado em produção (workspace real da
  Flávia) que apagar+recriar um `child_database` via `anexar_blocos` **nunca
  funciona** — a API do Notion só cria databases por `POST /databases`, não
  por `PATCH /blocks/.../children`; a implementação anterior prometia essa
  capacidade com a flag de força e, ao ser usada, apagava o database original
  (com linhas) e falhava ao recriá-lo, deixando-o arquivado até restauração
  manual. `child_page` continua suportado com a flag (recriação real funciona,
  só o ID muda). Validação: novo teste
  `test_reordenar_bloco_rejeita_child_database_mesmo_com_forcar`; 252 testes
  do notion-starter e 141 do notion-tasks-cli verdes, ruff limpo.

- [2026-07-24] ✅ Novo `services/schema.garantir_coluna`: adiciona uma coluna a
  um database **já existente**, sem apagar nada. Generaliza o padrão que só
  existia hardcoded em
  `inventario_github.garantir_coluna_hash` (que só cuidava da coluna de hash
  do README) para qualquer nome/tipo de coluna. Usa *data source* quando
  disponível, cai para o endpoint clássico de `database` caso contrário —
  mesma estratégia do original. Motivo: nenhuma ferramenta do ecossistema
  evoluía o schema de um database depois de criado (`criar-database` só
  define na criação; `editar-linha`/`importar-planilha` só escrevem em
  colunas existentes) — faltou ao tentar adicionar uma coluna real (Idioma)
  a um database do workspace da Flávia. TDD: testes escritos e confirmados
  falhando antes da implementação existir, só então o módulo foi criado.
  Validação: 4 novos testes em `test_services_schema.py`; 256 testes do
  notion-starter seguem verdes, ruff limpo.

---

Ideias abertas à contribuição: cobertura de mais tipos de propriedade do Notion,
mais tipos de bloco no conversor Markdown, escrita de linhas em data sources.
