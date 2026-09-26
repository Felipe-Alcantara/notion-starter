"""Markdown ↔ blocos preserva a hierarquia de listas.

Antes, ``markdown_para_blocos`` tirava o recuo de toda linha (lista indentada
era gravada plana) e ``blocos_para_markdown`` mostrava os filhos como irmãos
('- pai\\n\\n- filho'), então ``conteudo`` → ``escrever`` achatava a página.
"""

from __future__ import annotations

import pytest

from notion_starter.content import blocos_para_markdown, markdown_para_blocos, validar_blocos
from notion_starter.exceptions import EdicaoMultiblocoError
from notion_starter.services import conteudo as svc


def _texto(bloco):
    tipo = bloco["type"]
    return bloco[tipo]["rich_text"][0]["text"]["content"]


def test_lista_indentada_vira_filhos():
    blocos = markdown_para_blocos("- pai\n  - filho\n    - neto\n- outro")

    assert [_texto(b) for b in blocos] == ["pai", "outro"]
    (filho,) = blocos[0]["bulleted_list_item"]["children"]
    assert _texto(filho) == "filho"
    (neto,) = filho["bulleted_list_item"]["children"]
    assert _texto(neto) == "neto"
    validar_blocos(blocos)


def test_numerada_e_tarefa_aceitam_recuo_de_3_espacos_ou_tab():
    blocos = markdown_para_blocos("1. passo\n   - detalhe\n- [ ] tarefa\n\t- sub")

    assert _texto(blocos[0]["numbered_list_item"]["children"][0]) == "detalhe"
    assert _texto(blocos[1]["to_do"]["children"][0]) == "sub"


def test_recuo_alem_de_dois_niveis_e_achatado_no_segundo():
    """A API aceita dois níveis por requisição; o texto não se perde."""

    blocos = markdown_para_blocos("- a\n  - b\n    - c\n      - d")

    b = blocos[0]["bulleted_list_item"]["children"][0]
    netos = b["bulleted_list_item"]["children"]
    assert [_texto(x) for x in netos] == ["c", "d"]
    validar_blocos(blocos)


def test_recuo_sob_paragrafo_nao_aninha():
    blocos = markdown_para_blocos("texto\n    recuado")

    assert [b["type"] for b in blocos] == ["paragraph", "paragraph"]
    assert "children" not in blocos[0]["paragraph"]


def test_codigo_dentro_de_item_perde_so_o_recuo_do_item():
    blocos = markdown_para_blocos("- item\n  ```python\n  x = 1\n    y = 2\n  ```")

    codigo = blocos[0]["bulleted_list_item"]["children"][0]
    assert codigo["type"] == "code"
    assert _texto(codigo) == "x = 1\n  y = 2"


@pytest.mark.parametrize(
    "tipo,marcador,recuo",
    [
        ("bulleted_list_item", "- pai", "  "),
        ("numbered_list_item", "1. pai", "   "),
        ("to_do", "- [ ] pai", "  "),
    ],
)
def test_leitura_recua_os_filhos_sob_o_pai(tipo, marcador, recuo):
    corpo = {"rich_text": [{"plain_text": "pai"}]}
    if tipo == "to_do":
        corpo["checked"] = False
    pai = {
        "type": tipo,
        tipo: corpo,
        "_filhos": [
            {"type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": [{"plain_text": "filho"}]}},
        ],
    }

    assert blocos_para_markdown([pai]) == f"{marcador}\n{recuo}- filho"


def test_ida_e_volta_preserva_a_arvore():
    markdown = "- pai\n  - filho\n    - neto\n- irmão"
    blocos = markdown_para_blocos(markdown)

    def como_lidos(lista):
        lidos = []
        for bloco in lista:
            tipo = bloco["type"]
            corpo = dict(bloco[tipo])
            filhos = corpo.pop("children", None)
            corpo["rich_text"] = [{"plain_text": _texto(bloco)}]
            lido = {"type": tipo, tipo: corpo}
            if filhos:
                lido["_filhos"] = como_lidos(filhos)
            lidos.append(lido)
        return lidos

    relido = blocos_para_markdown(como_lidos(blocos))
    assert markdown_para_blocos(relido) == blocos


def test_colunas_continuam_sem_recuo():
    blocos = [
        {
            "type": "column_list",
            "column_list": {},
            "_filhos": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "x"}]}}],
        }
    ]
    assert blocos_para_markdown(blocos) == "x"


def test_editar_bloco_recusa_item_com_filhos():
    class Cliente:
        def atualizar_bloco(self, *a):
            raise AssertionError("não deveria gravar")

    with pytest.raises(EdicaoMultiblocoError):
        svc.editar_bloco("b1", "- pai\n  - filho", cliente=Cliente())
