# 🧱 notion-starter

<div align="center">

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Requests](https://img.shields.io/badge/Requests-2.25%2B-20232A?style=for-the-badge&logo=python&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/notion-starter?style=for-the-badge&label=PyPI)](https://pypi.org/project/notion-starter/)
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
  tipados; inclui `obter_pagina` e `atualizar_pagina` para propriedades,
  `obter_bloco`/`restaurar_bloco` para um bloco e `ler_itens_de_propriedade`
  para relações com mais de 25 páginas. A regra de retry (`deve_retentar`) segue
  a documentação: 429 bloqueado e 503 de escrita não se repetem, e uma escrita
  que o Notion salvou apesar do 503 vira `NotionEscritaSalvaError` com os IDs
  criados. `anexar_blocos` aceita `apos_bloco_id` ou `no_inicio`.
- **Schema** — leitura e comparação de schemas de databases com
  `comparar_schema`.
- **Tarefas** — modelos `Tarefa` e `TaskList` para criar, editar, mover e concluir
  tarefas; na criação, a coluna de título é descoberta pelo schema para também
  aceitar databases genéricos.
- **Conteúdo** — leitura e escrita de blocos, incluindo conversão Markdown ↔ blocos
  (listas recuadas viram `children` e voltam recuadas na leitura; o código de um
  bloco `code` volta com o recuo da primeira linha, como foi gravado). Na
  escrita, `_` colado a palavra (`snake_case`), marcador entre espaços
  (`2 * 3`), código inline e `<placeholders>` ficam como texto; só tags de
  elementos HTML são removidas. Escritas
  destrutivas nunca apagam antes de o conteúdo novo estar gravado:
  - `escrever_conteudo` valida os limites da API antes de tocar na página,
    anexa em lotes (100 blocos, 1000 elementos, 500 KB) e só então apaga o
    corpo antigo; aceita `apos_bloco_id`/`inicio` e devolve os IDs criados;
  - `limpar_conteudo` só apaga o que o Markdown recria (`TIPOS_RECRIAVEIS`) e
    preserva, com o motivo, o resto — inclusive blocos que **contêm** algo não
    recriável; `restaurar_blocos` desfaz pelos IDs;
  - `reordenacao.reordenar_bloco` cria a cópia antes de apagar o original,
    recusa tipos fora da lista branca, blocos com filhos e subpáginas;
  - `editar_bloco` recusa Markdown de vários blocos e, com `conferir_atual`,
    mantém o tipo e recusa perder menção/cor/sublinhado; `trocar_trecho` troca
    só um trecho preservando a formatação;
  - `ler_bloco`, `listar_blocos(metadados=True, recursivo=True, contendo=...)`
    e `apagar_bloco_verificado` (que recusa subpágina/database sem pedido
    explícito).
- **IDs** — `utils.normalizar_id` aceita UUID com ou sem hífens e links do
  Notion (ignora `?v=`, usa `?p=` e, quando pedido, a âncora `#bloco`).
- **Mover páginas de verdade** — `NotionClient.mover_pagina` usa
  `POST /pages/{id}/move` (o `PATCH` com `parent` é ignorado pelo Notion),
  aceita destino página, database (resolve o único data source) ou data source,
  e relê a página para confirmar o pai (`MovimentoNaoAplicadoError` se não
  mudou). `services.movimentacao.prever_movimento` diz antes quais colunas o
  Notion vai criar no database de destino e quais valores vão se perder;
  `services.movimentacao.mover_pagina` recusa perda sem `aceitar_perdas=True`.
- **Relações** — `services.relacoes.relacionar` liga os dois sentidos
  conferindo a outra ponta, lê a lista inteira acima de 25 páginas e recusa
  passar de 100.
- **Ingestão de planilhas** — `FontePlanilha(chave="Coluna")` casa cada linha
  pelo registro, não pela posição; sem chave, o título é conferido antes de
  atualizar e divergências vão para `conflitos`. `ingerir(simular=True)` não grava.
- **Propriedades** — builders `properties.*` para `title`, `rich_text`, `select`,
  `status`, `number`, `date`, `relation` e outros tipos; textos acima de 2.000
  unidades UTF-16 são fatiados automaticamente.
- **Inventário** — varredura de páginas, databases e árvore do workspace.
- **Classificação em lote** — `notion_starter.services.classificacao` calcula a
  distribuição de uma regra sobre linhas já buscadas, lista as linhas sem
  classificação e só escreve quando o chamador pede explicitamente.
- **Relatórios DOCX** — `notion_starter.services.relatorios_docx` exporta um arquivo
  por data, combinando propriedades e corpo sem arquivos intermediários.
- **Utilidades** — saneamento de texto/JSON, `fatiar_utf16`, logging e readers.

Exemplo de fluxo: `Markdown` → blocos tipados da API do Notion → página atualizada.

---

## 🎯 Como Usar

### Classificação em lote com dry-run

As linhas são buscadas pelo chamador para que o relatório possa ser conferido
antes da escrita. O padrão é um *dry-run*; a aplicação pode ocorrer depois, e o
valor é tratado como `select` por padrão:

```python
from notion_starter.services.classificacao import (
    aplicar_classificacoes,
    classificar_em_lote,
)

relatorio = classificar_em_lote(linhas, regra_de_classificacao)
print(relatorio.distribuicao)
print(relatorio.ids_sem_classificacao)

aplicar_classificacoes(relatorio, cliente=cliente, coluna="Tipo")
```

Para outro tipo de coluna, passe um `montar_propriedade`, como
`properties.status`. Linhas sem classificação nunca são alteradas.

### Instalação

```bash
# Instalação pública da biblioteca
python -m pip install "notion-starter>=0.4.0,<0.5.0"
```

O release `0.4.1` é publicado no [PyPI](https://pypi.org/project/notion-starter/)
como wheel e sdist; ele corrige o conversor Markdown da `0.4.0`, com as mesmas
APIs. Ele não depende de checkout Git e não instala Django, React
ou a CLI. Para operar o produto completo, use
[`notion-automacoes[app]`](https://pypi.org/project/notion-automacoes/).

Para desenvolvimento, clone o repositório e use `python -m pip install -e ".[dev]"`.

Para desenvolvimento:

```bash
# Clone e instale com as dependências de desenvolvimento
git clone https://github.com/Felipe-Alcantara/notion-starter.git
cd notion-starter
python -m pip install -e ".[dev]"
```

### Uso rápido

```python
from notion_starter import NotionClient

client = NotionClient()  # lê NOTION_TOKEN do ambiente
```

### Escrever e editar conteúdo sem perder o que já existe

```python
from notion_starter.services import conteudo

# Substitui o corpo recriável: valida, escreve o novo e só então apaga o antigo.
resultado = conteudo.escrever_conteudo(page_id, "# Título\n\n- item", substituir=True,
                                       cliente=client)
print(resultado.criados, resultado.limpeza.apagados_ids, resultado.limpeza.motivos)

# Troca só um trecho, preservando menções, cor e sublinhado do bloco.
conteudo.trocar_trecho(bloco_id, "[20:12]", "[21:40]", cliente=client)

# Desfaz uma limpeza pelos IDs (os blocos voltam no fim da página).
conteudo.restaurar_blocos([bid for bid, _ in resultado.limpeza.apagados_ids], cliente=client)
```

Todas as recusas desses fluxos acontecem **antes** de qualquer escrita e
derivam de `NotionSyncError` (as de entrada inválida também de `ValueError`).

A pasta [`examples/`](examples/) contém scripts completos para listar páginas,
exportar linhas, sincronizar CSV, gerar a árvore HTML do workspace, gerenciar
tarefas e publicar relatórios diários a partir do histórico de um repositório
git ([`relatorios_do_git.py`](examples/relatorios_do_git.py), com `--simular`
para conferir antes de escrever).

---

## ⚙️ Configuração

| Variável | Descrição |
| --- | --- |
| `NOTION_TOKEN` | Token de integração interna do Notion (obrigatório) |
| `NOTION_DATABASE_ID` | Database padrão de tarefas (opcional) |
| `NOTION_AUTOMACOES_BACKUP_DIR` | Pasta dos backups em JSON do `reordenar_bloco` (opcional). Sem ela: `${XDG_STATE_HOME:-~/.local/state}/notion-automacoes/backups` ou `%LOCALAPPDATA%\notion-automacoes\backups` — nunca o diretório corrente |

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

**Felipe Alcantara**

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
