# AGENTS.md — notion-starter

Biblioteca Python **base** do ecossistema [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion) — o hub tem o roteamento completo entre módulos; leia-o se a tarefa envolver o CLI ou o app.

## O que vive aqui

| Arquivo | Responsabilidade |
| --- | --- |
| `src/notion_starter/client.py` | Cliente HTTP resiliente (retries por semântica, rate limit, erros tipados) |
| `src/notion_starter/schema.py` | Leitura/comparação de schema de databases |
| `src/notion_starter/tasks.py` | `Tarefa`, `TaskList`, `CamposTarefa` |
| `src/notion_starter/content.py` + `properties.py` + `readers.py` | Conversão Markdown ↔ blocos (lógica pura) |
| `src/notion_starter/inventory.py` | Mapeamento do workspace (lógica pura, sem rede) |
| `src/notion_starter/utils.py` | Saneamento de texto/JSON (surrogates inválidos) |
| `examples/` | Scripts de uso direto da lib |

## Regras

- **Nenhuma regra de negócio de produto aqui** — isso pertence à camada `services` dos repos consumidores (`notion-tasks-cli`, `notion-workspace-app`).
- Só o `NotionClient` fala com a API do Notion; módulos de lógica são puros.
- Código e mensagens em português; exceções derivam de `NotionSyncError`; Conventional Commits.
- **Mudança de API pública quebra dois repos consumidores** — mantenha compatibilidade ou avise nos dois.

## Testar

```bash
python -m pytest        # não precisa instalar; tests/conftest.py adiciona src/ ao path
```
