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

Última atualização: [2026-09-26]

- Fase: biblioteca base estável, publicada como pacote `notion-starter==0.4.1`
  (correção do conversor Markdown sobre a `0.4.0`) para a distribuição da CLI única.
- Qualidade: 590 testes verdes e `ruff` limpo; CI cobre Python 3.10–3.13.
- Documentação: README alinhado ao Felixo System Design e contrato de qualidade
  centralizado em `QUALIDADE.md`.
- Próximos passos abertos: mais tipos de propriedade/bloco e escrita em data
  sources, como contribuições isoladas.
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
- [2026-07-27] ✅ Relatórios diários a partir do git: `git_historico.py` (módulo
  puro — executa `git` e agrupa commits por dia, sem conhecer Notion nem rede) e
  `services/relatorios_diarios.py` (upsert **por data**: se o dia já tem página,
  o corpo é anexado em vez de duplicar a linha). A separação existe porque o
  histórico serve a outros destinos além do Notion, e o upsert serve a conteúdo
  de qualquer origem, não só git. Decisão: página existente **preserva** suas
  propriedades por padrão (`atualizar_propriedades_existentes=False`) — um mesmo
  dia costuma acumular trabalho de projetos diferentes, e sobrescrever o resumo
  apagaria o registro do outro projeto. Nasceu de um script pontual que publicou
  9 dias de trabalho de um repositório na database de relatórios. TDD: testes
  antes da implementação, e um deles pegou um defeito real — mensagem de commit
  contendo o byte separador fazia o registro ser descartado silenciosamente
  (corrigido limitando as divisões do `split`). Exemplo executável em
  `examples/relatorios_do_git.py`, com `--simular`. Validação: 30 testes novos,
  286 do notion-starter verdes, ruff limpo, e execução real contra um
  repositório de 9 dias.

- [2026-08-13] ✅ `DiaDeTrabalho` ganhou `duracao_minutos` e
  `duracao_por_extenso()` (ex.: `"5h30"`, `"35 min"`, vazio com um único
  commit), e `resumo_markdown()` passou a incluir a duração entre o primeiro
  e o último commit do dia na linha de resumo, além da hora que já existia
  (`"2 commits, das 09:00 às 14:30 (duração: 5h30)."`). Motivo: alguns
  agentes já registravam hora e duração manualmente ao publicar relatórios
  no Notion (ex.: "Commit automático do Fetch All das 08:36") — o padrão foi
  formalizado em `docs/PADRAO-RELATORIOS.md` no hub, e este módulo passou a
  gerar esse dado automaticamente em vez de depender de alguém lembrar.
  Validação: 5 novos testes em `test_git_historico.py`; 295 testes do
  notion-starter verdes, ruff limpo.

---

Ideias abertas à contribuição: cobertura de mais tipos de propriedade do Notion,
mais tipos de bloco no conversor Markdown, escrita de linhas em data sources.

---

## [2026-08-17] Operar Notion às cegas era o gargalo real — três defesas na biblioteca

**Contexto.** Uma sessão longa de trabalho real no workspace (criar 17 tarefas
ricas, reescrever 16 e montar 48 ligações entre elas) expôs o mesmo padrão em
todas as fricções: **a biblioteca não respondia perguntas que antecedem a
escrita**, e o custo aparecia depois, já gravado no Notion.

### 1. `descrever_database` — ler o schema sem chamar a API na mão

`schema.py` só sabia **comparar** um database com um schema esperado. Para
descobrir o nome exato de uma coluna, os valores aceitos por um select ou como
uma relação está configurada, era preciso chamar `/v1/databases/<id>` cru e ler
JSON — passo que se pula com pressa.

Entram `DescricaoDatabase`, `Coluna` e `Relacao` (funções puras, sem rede):
colunas ordenadas com o título primeiro, opções de select/status/multi_select,
`editavel` marcando os tipos que o Notion calcula e recusa em PATCH
(`TIPOS_SOMENTE_LEITURA`), e a configuração de cada relação com `auto_referente`
comparando IDs sem hífen.

### 2. `services/relacoes.py` — o tipo da relação não prevê o comportamento

Hipótese inicial: `single_property` = mão única, então uma ligação simétrica
exige gravar as duas pontas. **Medido no workspace real e a hipótese caiu
parcialmente.** Experimento: duas linhas novas no database `30296e2d…`, coluna
`Subtarefas relacionadas`, reportada como `single_property` pelas versões de API
`2022-06-28` **e** `2025-09-03`. PATCH só na ponta C→D; releitura de D **já
trazia C**. O Notion espelhou sem segunda escrita.

Conclusão registrada: **não dá para deduzir do tipo declarado se o espelho
acontece.** Assumir "espelha" deixa metade da malha faltando; assumir "não
espelha" gasta requisição e pode duplicar. `relacionar()` resolve conferindo —
escreve uma ponta, **relê a outra** e grava só o que faltar. Sai simétrico nos
dois mundos, é idempotente e o retorno diz quais páginas precisaram de escrita.
Relação para outro database e de mão única não tem coluna de volta: escreve só A.

### 3. Reescrita que não custa o que não sabe repor

`limpar_conteudo` apagava **todos** os blocos de topo, e `escrever(substituir=True)`
chamava isso em silêncio. Consequência real: reescrever o texto de uma página
apagava a imagem dela (URL do Notion é assinada e expira — a lixeira não devolve
o arquivo) e, pior, apagava `child_database`, **levando o database inteiro** com
ID novo ao restaurar e todo link salvo quebrado.

Agora `TIPOS_NAO_RECRIAVEIS` (imagem, arquivo, vídeo, PDF, áudio, embed,
bookmark, link_preview, `child_page`, `child_database`, synced_block, table,
column_list) é **preservado por padrão**; apagar exige `incluir_nao_recriaveis=True`.
Os retornos viraram `ResultadoLimpeza`/`ResultadoEscrita`, que implementam
`__int__`/`__eq__` contra `int` — quem usava só a contagem antiga não quebrou.

### 4. `EscritaAbaixoDeDatabaseError` — a regra que virou guarda

A "regra do link" (se o alvo é database, trabalhe nas linhas) existia só em
documentação, e modelos mais fracos a ignoravam: recebiam o link de uma página
que **contém** uma database e escreviam um parágrafo solto abaixo da tabela,
onde não vira linha nem aparece em view nenhuma.

`escrever_conteudo` agora chama `databases_da_pagina()` antes de qualquer escrita
e **recusa** com uma exceção que lista as databases encontradas com ID e traz os
comandos prontos (`linhas` → `conteudo` → `editar-linha`/`escrever <linha_id>`).
A checagem vive no serviço, não na borda, para valer também para MCP e scripts.
`mesmo_com_database=True` libera quando o bloco solto é mesmo a intenção.

**Validação real** (2026-08-17, workspace do usuário): `escrever` na página HOME
`1fc91f95…` foi recusado listando as três databases de dentro; uma database de
teste criada dentro de uma linha sobreviveu a `escrever --substituir`; as quatro
linhas de teste foram arquivadas ao fim. 329 testes verdes, `ruff` limpo.

---

## [2026-08-17] Histórico de vários repositórios, e a varredura que acha o dia esquecido

**Contexto.** `git_historico` já reconstruía o dia de trabalho de **um**
repositório. Mas um dia real quase nunca cabe num só — mexe-se na biblioteca, no
CLI que a consome e no app que a expõe — e o relatório precisa contar isso junto,
senão o mesmo dia vira três narrativas soltas que ninguém cruza depois.

`services/historico_repositorios.py` agrega os históricos e agrupa por data,
produzindo o texto no formato que os relatórios diários já usam: **hora e duração
por projeto**, nunca só a data. Acrescenta arquivos e linhas por commit, que
respondem a "foi ajuste ou reescrita?".

### `descobrir_repositorios` — o motivo de existir

O pedido original era registrar o histórico dos projetos citados numa conversa.
A pergunta por trás dele era outra: *existe algum dia de trabalho que ficou sem
registro?* Listar repositórios à mão só encontra o que já se lembra — e o
esquecido, por definição, não está nessa lista.

Medido na máquina de origem: a lista de memória tinha **15 repositórios**; a
varredura encontrou **47**, e o histórico saltou de 125 para **201 dias** com
commit, de 2024-03-26 a 2026-08-17.

### O corpo diz que é reconstruído

O texto gerado abre avisando que veio do git e que decisões e pendências sem
commit não aparecem ali. Inventar narrativa a partir de mensagem de commit é o
jeito mais fácil de povoar um relatório com ficção plausível; o aviso é o que
impede o leitor de tomar log por relato.

### Decisões de robustez

- Repositório inacessível é **pulado**, não fatal: numa lista de quinze, um
  caminho que mudou não pode custar o histórico dos outros catorze.
- `--shortstat` tem formato irregular (omite a metade que é zero, e merge não
  gera linha). O parser vive numa função pura, testada com os três formatos.
- `relatorios_diarios` voltou a converter o retorno de `escrever_conteudo` para
  inteiro com `int(...)` em vez de ler `.anexados` — converter mantém válido
  qualquer double de teste que devolva só o número.

**Validação:** 354 testes verdes, `ruff` limpo; publicação real de 201 dias no
workspace do usuário (115 páginas criadas, 86 complementadas).

---

## [2026-08-25] `TaskList.criar` descobre o título do database

**Sintoma.** A criação de uma linha em `Relatórios diários` falhava porque o
payload sempre enviava a propriedade `Tarefa`, embora o título real se chamasse
`Relatório`. A API aceitava criação direta com o schema correto; o defeito estava
no modelo compartilhado.

**Decisão.** `TaskList.criar` lê o schema antes do POST, encontra a única coluna
`title` com `descrever_database` e usa seu nome real. Os atalhos do modelo de
tarefas (`Etapa`, `Prazo`, `Esforço`, `Áreas da vida`) só entram quando a coluna
existe com tipo compatível. A assinatura e o retorno `Tarefa` foram preservados;
somente a criação ficou genérica, sem fingir que listar/editar databases
arbitrários também são operações de tarefas.

**Validação.** 355 testes verdes e `ruff` limpo. No workspace real, foram
criadas com sucesso uma linha em `Relatórios diários` (título `Relatório`) e
outra em `Tasks` (título `Tarefa`, com `Etapa`/`Esforço`); ambas foram arquivadas
ao fim.

## [2026-09-04] Pacote base preparado para a distribuição sem clone

O `pyproject.toml` foi alinhado ao contrato de distribuição da CLI única: a
versão candidata do `notion-starter` passou a ser `0.3.0`, com build Hatchling,
wheel e sdist. Nenhum código de domínio foi alterado nesta etapa; o pacote segue
sendo a fonte compartilhada para o CLI e o app, sem depender de uma URL Git nos
consumidores.

**Validação:** `ruff check .` limpo, **355 testes verdes**, `twine check` aprovado
para wheel e sdist e import validado em ambiente limpo. A publicação efetiva no
PyPI não foi executada: nome final, ownership e metadados legais ainda precisam
de confirmação explícita.

## [2026-09-04] Documentação e estado público atualizados

O README, `AGENTS.md`, `CONTRIBUTING.md` e `QUALIDADE.md` agora distinguem o uso
do pacote público do fluxo de desenvolvimento, apontam para o PyPI e registram
`Felipe Alcantara` como titular legal. O resumo vivo deixa de tratar a publicação
como pendência; itens futuros ficam restritos a novas capacidades da biblioteca.
Também foi corrigida a referência de distribuição para indicar que o produto
completo é instalado pela fachada `notion-automacoes[app]`.

## [2026-09-07] Classificação em lote com dry-run virou serviço compartilhado

Três preenchimentos em massa da sessão repetiram o mesmo script: consultar linhas,
classificar, contar a distribuição, revisar e atualizar. O novo módulo
`services/classificacao.py` extrai esse andaime sem assumir como as linhas foram
buscadas. `classificar_em_lote` recebe as linhas e uma regra, devolve
`ResultadoClassificacao` com distribuição, linhas sem classificação e pares
linha/valor; nenhuma escrita ocorre por padrão. A aplicação pode ser explícita na
mesma chamada (`aplicar=True`) ou posterior, por `aplicar_classificacoes`, usando
callback ou `NotionClient` com nome da coluna. O atalho do cliente monta `select`
por padrão e aceita outro builder para `status`, `rich_text` ou demais tipos.

Motivo: o relatório precisa ser revisável antes de tocar centenas de linhas, e a
regra de negócio não deve reimplementar o ciclo fetch → contagem → apply em cada
preenchimento novo.

**Validação:** 364 testes verdes e `ruff check .` limpo; importação pública
confirmada pelo clone editável apontado por `check-dev.py`.

## [2026-09-07] `services/schema.py` ganhou `renomear_coluna`

Faltava um caso irmão de `garantir_coluna`: o Notion cria sozinho a coluna
espelho de toda relação nova com nome genérico (`"Related to <database>
(<coluna>)"`), e não existia nenhuma função pra corrigir isso — só
`atualizar_database`/`atualizar_data_source` crus, chamados na mão fora de
qualquer serviço (foi assim que a coluna espelho de "Bloqueada por" virou
"Bloqueia" na database de Tarefas, direto por script).

`renomear_coluna(database_id, nome_atual, novo_nome, cliente=...)` segue a mesma
estratégia de `garantir_coluna`: resolve o *data source* do database (modelo
novo, `PATCH /data_sources/{id}`, versão `2025-09-03`) quando existe, cai para o
endpoint clássico de database caso contrário. Valida que `nome_atual` existe no
schema e que `novo_nome` não colide com outra coluna antes de gravar — as duas
validações lêem o schema atual (via `get_data_source`/`get_database`) antes do
PATCH, então o erro aparece antes da escrita, não depois.

Exposto na CLI como `notion-tasks renomear-coluna <database_id> <nome_atual>
<novo_nome>`. Testes cobrem os dois caminhos (data source e clássico) e as duas
rejeições, reaproveitando o `ClienteFake` já usado por `garantir_coluna`.

**Validação:** 369 testes verdes e `ruff check .` limpo.

## [2026-09-07] `listar_linhas` ganhou o parâmetro `propriedades`

Por design, `listar_linhas` sempre devolveu só `{"id", "titulo", "url"}` por
linha — documentado assim no próprio docstring. Quem precisava das
propriedades completas de uma database inteira (classificar colunas em massa,
cruzar uma relação contra outra, auditar cobertura) tinha que sair da
ferramenta e chamar `consultar_database`/`obter_pagina` linha a linha direto
pelo client. Bateu nesse teto pelo menos quatro vezes numa única sessão de
backfill de propriedades na database de Tarefas.

`listar_linhas(database_id, propriedades=True)` agora acrescenta, em cada
linha, a chave `"propriedades"` com o dicionário `nome -> valor simples` — o
mesmo formato que `ler_conteudo` já devolve, produzido pelo mesmo leitor
(`notion_starter.readers.extrair_valores`), então quem já lê o resultado de
`conteudo` reconhece o formato sem aprender nada novo. Continua resolvendo
*data sources* como antes; a diferença é só o que cada linha carrega.
`propriedades=False` (padrão) mantém a resposta enxuta de sempre — nenhum
consumidor existente muda de comportamento.

Exposto na CLI como `notion-tasks linhas <database_id> --completo`.

**Validação:** 373 testes verdes (4 novos) e `ruff check .` limpo. Testado ao
vivo contra a database "Áreas da vida" real, com e sem `--completo`.

---

## [2026-09-08] Release 0.3.1 preparado para publicar a API de propriedades

O código de `listar_linhas(database_id, propriedades=True)` já estava no
repositório depois da tag `v0.3.0`, mas o PyPI ainda entregava somente o
artefato `0.3.0`. Como a mudança é retrocompatível e o CLI declara
`notion-starter>=0.3.0,<0.4.0`, a correção é um release patch `0.3.1`, sem
alterar a dependência do consumidor. Foram atualizados o metadado do pacote, a
versão exposta por `notion_starter.__version__` e a documentação pública.

A publicação será feita pela tag `v0.3.1`, usando o workflow `release.yml` e o
Trusted Publishing do PyPI. A confirmação final da publicação e da CI dos
consumidores deve ser registrada na sequência.

---

## [2026-09-08] Publicação do release 0.3.1 confirmada

A tag `v0.3.1` foi publicada no commit `ec03490` e o workflow [Release Python
package #34186364793](https://github.com/Felipe-Alcantara/notion-starter/actions/runs/34186364793)
passou no build, nos seis smokes de Ubuntu, Windows e macOS com Python 3.10 e
3.13, e no job de publicação via Trusted Publishing. O PyPI passou a servir
`notion-starter==0.3.1`.

**Validação de consumo:** uma instalação limpa de
`notion-automacoes==0.3.0` resolveu `notion-starter==0.3.1`, e a assinatura
publicada de `listar_linhas` contém `propriedades`.

**CI do consumidor:** os quatro jobs Python da [CI do CLI
#34166776357](https://github.com/Felipe-Alcantara/notion-tasks-cli/actions/runs/34166776357)
passaram após a publicação. O problema original era exclusivamente a resolução
do starter público anterior à implementação.

---

## [2026-09-25] Auditoria de perda de dados: escrever antes de apagar, lista branca e rastro para desfazer

Uma auditoria da CLI contra o workspace real (numa subpágina-sandbox) achou
vários caminhos em que uma operação **sumia com conteúdo** do usuário. A
correção de biblioteca ficou aqui; a borda da CLI (flags, envelope JSON, os
`except` das exceções novas) é o passo seguinte, no `notion-tasks-cli`.

**O que estava errado (medido):**

- `reordenar_bloco` apagava o original antes de recriar. Todo parágrafo sumia
  (a cópia levava `paragraph.icon: null` e a API respondia 400); tabela, âncora
  de outra página e falha de rede também; blocos com filhos eram recriados sem
  eles; `child_page` "forçado" ia inteiro para a lixeira; e `--inicio` mandava
  o bloco para o **fim** (sem `position` vale o padrão `end`). Os backups JSON
  caíam no diretório corrente e chegaram a ser versionados.
- `escrever --substituir` apagava o corpo e só depois recebia 400 por limite da
  API (rich text > 100 itens, tabela > 100 linhas, lote > 1000 elementos): a
  página ficava vazia, sem IDs para restaurar. A limpeza usava lista negra e só
  olhava o topo: `equation`, `link_to_page`, sumário, e um toggle com database
  ou imagem dentro iam para a lixeira.
- `relacionar` regravava a relação lida de `GET /pages`, que corta em 25:
  ligar a 27ª página apagava a 26ª.
- `importar-planilha` usava a posição da linha como chave: inserir uma linha no
  topo fazia a página da Ana passar a descrever a Aline.
- `editar-bloco` gravava só a primeira de várias linhas e destruía menções,
  sublinhado e cor; um DELETE retentado depois de timeout virava 400 e
  abortava laços; o retry repetia escritas com 503 "Do not repeat the write".

**Decisões:**

- Ordem única nos fluxos destrutivos: validar sem rede → ler uma vez → gravar o
  novo e conferir → só então apagar. Falha no meio desfaz o que foi criado e
  levanta exceção com os IDs (`EscritaParcialError`, `LimpezaIncompletaError`,
  `ReordenacaoIncompletaError`); `restaurar_blocos` desfaz pelos IDs
  (medido: o bloco restaurado volta no **fim** do pai, não na posição antiga).
- Lista branca em vez de lista negra: `TIPOS_RECRIAVEIS` na limpeza e
  `_TIPOS_SEGUROS` + campos graváveis por tipo no reordenar. Toggle e callout
  passam a ser **preservados** ao substituir (o motivo avisa que reescrever o
  texto deles duplica). `TIPOS_NAO_RECRIAVEIS` continua exportado, agora
  documental.
- Compatibilidade antes de proteção onde o app não pode mudar agora:
  `editar_bloco(conferir_atual=True)` e `databases_da_pagina(profundo=True)`
  são opt-in (o MCP do app mantém o comportamento e o custo de antes);
  `listar_blocos` só ganha chaves com `metadados`/`completo`; `excluir_bloco`
  mantém o retorno cru e a conferência mora em `apagar_bloco_verificado`.
  `forcar_tipos_arriscados` do reordenar ficou sem efeito (child_page é sempre
  recusado).
- Retry segue `request-limits`: `deve_retentar` é a regra única (inclusive do
  upload); `NotionHTTPError` ganhou `codigo`/`dados_adicionais` lidos do corpo
  inteiro; jitter proporcional e teto de 30 s.
- `position` (`start`/`after_block`) vale na versão `2022-06-28` fixada (regra
  de mudanças aditivas + medição); com posição, `results` traz também os irmãos
  seguintes — os criados são `results[:len(lote)]`. `arquivar_pagina` passou a
  `in_trash`, aceito na 2022-06-28; a troca global de `NOTION_VERSION` segue
  fora (quebraria query de database, busca por `database` e `parent.database_id`).
- Todas as exceções da biblioteca derivam de `NotionSyncError`, mantendo a
  base antiga (`ValueError`/`RuntimeError`) como segunda.
- `python-docx` só é importado na primeira renderização (a CLI pagava ~100 ms
  de abertura em todo comando).

**Validação:** 559 testes verdes e `ruff check .` limpo; cada teste de bug foi
visto falhando com o código anterior (stash da correção). As suítes do
`notion-tasks-cli` (259) e do `notion-workspace-app` (256, 2 pulados) passam
contra esta versão sem alteração. Conferido na API real, numa subpágina-sandbox
arquivada ao final: reordenar parágrafo com `--apos` e `--inicio`; recusa de
item com filhos; recusa antes de apagar (119 trechos, tabela de 101 linhas);
`apos_bloco_id` com 150 blocos na ordem certa; substituição preservando
`equation` e item com imagem dentro; edição mantendo o tipo; recusa de perda
de formatação; `trocar_trecho` preservando sublinhado, cor, menção de data,
de página e de usuário; DELETE duplo sem erro; limpar + restaurar; leitura de
bloco com pai; `apagar_bloco_verificado` recusando subpágina; `in_trash` em
página. Relação acima de 25 foi validada só com *fake* (montar 26+ linhas
relacionadas no workspace real ficou de fora nesta máquina).

**Para quem continuar:** expor na CLI `escrever --apos/--inicio`, `trocar`,
`ler-bloco`, `restaurar-bloco`,
`blocos --metadados/--completo/--recursivo/--contendo`,
`importar-planilha --chave/--dry-run`, a flag de `apagar-bloco` para
subpágina e os `except` das exceções novas (as que derivam só de
`NotionSyncError` escapariam do tratamento atual). Recriar blocos com filhos no
reordenar (em vez de recusar) e limpar células vazias na reimportação por chave
são melhorias que o projeto ainda poderia receber. Nenhuma versão nova foi
publicada; o release fica para a decisão do mantenedor.

---

## [2026-09-25] Revisão da auditoria: código lido com o recuo e release 0.4.0

Registro gravado em 2026-09-26 às 03:12 (-03), durante a correção dos
bloqueantes apontados pela revisão das mudanças de 2026-09-25.

### Leitura de bloco de código perdia o recuo

**O que estava errado (medido na API real, numa subpágina-sandbox).** Depois de
a CLI passar a mandar o código com o recuo, o `GET /blocks/{id}` confirmou
`"    return valor\n\nfim"` gravado, mas `blocos_para_markdown` devolvia
` ```python\nreturn valor\n\nfim\n``` `: `_texto_de_bloco` fazia `strip()` também
no código. Quem conferia a edição pela saída (`editar-bloco`, `ler-bloco`,
`conteudo`) via outro código, e quem relia a página para reescrevê-la gravava o
código sem o recuo.

**Decisão.** No código (`formatado=False`) só as quebras de linha das pontas
saem, o mesmo corte que `editar_bloco` faz na escrita (`strip("\n")`). O texto
formatado dos outros blocos continua com `strip()`, porque ali espaço nas pontas
não é conteúdo.

**Validação.** Dois testes novos em `tests/test_content.py` (ida e volta com a
primeira linha recuada; YAML com recuo e espaços no fim) falham com o código
anterior e passam agora. Na API real, `ler-bloco` passou a mostrar os quatro
espaços que o `GET` já tinha.

### Release 0.4.0 preparado (a CLI não importava com o starter publicado)

**O que a revisão achou (reproduzido).** Os commits da auditoria de 2026-09-25
(`bd58ee9`…`484263c`) acrescentaram API pública (`EdicaoMultiblocoError`,
`normalizar_id`, `chave_de_id`, `services.backups`, entre outras), mas a versão
continuou `0.3.1`, que é também a versão já publicada no PyPI **sem** essas
APIs. A CLI declara a faixa pelo número e passou a importar esses nomes no topo.
Com o `0.3.1` do `origin/main` (`git archive`) na frente do `sys.path`,
`python -m cli --help` falha com `ImportError: cannot import name
'EdicaoMultiblocoError' from 'notion_starter.exceptions'`: nenhum comando abre.

**Decisão.** Versão `0.4.0` (minor, não patch): além das APIs novas, há mudança
de comportamento (`editar_bloco` recusa várias linhas, as exceções ganharam a
base `NotionSyncError`, `arquivar_pagina` usa `in_trash`). As faixas `<0.4.0`
dos consumidores continuam no `0.3.1` até cada um validar e abrir a faixa. O
teste novo `tests/test_versao.py` amarra `__version__` ao `pyproject.toml`.

**Ordem de publicação (nada foi publicado nesta execução; os commits são
locais).** (1) push deste repositório e tag `v0.4.0`, que o `release.yml` leva
ao PyPI; (2) só então a CLI, que agora exige `notion-starter>=0.4.0,<0.5.0` e
cuja CI fica vermelha até o `0.4.0` existir no PyPI; (3) o
`notion-workspace-app` precisa abrir a própria faixa para `<0.5.0` antes do
próximo release da CLI, senão `notion-automacoes[app]` não resolve (a CLI exige
`>=0.4.0` e o app `<0.4.0`).

**Validação.** `ruff check .` limpo e `python -m pytest` verde (562 testes);
o teste de versão falha se só um dos dois números subir (conferido trocando o
`__version__` de volta para `0.3.1`).

---

## [2026-09-26] Ênfase e HTML do conversor Markdown: o que não é marcação fica como texto

Registro gravado em 2026-09-26 às 12:28 (-03).

**O que estava errado (medido).** Duas perdas de texto na escrita, as duas
vistas em páginas reais escritas pela CLI:

- O parser inline casava qualquer par de marcadores. Por isso
  `FELIXO_UPDATE_PRERELEASE` virava "FELIXO" + itálico "UPDATE" + "PRERELEASE",
  `snake_case_name` perdia os `_`, e `2 * 3 * 4` e `a ** b ** c` perdiam os `*`.
- A limpeza de HTML (`_RE_TAG = <[^>]+>`) rodava antes das crases. Com isso
  `DATABASE_URL=<banco descartável migrado>` e `@<versão>` sumiam até dentro de
  código inline, e o mesmo valia para `a < b e c > d` e autolinks. O
  `html.unescape` ainda decodificava entidade sem `;` (`&copy=1` numa URL virava
  "©=1").

**Decisão: correção mínima.**

- Escrita:
  - um marcador não abre antes de espaço nem fecha depois de espaço;
  - `_` não abre nem fecha colado a letra ou dígito;
  - a vizinhança é a da corrida inteira de marcadores (`***`).
- A regra de pontuação do CommonMark ficou de fora de propósito. Ela deixaria
  sem negrito, na releitura, os trechos formatados colados em pontuação, como
  `Campo **(opcional)**obrigatório` e texto CJK, que a 0.4.0 aceitava.
- Leitura: o espaço da ponta fica fora dos marcadores (`**Nota:** `), que é o
  que a escrita nova relê como negrito.
- HTML: nada entre crases é tocado. Só tags de elementos HTML são removidas;
  `<versão>`, `<id>` e `<nome>` ficam. `<https://...>` vira link, e só
  entidades com `;` são decodificadas.

**Tentativa anterior, descartada.** Uma primeira versão reescreveu o conversor
inteiro (pilha de delimitadores do CommonMark, escape na leitura, DOCX), com
+1228 linhas em `content.py`. Duas rodadas de revisão adversarial acharam 20
problemas cada, entre eles leitura de parágrafo de 0,7 ms para 9,5 s, busca
`contendo` quebrada pelo escape e `RecursionError`. Não convergia, e ela ficou
fora do repositório.

**Validação.**

- `ruff check .` limpo e `python -m pytest` verde (590 testes).
- 28 testes novos em `tests/test_content_marcacao.py`; 16 deles falham na 0.4.0.
- Diferencial automático contra a 0.4.0, com corpus de semente fixa:
  - ida e volta fiel em 2326 de 4000 parágrafos gerados, contra 1684: 663
    melhoras e 21 regressões;
  - escrita igual ao markdown-it 4.2 (CommonMark + tachado) em 3603 de 4000
    textos, contra 3238, sem nenhuma regressão;
  - textos que perdem caracteres visíveis: de 692 para 328;
  - tempo linear, com 0,19 s para uma linha de 15 mil caracteres.

**Limitação conhecida.** As 21 regressões de ida e volta são todas trechos
formatados cujo conteúdo começa ou termina com o próprio marcador (um tachado de
"~", um itálico de "*x"). Sem escape com barra, que a biblioteca não tem, esse
caso não tem Markdown que o releia. A 0.4.0 acertava por acaso, porque aceitava
qualquer par.

### Release 0.4.1

**Decisão.** Patch (`0.4.0` → `0.4.1`): só corrige o conversor, sem API nova
nem mudança de contrato. As faixas `>=0.4.0,<0.5.0` da CLI e do app já aceitam
a versão, então nenhum dos dois precisa de release para receber a correção. A
tag `v0.4.1` leva ao PyPI pelo `release.yml`.

---

## [2026-09-26] Revisão adversarial da 0.4.1: delimitadores do CommonMark e leitura por trechos

Registro gravado em 2026-09-26 às 13:33 (-03), antes da publicação da `0.4.1`.

**O que a revisão achou (3 lentes, cada achado com um cético).** A correção
registrada na entrada anterior tinha dois defeitos confirmados, e um terceiro
foi refutado como bloqueante, mas corrigido mesmo assim.

- **Ênfase aninhada do mesmo caractere.** `*Nota: o **CI** falhou*` deixava
  asteriscos visíveis; a 0.4.0 dava texto limpo. Casos reais:
  - `Trabalho2_MNIST.md:113`;
  - o README do `form-data`;
  - duas leituras da 0.4.0 com negrito em volta de código.
- **Tempo quadrático** numa linha com muitos marcadores sem par: `*a ` repetido
  5000 vezes levava 31 s, contra 0,13 s na 0.4.0; uma lista de globs de 7 KB
  levava 1,15 s. A frase "tempo linear" da entrada anterior valia só para o
  corpus sintético medido lá.
- **Colisão** dos marcadores internos da limpeza de HTML (U+E000/U+E001) com um
  texto que já os tivesse, ou com `&#57344;`: `IndexError`.

**Decisão.** As correções pontuais sugeridas conflitavam entre si. O atalho de
desempenho quebrava `*a *b* c`. Por isso a ênfase passou a ser casada pelo
"process emphasis" do CommonMark (`_casar_delimitadores`):

- a linha vira nós (texto, código, link, imagem e corridas de marcadores);
- cada fechamento procura para trás a abertura mais próxima;
- valem a regra do 3 e o `openers_bottom`, que deixa a busca linear;
- o flanqueamento continua o simplificado, sem a regra de pontuação;
- o link recebe o rótulo já parseado, e o `_aplicar_link`, que marcava pelo
  tamanho do texto, saiu.

Os marcadores do HTML passaram a ser caracteres ausentes da linha. A leitura
passou a juntar vizinhos de mesma formatação (`**ab**` em vez de
`**a****b**`).

**Validação.**

- 603 testes verdes e `ruff` limpo. Os testes novos (aninhada, linhas longas,
  colisão e vizinhos) falham no commit anterior; aquela suíte levava 60 s por
  causa dos casos quadráticos.
- **Corpus real** de 10.128 linhas (hub, repositórios do Felipe e leituras
  reais): 9.997 iguais ao markdown-it, contra 9.834 na 0.4.0 e 9.979 na versão
  anterior, **sem nenhuma linha pior** que nas duas.
- **Sintético** (semente fixa): ida e volta fiel em 3.091 de 4.000 parágrafos
  (1.684 na 0.4.0) e escrita igual ao markdown-it em 3.829 de 4.000 (3.238).
- **Desempenho:** `*a ` x 5000 leva 0,01 s, e uma linha de 15 mil caracteres,
  0,10 s.

**Limitações conhecidas (atualiza a entrada anterior).** 37 dos 4.000
parágrafos sintéticos que a 0.4.0 devolvia igual não voltam iguais:

- 27 são trechos formatados que começam ou terminam com o próprio marcador;
- os demais são trechos de formatações **diferentes** colados sem espaço
  (negrito seguido de itálico).

A escrita difere da 0.4.0 em 26 sequências sintéticas de marcadores com
pontuação (como `*1**(`), em que só a regra de pontuação, deixada de fora de
propósito, mudaria o resultado; nas linhas reais foram zero. Markdown gerado
pelo leitor da 0.4.0 com espaço dentro do marcador (`**Nota: **`) não vira
mais negrito: basta reler a página com a 0.4.1.

---

## [2026-09-26] Segunda revisão adversarial da 0.4.1: pilha de delimitadores, destino de link e comentário HTML

Registro gravado em 2026-09-26 às 14:27 (-03), antes da publicação.

**O que a segunda revisão achou (2 lentes, um cético por achado): 3
problemas confirmados, 1 refutado.**

- **Aberturas somiam depois que a pilha perdia itens.** O `fundo`
  ("openers_bottom") guardava a posição na lista de delimitadores, e os pares
  casados removiam itens abaixo dela. Em `~~**ARQ-01**~~ → **Resolvido**:`
  (`docs/AUDITORIA-2026-08-08.md`, linhas 331 e 334, do Felixo AI Core) o
  negrito de "Resolvido" sumia; a 0.4.0 acertava. O defeito foi confirmado
  pelas duas lentes. Agora o `fundo` guarda o índice do nó.
- **Destino de link entre `<…>`.** Em `[RSA](<https://…_(sistema)>)`
  (sintaxe válida do CommonMark), a conversão de autolink pegava o destino, e a
  URL vazava para o texto. Agora:
  - o autolink não conta logo depois de `](`;
  - o leitor de link aceita `<destino>`;
  - o destino comum aceita parênteses balanceados.
- **Comentário HTML sem fechamento.** A regex `<!--.*?-->`, nova nesta versão,
  ficava quadrática: 5,7 s numa linha de 50 KB, contra 0,66 s na 0.4.0. Foi
  trocada por um laço com `find`.
- **Refutado como bloqueante, corrigido assim mesmo.** Uma linha com todos os
  6.399 caracteres de uso privado do BMP deixava os marcadores internos sem
  opção. A busca agora continua no plano 15.

**Validação.**

- 610 testes verdes e `ruff` limpo. Os 7 testes novos falham no commit
  anterior.
- A referência independente escrita pelo revisor (`ref_casar`, mesmo
  flanqueamento e `fundo` por nó) bate com o código final em 200.000 de
  200.000 entradas aleatórias.
- **Corpus real** de 10.128 linhas: 9.997 iguais ao markdown-it, sem nenhuma
  linha pior que na 0.4.0 ou na versão anterior.
- **Sintético:** ida e volta fiel em 3.102 de 4.000 (1.684 na 0.4.0).
- **Desempenho:** linhas de 50 KB de `*a `, `a* `, `*a* ` e `*_~~` em até
  0,43 s.
- **Consumidores:** `notion-tasks-cli` 333/333 e `notion-workspace-app`
  279/279 com esta versão, os mesmos números da 0.4.0.

---

## [2026-09-27] Mover página de verdade: `POST /pages/{id}/move` e pai conferido

**O que estava errado (medido no workspace real em 2026-09-27).**
`NotionClient.mover_pagina` fazia `PATCH /pages/{id}` com `parent`. O Notion
responde 200 e **ignora** o campo: `parent` e `last_edited_time` relidos
ficaram iguais. A CLI (`mover-pagina`) e o MCP do app reportavam um movimento
que não acontecia. O aviso antigo do docstring ("página que contém databases é
aceita e ignorada") era um caso particular do mesmo defeito.

**Decisão.**

- `mover_pagina(page_id, novo_pai_id, *, tipo_pai="page_id")` manteve a
  assinatura e passou a usar `POST /pages/{id}/move` com
  `Notion-Version: 2025-09-03`. `tipo_pai` aceita também `"data_source_id"`;
  `"database_id"` resolve o **único** data source do database pelo método
  novo `resolver_data_source` (zero ou várias fontes: `FonteDeDadosIndefinidaError`,
  que lista as fontes).
- Depois do pedido a página é relida e o pai comparado (`chave_de_id`); se não
  bater, `MovimentoNaoAplicadoError`. Quando o destino é data source, a
  releitura mostra `{"type": "database_id", ...}` (medido) e é o database dono
  da fonte que se compara. O retorno passou a ser a página relida.
- `services/movimentacao.py` (novo): `prever_movimento` lê a página e o schema
  da fonte de destino e classifica as colunas; `mover_pagina` recusa perda de
  valor sem `aceitar_perdas=True` (`MovimentoComPerdasError`) e aceita
  `dry_run`. Regras, com o que foi medido marcado no `motivo`:
  - coluna ausente no destino → o Notion a **cria** lá (medido: uma
    `multi_select` apareceu com as opções da origem);
  - `select`/`status`/`multi_select` com opção inexistente no destino → valor
    perdido (medido);
  - relação → perdida (medido);
  - mesmo nome com outro tipo, e linha movida para uma página → perda
    (previsão pelo lado seguro, não medida);
  - tipos calculados → listados à parte, recalculados no destino.

**Validação.** `tests/test_client_movimento.py` (7 testes) e
`tests/test_services_movimentacao.py` (8) novos; os dois testes antigos de
`test_client.py` que fixavam o `PATCH` foram reescritos para o endpoint novo e
falham com o cliente anterior. Nada foi testado contra o Notion real nesta
entrega: os fatos acima vêm da medição feita antes, no mesmo dia.

**Contrato.** API pública nova (`resolver_data_source`, `TIPOS_PAI_DE_MOVIMENTO`,
as duas exceções, o serviço) entra no `main` sem mudar a versão do pacote, por
decisão de quem mantém; a CLI só pode exigi-la depois do próximo release.

---

## [2026-09-27] Copiar o corpo de uma página bloco a bloco

**Contexto.** Para preencher modelos e consolidar páginas era preciso copiar um
corpo com tabela, checklist e colunas. Passar por Markdown perde isso. A
implementação de tarefa que funcionou (73 blocos: tabela de 9 linhas, to_do,
quote, headings e listas, conferidos por contagem de tipos) mostrou três
recusas da API, medidas em 2026-09-27:

- a leitura devolve campos opcionais como `null` (`paragraph.icon`) e a escrita
  recusa `null` onde espera objeto;
- `plain_text`/`href` dos itens de *rich text* e campos só-leitura precisam sair;
- o lote de 100 é **atômico**: um bloco recusado derruba todos.

**Decisão.** `services/copia_corpo.py` (novo):

- `copiar_corpo(origem, destino, *, so_se_vazio, mesmo_com_database, dry_run,
  conferir)` grava no fim do destino e devolve `ResultadoCopia`;
- **lista branca** de tipos graváveis (`TIPOS_COPIAVEIS`). Subpágina, database,
  `link_preview`, arquivo hospedado no Notion (o link expira) e tipos
  desconhecidos vão para `ignorados`, com o motivo;
- *rich text* pela conversão que a biblioteca já tinha
  (`content.item_para_requisicao`); menção não regravável vira texto com o link
  e o bloco entra em `degradados`;
- chaves `None` removidas em qualquer profundidade (o `synced_from: null` de um
  bloco sincronizado original é mantido de propósito);
- até dois níveis de `children` por requisição; o que passa disso é anexado
  depois no bloco já criado (relendo os filhos para achar os IDs). Tabela,
  `column_list` e `column` sempre nascem com os filhos; tabela com mais de 100
  linhas recebe o resto depois; coluna sem nenhum filho copiável ganha um
  parágrafo vazio, porque a API recusa coluna vazia;
- lotes por `content.planejar_lotes` (100 blocos, 1000 elementos, 500 KB);
- destino com database recusa como `escrever_conteudo`
  (`EscritaAbaixoDeDatabaseError`), salvo `mesmo_com_database`;
- falha no meio: os blocos de topo criados vão de novo para a lixeira e sobe
  `EscritaParcialError` (o mesmo contrato das outras escritas).

**Validação.** `tests/test_services_copia_corpo.py` (11 testes) com um double
que aplica as recusas medidas (nulo, campo de leitura no *rich text*, mais de
dois níveis, mais de 100 filhos, tabela/colunas sem filhos, lote atômico).
Conferido à parte que o double pega os defeitos: sem a remoção de `null`, o
teste da página medida falha; aceitando cinco níveis numa requisição, o teste de
aninhamento falha. Nada foi escrito no Notion real nesta entrega.

**Limites conhecidos.** A conferência (`conferir=True`) conta os filhos que a
leitura devolve; numa cópia de bloco sincronizado **duplicado** a releitura
mostra o conteúdo do original e a contagem diverge. Um arquivo hospedado no
Notion não é copiado (seria preciso baixar e reenviar pela File Upload API),
uma melhoria aberta a quem quiser contribuir.
