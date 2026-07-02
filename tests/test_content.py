"""Testes da camada de conteúdo: blocos no NotionClient + conversor Markdown."""

from __future__ import annotations

import json

import pytest
import responses

from notion_starter import (
    NotionClient,
    blocos_para_markdown,
    markdown_para_blocos,
)
from notion_starter.constants import NOTION_BASE_URL
from notion_starter.exceptions import NotionConfigurationError

TOKEN = "ntn_test_token"


def criar_client() -> NotionClient:
    return NotionClient(token=TOKEN, max_retries=0)


# -- Conversor Markdown -> blocos ------------------------------------------


def test_markdown_para_blocos_tipos_comuns():
    md = (
        "# Título\n"
        "## Sub\n"
        "Um parágrafo.\n"
        "- item a\n"
        "1. passo um\n"
        "- [ ] pendente\n"
        "- [x] feito\n"
        "> citação\n"
        "---"
    )
    blocos = markdown_para_blocos(md)
    tipos = [b["type"] for b in blocos]
    assert tipos == [
        "heading_1",
        "heading_2",
        "paragraph",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "to_do",
        "quote",
        "divider",
    ]
    assert blocos[5]["to_do"]["checked"] is False
    assert blocos[6]["to_do"]["checked"] is True
    assert blocos[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Título"


def test_markdown_para_blocos_bloco_de_codigo_preserva_linhas():
    md = "```python\nx = 1\ny = 2\n```"
    blocos = markdown_para_blocos(md)
    assert len(blocos) == 1
    assert blocos[0]["type"] == "code"
    assert blocos[0]["code"]["language"] == "python"
    assert blocos[0]["code"]["rich_text"][0]["text"]["content"] == "x = 1\ny = 2"


def test_markdown_para_blocos_normaliza_apelido_de_linguagem():
    # "py" não é aceito pelo Notion; deve virar "python".
    blocos = markdown_para_blocos("```py\nx = 1\n```")
    assert blocos[0]["code"]["language"] == "python"


def test_markdown_para_blocos_linguagem_desconhecida_vira_plain_text():
    # Linguagem fora da lista do Notion (ou cerca sem info) não pode quebrar.
    desconhecida = markdown_para_blocos("```planilha\na,b\n```")
    assert desconhecida[0]["code"]["language"] == "plain text"
    sem_lingua = markdown_para_blocos("```\nsó texto\n```")
    assert sem_lingua[0]["code"]["language"] == "plain text"


def test_markdown_para_blocos_fatia_texto_acima_de_2000_chars():
    # O Notion rejeita um item de rich_text com mais de 2000 caracteres.
    grande = "x" * 5000
    blocos = markdown_para_blocos(f"```\n{grande}\n```")
    itens = blocos[0]["code"]["rich_text"]
    assert len(itens) == 3  # 2000 + 2000 + 1000
    assert all(len(i["text"]["content"]) <= 2000 for i in itens)
    # A leitura reconstrói o texto inteiro, sem truncar.
    assert grande in blocos_para_markdown(blocos)


def test_markdown_para_blocos_conta_emoji_como_duas_unidades_utf16():
    # Emojis ocupam 2 unidades UTF-16; um item de 1000 emojis = 2000 unidades,
    # no limite. 1500 emojis (3000 unidades) precisa de pelo menos 2 itens, e
    # nenhum item pode passar de 2000 unidades UTF-16.
    grande = "🚀" * 1500
    itens = markdown_para_blocos(f"```\n{grande}\n```")[0]["code"]["rich_text"]
    assert len(itens) >= 2
    for item in itens:
        unidades = sum(2 if ord(c) > 0xFFFF else 1 for c in item["text"]["content"])
        assert unidades <= 2000


def test_markdown_para_blocos_ignora_linhas_em_branco():
    blocos = markdown_para_blocos("a\n\n\nb")
    assert [b["type"] for b in blocos] == ["paragraph", "paragraph"]


# -- Formatação inline (negrito, itálico, código, link) --------------------


def _itens(bloco):
    return bloco[bloco["type"]]["rich_text"]


def test_inline_negrito_italico_codigo():
    itens = _itens(markdown_para_blocos("um **negrito**, *itálico* e `code` aqui")[0])
    por_texto = {i["text"]["content"]: i.get("annotations", {}) for i in itens}
    assert por_texto["negrito"]["bold"] is True
    assert por_texto["itálico"]["italic"] is True
    assert por_texto["code"]["code"] is True
    assert "annotations" not in itens[0]  # "um " sem formatação


def test_inline_link_vira_href():
    itens = _itens(markdown_para_blocos("veja [o site](https://x.com) agora")[0])
    link = next(i for i in itens if i["text"]["content"] == "o site")
    assert link["text"]["link"] == {"url": "https://x.com"}


def test_inline_negrito_com_link_combinados():
    itens = _itens(markdown_para_blocos("**[bold link](https://y.com)**")[0])
    assert itens[0]["text"]["content"] == "bold link"
    assert itens[0]["annotations"]["bold"] is True
    assert itens[0]["text"]["link"] == {"url": "https://y.com"}


def test_inline_marcador_sem_par_vira_literal():
    itens = _itens(markdown_para_blocos("um * solto sem par")[0])
    assert "".join(i["text"]["content"] for i in itens) == "um * solto sem par"


def test_codigo_em_bloco_nao_parseia_inline():
    # Dentro de um bloco de código, ** e ` são literais, não viram formatação.
    itens = markdown_para_blocos("```\nx = **a**\n```")[0]["code"]["rich_text"]
    assert itens[0]["text"]["content"] == "x = **a**"
    assert "annotations" not in itens[0]


# -- Imagens, badges, HTML, headings, tabelas ------------------------------


def test_link_ancora_ou_relativo_vira_texto_sem_link():
    # O Notion rejeita URLs não-absolutas; o rótulo é preservado sem link.
    ancora = _itens(markdown_para_blocos("veja [a seção](#instalacao) abaixo")[0])
    alvo = next(i for i in ancora if i["text"]["content"] == "a seção")
    assert "link" not in alvo["text"]
    relativo = _itens(markdown_para_blocos("[doc](docs/guia.md)")[0])
    assert "link" not in relativo[0]["text"]


def test_link_http_mantem_link():
    itens = _itens(markdown_para_blocos("[site](https://x.com)")[0])
    assert itens[0]["text"]["link"] == {"url": "https://x.com"}


def test_imagem_com_url_relativa_nao_vira_bloco():
    # ![logo](./logo.png) tem URL relativa: o Notion rejeitaria — vira parágrafo.
    blocos = markdown_para_blocos("![logo](./logo.png)")
    assert blocos[0]["type"] == "paragraph"


def test_imagem_vira_bloco_image():
    blocos = markdown_para_blocos("![alt](https://img.com/x.png)")
    assert blocos[0]["type"] == "image"
    assert blocos[0]["image"]["external"]["url"] == "https://img.com/x.png"


def test_imagem_nao_tem_legenda():
    # O alt não vira caption — badges sem imagem deixariam só a legenda poluindo.
    bloco = markdown_para_blocos("![Python](https://img.shields.io/x.svg)")[0]
    assert "caption" not in bloco["image"]


def test_citacao_vazia_e_ignorada():
    # Linha só com '>' separa parágrafos de um blockquote, mas não é conteúdo.
    md = "> primeira linha\n>\n> segunda linha"
    tipos = [b["type"] for b in markdown_para_blocos(md)]
    assert tipos == ["quote", "quote"]  # nada de paragraph '>'


def test_badge_com_link_vira_bloco_image():
    blocos = markdown_para_blocos("[![Tests](https://img/badge.svg)](https://ci.com)")
    assert blocos[0]["type"] == "image"
    assert blocos[0]["image"]["external"]["url"] == "https://img/badge.svg"


def test_varias_badges_na_mesma_linha_viram_varios_blocos():
    blocos = markdown_para_blocos("![a](https://i/a.png) ![b](https://i/b.png)")
    assert [b["type"] for b in blocos] == ["image", "image"]


def test_imagem_com_texto_na_linha_nao_vira_bloco_image():
    # Há texto além da imagem: a linha vira parágrafo (imagem como link inline).
    blocos = markdown_para_blocos("veja ![logo](https://i/l.png) aqui")
    assert blocos[0]["type"] == "paragraph"


def test_html_div_e_center_sao_removidos_preservando_conteudo():
    blocos = markdown_para_blocos('<div align="center">\n\n# Título\n\n</div>')
    assert [b["type"] for b in blocos] == ["heading_1"]
    assert blocos[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Título"


def test_html_a_e_img_viram_markdown():
    a = markdown_para_blocos('<a href="https://x.com">site</a>')[0]
    item = a["paragraph"]["rich_text"][0]
    assert item["text"]["content"] == "site"
    assert item["text"]["link"] == {"url": "https://x.com"}
    img = markdown_para_blocos('<img src="https://i/x.png">')[0]
    assert img["type"] == "image"


def test_heading_4_a_6_viram_heading_3():
    for prefixo in ("#### ", "##### ", "###### "):
        bloco = markdown_para_blocos(f"{prefixo}Sub")[0]
        assert bloco["type"] == "heading_3"
        assert bloco["heading_3"]["rich_text"][0]["text"]["content"] == "Sub"


def test_setext_headings():
    assert markdown_para_blocos("Título\n======")[0]["type"] == "heading_1"
    assert markdown_para_blocos("Subtítulo\n------")[0]["type"] == "heading_2"


def test_tabela_vira_bloco_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    bloco = markdown_para_blocos(md)[0]
    assert bloco["type"] == "table"
    assert bloco["table"]["table_width"] == 2
    assert bloco["table"]["has_column_header"] is True
    linhas = bloco["table"]["children"]
    assert len(linhas) == 3  # cabeçalho + 2 linhas de dados
    assert linhas[0]["table_row"]["cells"][0][0]["text"]["content"] == "A"


# -- Round-trip da formatação rica -----------------------------------------


def _reidratar(blocos):
    """Adiciona plain_text como a API faria, para exercitar a leitura."""
    for bloco in blocos:
        corpo = bloco.get(bloco["type"], {})
        for rt in corpo.get("rich_text", []):
            rt["plain_text"] = rt["text"]["content"]
        for filho in corpo.get("children", []):
            for cel in filho.get("table_row", {}).get("cells", []):
                for rt in cel:
                    rt["plain_text"] = rt["text"]["content"]
    return blocos


def test_round_trip_inline_preserva_formatacao():
    md = "um **negrito** e [link](https://x.com) e `code`"
    saida = blocos_para_markdown(_reidratar(markdown_para_blocos(md)))
    assert "**negrito**" in saida
    assert "[link](https://x.com)" in saida
    assert "`code`" in saida


def test_round_trip_imagem_e_tabela():
    # O alt não é preservado (imagens vão sem legenda), mas a URL volta intacta.
    img = blocos_para_markdown(_reidratar(markdown_para_blocos("![alt](https://i/x.png)")))
    assert "(https://i/x.png)" in img
    md_tab = "| A | B |\n|---|---|\n| 1 | 2 |"
    tab = blocos_para_markdown(_reidratar(markdown_para_blocos(md_tab)))
    assert "| A | B |" in tab
    assert "| 1 | 2 |" in tab


# -- Conversor blocos -> Markdown (ida e volta) ----------------------------


def test_blocos_para_markdown_round_trip():
    md = "# Título\n\nUm parágrafo.\n\n- item\n\n- [x] feito"
    blocos = markdown_para_blocos(md)
    # Reidrata ``plain_text`` como a API faria, para exercitar a leitura.
    for bloco in blocos:
        corpo = bloco[bloco["type"]]
        for rt in corpo.get("rich_text", []):
            rt["plain_text"] = rt["text"]["content"]
    assert blocos_para_markdown(blocos) == md


def test_blocos_para_markdown_tipo_desconhecido_vira_paragrafo():
    blocos = [
        {
            "type": "callout",
            "callout": {"rich_text": [{"plain_text": "aviso"}]},
        }
    ]
    assert blocos_para_markdown(blocos) == "aviso"


# -- Blocos no NotionClient ------------------------------------------------


@responses.activate
def test_ler_blocos_pagina_unica():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={"results": [{"id": "b1", "type": "paragraph"}], "has_more": False},
        status=200,
    )
    blocos = criar_client().ler_blocos("page1")
    assert blocos[0]["id"] == "b1"


@responses.activate
def test_ler_blocos_pagina_todos_segue_cursor():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={"results": [{"id": "b1"}], "has_more": True, "next_cursor": "cur2"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={"results": [{"id": "b2"}], "has_more": False},
        status=200,
    )
    blocos = criar_client().ler_blocos("page1", buscar_todos=True)
    assert [b["id"] for b in blocos] == ["b1", "b2"]
    assert "start_cursor=cur2" in responses.calls[1].request.url


@responses.activate
def test_anexar_blocos_envia_children():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={"results": []},
        status=200,
    )
    criar_client().anexar_blocos("page1", markdown_para_blocos("oi"))
    corpo = json.loads(responses.calls[0].request.body)
    assert corpo["children"][0]["type"] == "paragraph"


def test_anexar_blocos_vazio_levanta():
    with pytest.raises(ValueError):
        criar_client().anexar_blocos("page1", [])


@responses.activate
def test_atualizar_bloco_envia_payload():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/blocks/b1",
        json={"id": "b1"},
        status=200,
    )
    criar_client().atualizar_bloco(
        "b1", {"paragraph": {"rich_text": [{"text": {"content": "novo"}}]}}
    )
    corpo = json.loads(responses.calls[0].request.body)
    assert corpo["paragraph"]["rich_text"][0]["text"]["content"] == "novo"


@responses.activate
def test_excluir_bloco_usa_delete():
    responses.add(
        responses.DELETE,
        f"{NOTION_BASE_URL}/blocks/b1",
        json={"id": "b1", "archived": True},
        status=200,
    )
    resultado = criar_client().excluir_bloco("b1")
    assert resultado["archived"] is True
    assert responses.calls[0].request.method == "DELETE"


def test_excluir_bloco_id_vazio_levanta():
    with pytest.raises(NotionConfigurationError):
        criar_client().excluir_bloco("   ")


# -- Data sources (modelo novo de database) --------------------------------


@responses.activate
def test_listar_data_sources_usa_versao_nova():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"data_sources": [{"id": "ds1", "name": "Principal"}]},
        status=200,
    )
    fontes = criar_client().listar_data_sources("db1")
    assert fontes == [{"id": "ds1", "name": "Principal"}]
    assert responses.calls[0].request.headers["Notion-Version"] == "2025-09-03"


@responses.activate
def test_listar_data_sources_sem_fontes_retorna_lista_vazia():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"object": "database"},
        status=200,
    )
    assert criar_client().listar_data_sources("db1") == []


@responses.activate
def test_consultar_data_source_pagina_todos():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/data_sources/ds1/query",
        json={"results": [{"id": "r1"}], "has_more": True, "next_cursor": "c2"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/data_sources/ds1/query",
        json={"results": [{"id": "r2"}], "has_more": False},
        status=200,
    )
    linhas = criar_client().consultar_data_source("ds1", buscar_todos=True)
    assert [linha["id"] for linha in linhas] == ["r1", "r2"]
    assert responses.calls[0].request.headers["Notion-Version"] == "2025-09-03"


@responses.activate
def test_get_data_source_le_schema():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/data_sources/ds1",
        json={"object": "data_source", "properties": {"Name": {"type": "title"}}},
        status=200,
    )
    schema = criar_client().get_data_source("ds1")
    assert schema["properties"]["Name"]["type"] == "title"


@responses.activate
def test_atualizar_data_source_usa_versao_nova_e_envia_propriedades():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/data_sources/ds1",
        json={"object": "data_source", "properties": {"Etapa": {"type": "status"}}},
        status=200,
    )
    props = {"Etapa": {"status": {"options": [{"name": "Entrada"}]}}}
    criar_client().atualizar_data_source("ds1", propriedades=props)
    chamada = responses.calls[0].request
    assert chamada.headers["Notion-Version"] == "2025-09-03"
    assert json.loads(chamada.body) == {"properties": props}


@responses.activate
def test_criar_pagina_em_fonte_usa_parent_data_source():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"id": "nova"},
        status=200,
    )
    props = {"Name": {"title": [{"type": "text", "text": {"content": "X"}}]}}
    criar_client().criar_pagina_em_fonte("ds1", props)
    corpo = json.loads(responses.calls[0].request.body)
    assert corpo["parent"] == {"type": "data_source_id", "data_source_id": "ds1"}
    assert corpo["properties"] == props
    assert responses.calls[0].request.headers["Notion-Version"] == "2025-09-03"


@responses.activate
def test_versao_padrao_nao_muda_nas_rotas_antigas():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "properties": {}},
        status=200,
    )
    criar_client().get_database("db1")
    assert responses.calls[0].request.headers["Notion-Version"] == "2022-06-28"


# -- Leitura recursiva (colunas, toggles, child_database) ------------------


@responses.activate
def test_ler_blocos_recursivo_desce_em_filhos():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={
            "results": [
                {"id": "col-list", "type": "column_list", "has_children": True},
            ],
            "has_more": False,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/col-list/children",
        json={
            "results": [
                {
                    "id": "p1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [{"plain_text": "dentro da coluna"}]},
                }
            ],
            "has_more": False,
        },
        status=200,
    )
    blocos = criar_client().ler_blocos("page1", recursivo=True)
    assert blocos[0]["_filhos"][0]["id"] == "p1"


@responses.activate
def test_ler_blocos_recursivo_nao_desce_em_child_database():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/page1/children",
        json={
            "results": [
                {"id": "db1", "type": "child_database", "has_children": True},
            ],
            "has_more": False,
        },
        status=200,
    )
    blocos = criar_client().ler_blocos("page1", recursivo=True)
    # Não deve ter feito uma segunda chamada para descer no child_database.
    assert "_filhos" not in blocos[0]
    assert len(responses.calls) == 1


def test_markdown_inclui_filhos_aninhados():
    blocos = [
        {
            "type": "column_list",
            "column_list": {},
            "_filhos": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "aninhado"}]}}
            ],
        }
    ]
    assert blocos_para_markdown(blocos) == "aninhado"


def test_markdown_child_database_mostra_titulo():
    blocos = [{"type": "child_database", "child_database": {"title": "Tarefas"}}]
    assert blocos_para_markdown(blocos) == "**[database: Tarefas]**"


def test_markdown_ignora_custom_emoji_em_titulo():
    blocos = [
        {
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {"type": "mention", "mention": {"type": "custom_emoji"}, "plain_text": ":x:"},
                    {"type": "text", "plain_text": " pessoal"},
                ]
            },
        }
    ]
    assert blocos_para_markdown(blocos) == "## pessoal"
