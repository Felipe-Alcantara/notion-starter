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

---

Ideias abertas à contribuição: cobertura de mais tipos de propriedade do Notion,
mais tipos de bloco no conversor Markdown, escrita de linhas em data sources.
