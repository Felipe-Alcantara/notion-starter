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

- Gate: `ruff check .` + `python -m pytest` (183 testes em 2026-07-08, sem rede).
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

---

Ideias abertas à contribuição: cobertura de mais tipos de propriedade do Notion,
mais tipos de bloco no conversor Markdown, escrita de linhas em data sources.
