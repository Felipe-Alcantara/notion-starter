"""Ênfase e HTML no conversor Markdown: o que não é marcação fica como texto."""

from __future__ import annotations

import time

import pytest

from notion_starter import blocos_para_markdown, markdown_para_blocos


def _itens(markdown: str) -> list[dict]:
    bloco = markdown_para_blocos(markdown)[0]
    return bloco[bloco["type"]]["rich_text"]


def _texto(markdown: str) -> str:
    return "".join(item["text"]["content"] for item in _itens(markdown))


def _formatados(markdown: str) -> dict[str, set[str]]:
    return {
        item["text"]["content"]: {k for k, v in (item.get("annotations") or {}).items() if v}
        for item in _itens(markdown)
        if item.get("annotations")
    }


# -- Ênfase: flanqueamento ---------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "FELIXO_UPDATE_PRERELEASE e FELIXO_DISABLE_AUTO_UPDATE=1",
        "snake_case_name",
        "arquivo_v2_final.md",
        "2 * 3 * 4",
        "a ** b ** c",
        "custo ~~ fixo ~~ mensal",
        "x _ y _ z",
    ],
)
def test_marcador_colado_em_palavra_ou_entre_espacos_fica_literal(texto):
    assert _texto(texto) == texto
    assert _formatados(texto) == {}


def test_rotulo_de_link_mantem_sublinhados_e_o_link_inteiro():
    itens = _itens("veja [link_com_sub](https://a.com/x_y_z) agora")
    link = [i for i in itens if i["text"].get("link")]
    assert [i["text"]["content"] for i in link] == ["link_com_sub"]
    assert link[0]["text"]["link"] == {"url": "https://a.com/x_y_z"}


@pytest.mark.parametrize(
    ("markdown", "esperado"),
    [
        ("*ênfase*", {"ênfase": {"italic"}}),
        ("_x_ e __y__", {"x": {"italic"}, "y": {"bold"}}),
        ("**negrito** e ~~riscado~~", {"negrito": {"bold"}, "riscado": {"strikethrough"}}),
        ("a*b*c", {"b": {"italic"}}),
        ("**Agente:** Tasks", {"Agente:": {"bold"}}),
        ("(**23%**)", {"23%": {"bold"}}),
        ("Fim:**06:42**", {"06:42": {"bold"}}),
        ("Campo **(opcional)**obrigatório", {"(opcional)": {"bold"}}),
    ],
)
def test_enfase_valida_continua_funcionando(markdown, esperado):
    assert _formatados(markdown) == esperado


def test_corrida_longa_de_marcadores_e_linear_e_nao_perde_texto():
    texto = "*" * 5000 + "Atenção" + "*" * 5000
    inicio = time.perf_counter()
    conteudo = "".join(i["text"]["content"] for i in _itens(texto))
    assert time.perf_counter() - inicio < 1.0
    assert conteudo.count("Atenção") == 1
    assert len(conteudo) >= len(texto) - 4  # só o par que envolve "Atenção" é consumido


# -- Leitura: ida e volta ----------------------------------------------------


def _paragrafo(*itens: dict) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": list(itens)}}


def _item(texto: str, **anotacoes: bool) -> dict:
    return {
        "type": "text",
        "text": {"content": texto},
        "plain_text": texto,
        "annotations": anotacoes,
    }


def test_leitura_deixa_espaco_da_ponta_fora_dos_marcadores():
    bloco = _paragrafo(_item("Nota: ", bold=True), _item("texto"))
    markdown = blocos_para_markdown([bloco])
    assert markdown == "**Nota:** texto"
    assert _formatados(markdown) == {"Nota:": {"bold"}}


def test_ida_e_volta_de_italico_no_meio_da_palavra():
    bloco = _paragrafo(_item("FELIXO"), _item("UPDATE", italic=True), _item("PRERELEASE"))
    assert _formatados(blocos_para_markdown([bloco])) == {"UPDATE": {"italic"}}


def test_ida_e_volta_de_texto_simples_com_sublinhado_e_asterisco():
    bloco = _paragrafo(_item("rode snake_case_name e 2 * 3 * 4"))
    markdown = blocos_para_markdown([bloco])
    assert _texto(markdown) == "rode snake_case_name e 2 * 3 * 4"
    assert _formatados(markdown) == {}
