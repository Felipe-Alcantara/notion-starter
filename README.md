# 🧱 notion-starter

<div align="center">

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Requests](https://img.shields.io/badge/Requests-2.25%2B-20232A?style=for-the-badge&logo=python&logoColor=white)
![Licença MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-green?style=for-the-badge)

**Biblioteca Python resiliente para operar a API oficial do Notion e compartilhar regras de negócio entre interfaces.**

[📖 Sobre](#-sobre-o-projeto) • [🚀 Funcionalidades](#-funcionalidades) • [🎯 Como usar](#-como-usar) • [✅ Qualidade](#-qualidade)

</div>

---

## 📋 Índice

- [📖 Sobre o Projeto](#-sobre-o-projeto)
- [📁 Estrutura do Projeto](#-estrutura-do-projeto)
- [🚀 Funcionalidades](#-funcionalidades)
- [🎯 Como Usar](#-como-usar)
- [⚙️ Configuração](#-configuração)
- [✅ Qualidade](#-qualidade)
- [📄 Licença](#-licença)
- [👤 Autor](#-autor)
- [🤝 Contribuições](#-contribuições)

---

## 📖 Sobre o Projeto

O `notion-starter` é o núcleo do ecossistema
[Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion).
Ele oferece uma API Python tipada para trabalhar com páginas, databases, tarefas e
conteúdo do Notion com retries, rate limit e erros previsíveis.

Além do cliente base, este repositório concentra a camada compartilhada entre o
[notion-tasks-cli](https://github.com/Felipe-Alcantara/notion-tasks-cli) e o
[notion-workspace-app](https://github.com/Felipe-Alcantara/notion-workspace-app):
adaptadores GitHub/OpenRouter e `notion_starter.services` para tarefas, conteúdo,
clonagem, ingestão, inventário GitHub, exportação DOCX e IA. As bordas e a
configuração de ambiente permanecem nos consumidores.

---

## 📁 Estrutura do Projeto

```text
notion-starter/
│
├── 📁 src/notion_starter/       # Biblioteca pública e módulos de domínio
│   ├── 📁 services/             # Casos de uso compartilhados
│   ├── client.py                # Cliente HTTP resiliente do Notion
│   ├── content.py               # Conversão Markdown ↔ blocos
│   ├── properties.py            # Builders de propriedades e schemas
│   └── tasks.py                 # Tarefa e TaskList
│
├── 📁 examples/                 # Scripts de uso da biblioteca
├── 📁 tests/                    # Suíte automatizada sem rede
├── .github/workflows/ci.yml     # Gate em Python 3.10–3.13
├── pyproject.toml               # Pacote, dependências e ferramentas
├── QUALIDADE.md                 # Contrato de qualidade do módulo
├── README.md                    # Este arquivo
└── LICENSE                      # Licença MIT
```

---

## 🚀 Funcionalidades

- **`NotionClient`** — cliente HTTP resiliente com retries, rate limit e erros
  tipados; inclui `obter_pagina` e `atualizar_pagina` para propriedades.
- **Schema** — leitura e comparação de schemas de databases com
  `comparar_schema`.
- **Tarefas** — modelos `Tarefa` e `TaskList` para criar, editar, mover e concluir
  tarefas.
- **Conteúdo** — leitura e escrita de blocos, incluindo conversão Markdown ↔ blocos.
- **Propriedades** — builders `properties.*` para `title`, `rich_text`, `select`,
  `status`, `number`, `date`, `relation` e outros tipos; textos acima de 2.000
  unidades UTF-16 são fatiados automaticamente.
- **Inventário** — varredura de páginas, databases e árvore do workspace.
- **Relatórios DOCX** — `notion_starter.services.relatorios_docx` exporta um arquivo
  por data, combinando propriedades e corpo sem arquivos intermediários.
- **Utilidades** — saneamento de texto/JSON, `fatiar_utf16`, logging e readers.

Exemplo de fluxo: `Markdown` → blocos tipados da API do Notion → página atualizada.

---

## 🎯 Como Usar

### Instalação

```bash
# Instale diretamente do repositório
pip install git+https://github.com/Felipe-Alcantara/notion-starter.git
```

Para desenvolvimento:

```bash
# Clone e instale com as dependências de desenvolvimento
git clone https://github.com/Felipe-Alcantara/notion-starter.git
cd notion-starter
pip install -e ".[dev]"
```

### Uso rápido

```python
from notion_starter import NotionClient

client = NotionClient()  # lê NOTION_TOKEN do ambiente
```

A pasta [`examples/`](examples/) contém scripts completos para listar páginas,
exportar linhas, sincronizar CSV, gerar a árvore HTML do workspace e gerenciar
tarefas.

---

## ⚙️ Configuração

| Variável | Descrição |
| --- | --- |
| `NOTION_TOKEN` | Token de integração interna do Notion (obrigatório) |
| `NOTION_DATABASE_ID` | Database padrão de tarefas (opcional) |

Use variáveis de ambiente ou um arquivo `.env` local baseado em `.env.example`.
Nunca versione tokens ou IDs reais.

---

## ✅ Qualidade

O gate local combina lint e testes:

```bash
python -m ruff check .
python -m pytest
```

A CI repete o gate em Python 3.10, 3.11, 3.12 e 3.13. Consulte
[`QUALIDADE.md`](QUALIDADE.md) para o critério de pronto e a política de
dependências deste pacote.

---

## 📄 Licença

Este projeto está sob a licença MIT — veja [`LICENSE`](LICENSE).

---

## 👤 Autor

**Felipe Martin**

- GitHub: [@Felipe-Alcantara](https://github.com/Felipe-Alcantara)
- Repositório: [notion-starter](https://github.com/Felipe-Alcantara/notion-starter)

---

## 🤝 Contribuições

Contribuições são bem-vindas. Algumas ideias para quem quiser colaborar:

- ampliar a cobertura de tipos de propriedade do Notion;
- adicionar tipos de bloco ao conversor Markdown;
- expandir a escrita de linhas em data sources;
- melhorar exemplos, testes e documentação.

Leia [`CONTRIBUTING.md`](CONTRIBUTING.md) antes de enviar uma mudança.

---

⭐ Se esta biblioteca foi útil, considere dar uma estrela no
[GitHub](https://github.com/Felipe-Alcantara/notion-starter).
