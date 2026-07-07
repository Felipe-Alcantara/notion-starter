# AGENTS.md — notion-starter

Biblioteca Python **base** do ecossistema [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion) — o hub tem o roteamento completo entre módulos; leia-o se a tarefa envolver o CLI ou o app.

## O que vive aqui

| Arquivo | Responsabilidade |
| --- | --- |
| `src/notion_starter/client.py` | Cliente HTTP resiliente (retries por semântica, rate limit, erros tipados); `obter_pagina`/`atualizar_pagina` leem e editam propriedades |
| `src/notion_starter/schema.py` | Leitura/comparação de schema de databases |
| `src/notion_starter/tasks.py` | `Tarefa`, `TaskList`, `CamposTarefa` |
| `src/notion_starter/content.py` + `properties.py` + `readers.py` | Conversão Markdown ↔ blocos (lógica pura); `properties.title`/`rich_text` fatiam texto >2000 (via `utils.fatiar_utf16`) |
| `src/notion_starter/inventory.py` | Mapeamento do workspace (lógica pura, sem rede) |
| `src/notion_starter/github.py`, `openrouter.py` | Adaptadores externos compartilhados por CLI e app |
| `src/notion_starter/services/` | Casos de uso compartilhados entre CLI e app; defaults de ambiente continuam nos consumidores via `integrations.notion` |
| `src/notion_starter/utils.py` | Saneamento de texto/JSON (surrogates inválidos); `fatiar_utf16` (fatia por unidades UTF-16, teto em `constants.MAX_RICH_TEXT`) |
| `examples/` | Scripts de uso direto da lib |

## Regras

- Regra de negócio compartilhada entre CLI e app pode viver em `notion_starter.services`.
  Bordas e configuração de ambiente continuam fora daqui (`cli/`, `api/`, `mcp_server`,
  `integrations.notion` dos consumidores).
- Só o `NotionClient` fala com a API do Notion; módulos de lógica são puros.
- Código e mensagens em português; exceções derivam de `NotionSyncError`; Conventional Commits.
- **Mudança de API pública quebra dois repos consumidores** — mantenha compatibilidade ou avise nos dois.

## Testar

```bash
python -m pytest        # não precisa instalar; tests/conftest.py adiciona src/ ao path
```
