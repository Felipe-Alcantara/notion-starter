# notion-starter

Biblioteca Python para operar a **API oficial do Notion** com segurança e resiliência. É o núcleo do ecossistema de automações do Notion — os demais módulos ([notion-tasks-cli](https://github.com/Felipe-Alcantara/notion-tasks-cli), [notion-workspace-app](https://github.com/Felipe-Alcantara/notion-workspace-app)) constroem em cima dela.

> Parte do ecossistema [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion).

## O que ela oferece

- **`NotionClient`** — cliente HTTP resiliente (retries, rate limit, erros tipados)
- **Schema** — leitura e comparação de schemas de databases (`comparar_schema`)
- **Tarefas** — modelo `Tarefa`/`TaskList` para criar, editar, mover e concluir tarefas
- **Conteúdo** — leitura e escrita de blocos de páginas
- **Inventário** — varredura do workspace (páginas, databases, árvore)
- **Utilidades** — saneamento de texto/JSON (surrogates inválidos), logging, properties e readers

## Instalação

```bash
pip install git+https://github.com/Felipe-Alcantara/notion-starter.git
```

Ou, para desenvolvimento:

```bash
git clone https://github.com/Felipe-Alcantara/notion-starter.git
cd notion-starter
pip install -e ".[dev]"
```

## Uso rápido

```python
from notion_starter import NotionClient

client = NotionClient()  # lê NOTION_TOKEN do ambiente
```

Veja a pasta [`examples/`](examples/) para scripts completos: listar páginas, exportar linhas, sincronizar CSV, gerar árvore HTML do workspace, gerenciar tarefas e mais.

## Configuração

| Variável | Descrição |
| --- | --- |
| `NOTION_TOKEN` | Token de integração interna do Notion (obrigatório) |
| `NOTION_DATABASE_ID` | Database padrão de tarefas (opcional) |

## Testes

```bash
pytest
```

## Licença

MIT
