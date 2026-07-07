# notion-starter

Biblioteca Python para operar a **API oficial do Notion** com segurança e resiliência. É o núcleo do ecossistema de automações do Notion — os demais módulos ([notion-tasks-cli](https://github.com/Felipe-Alcantara/notion-tasks-cli), [notion-workspace-app](https://github.com/Felipe-Alcantara/notion-workspace-app)) constroem em cima dela.

Além do cliente base, este repo concentra a camada compartilhada entre CLI e app:
adaptadores GitHub/OpenRouter e `notion_starter.services` (tarefas, conteúdo,
clonagem, ingestão, inventário GitHub, exportação DOCX de relatórios e IA). As
bordas e configuração de ambiente continuam nos consumidores.

> Parte do ecossistema [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion).

## O que ela oferece

- **`NotionClient`** — cliente HTTP resiliente (retries, rate limit, erros tipados); inclui `obter_pagina` e `atualizar_pagina` para ler e editar propriedades de uma página
- **Schema** — leitura e comparação de schemas de databases (`comparar_schema`)
- **Tarefas** — modelo `Tarefa`/`TaskList` para criar, editar, mover e concluir tarefas
- **Conteúdo** — leitura e escrita de blocos de páginas
- **Propriedades** — builders `properties.*` (title, rich_text, select, status, number, date, relation…); `title`/`rich_text` fatiam texto acima de 2000 unidades UTF-16 automaticamente
- **Inventário** — varredura do workspace (páginas, databases, árvore)
- **Relatórios DOCX** — `notion_starter.services.relatorios_docx` exporta relatórios diários do Notion para `.docx`, um arquivo por data, juntando propriedades e corpo sem arquivos intermediários
- **Utilidades** — saneamento de texto/JSON (surrogates inválidos), `fatiar_utf16`, logging e readers

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
