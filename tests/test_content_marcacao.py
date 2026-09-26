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


@pytest.mark.parametrize(
    "texto",
    [
        "*a " * 5000,
        "_a _" * 3000,
        "~~a " * 4000,
        ", ".join(["*.pyc", "*.log", "*.tmp"] * 400),
        '[{"_id": 1, "_score": 0.5}, ' * 300 + "]",
        " ".join(["**Nota: **texto"] * 300),
    ],
)
def test_linha_longa_de_marcadores_sem_par_e_linear_e_fica_literal(texto):
    inicio = time.perf_counter()
    itens = _itens(texto)
    assert time.perf_counter() - inicio < 1.0
    assert "".join(i["text"]["content"] for i in itens) == texto.strip()


def test_corridas_longas_casam_inteiras_como_no_commonmark():
    inicio = time.perf_counter()
    assert _formatados("*" * 5000 + "Atenção" + "*" * 5000) == {"Atenção": {"bold"}}
    assert time.perf_counter() - inicio < 1.0


@pytest.mark.parametrize(
    ("markdown", "esperado"),
    [
        ("*Nota: o **CI** falhou.*", {"Nota: o ": {"italic"}, "CI": {"bold", "italic"},
                                      " falhou.": {"italic"}}),
        ("_Obs: __isto__ é sério_", {"Obs: ": {"italic"}, "isto": {"bold", "italic"},
                                     " é sério": {"italic"}}),
        ("**Aviso: *leia* isto**", {"Aviso: ": {"bold"}, "leia": {"bold", "italic"},
                                    " isto": {"bold"}}),
        ("***x***", {"x": {"bold", "italic"}}),
        ("*a **b c*", {"b c": {"italic"}}),  # o fechamento casa com a abertura mais próxima
    ],
)
def test_enfase_aninhada_do_mesmo_caractere(markdown, esperado):
    assert _formatados(markdown) == esperado


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


# -- HTML ---------------------------------------------------------------------


def test_codigo_inline_nunca_perde_marcador_entre_sinais_de_menor_e_maior():
    itens = _itens("rode `DATABASE_URL=<banco descartável migrado> python x.py` e `a@<versão>`")
    codigos = [i["text"]["content"] for i in itens if (i.get("annotations") or {}).get("code")]
    assert codigos == ["DATABASE_URL=<banco descartável migrado> python x.py", "a@<versão>"]


def test_codigo_inline_nao_decodifica_entidade_nem_remove_tag():
    itens = _itens("`a &amp; <b>` fim")
    assert itens[0]["text"]["content"] == "a &amp; <b>"


@pytest.mark.parametrize(
    "texto",
    [
        "use <versão>, <id> e <nome do banco> aqui",
        "se a < b e c > d, ok",
        "filtro: https://a.com/busca?q=x&region=br&copy=1&para=2",
    ],
)
def test_texto_que_parece_html_fica_intacto(texto):
    assert _texto(texto) == texto


def test_tags_de_elementos_html_e_comentarios_sao_removidos():
    assert _texto('<div align="center">x</div> <!-- nota --> <b>y</b>') == "x  y"


def test_entidade_com_ponto_e_virgula_e_decodificada():
    assert _texto("a &amp; b &copy; c") == "a & b © c"


def test_autolink_vira_link_com_a_propria_url():
    itens = _itens("veja <https://a.com/x_y> agora")
    link = next(i for i in itens if i["text"].get("link"))
    assert link["text"]["content"] == "https://a.com/x_y"
    assert link["text"]["link"] == {"url": "https://a.com/x_y"}
