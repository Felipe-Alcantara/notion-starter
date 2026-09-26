"""Editar um bloco sem perder o que o Markdown não representa.

Medido no workspace real: ``editar-bloco`` com várias linhas gravava só a
primeira e respondia sucesso; texto puro num heading virava ``paragraph`` (400
"Block type mismatch"); e reenviar o próprio texto lido em ``conteudo``
destruía menções de data/página, sublinhado e cor.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.exceptions import (
    BlocoSemTextoError,
    EdicaoMultiblocoError,
    NotionSyncError,
    PerdaDeFormatacaoError,
    RichTextNaoRegravavelError,
    TrechoAmbiguoError,
    TrechoAtravessaItensError,
    TrechoNaoEncontradoError,
    TrocaDeTipoError,
)
from notion_starter.services import conteudo as svc


class ClienteBloco:
    def __init__(self, bloco: dict[str, Any] | None = None) -> None:
        self.bloco = bloco or {}
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.leituras = 0

    def obter_bloco(self, block_id):
        self.leituras += 1
        return self.bloco

    def atualizar_bloco(self, block_id, conteudo):
        self.patches.append((block_id, conteudo))
        tipo = next(iter(conteudo))
        return {
            "id": block_id,
            "type": tipo,
            tipo: conteudo[tipo],
            "last_edited_time": "2026-09-26T10:00:00.000Z",
        }


def _texto(conteudo: str, **anot) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": conteudo, "link": None},
        "annotations": {"bold": False, "underline": False, "color": "default", **anot},
        "plain_text": conteudo,
        "href": None,
    }


def _mencao_pagina(texto: str = "Página X") -> dict[str, Any]:
    return {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": "pg-x"}},
        "annotations": {"bold": False, "color": "default"},
        "plain_text": texto,
        "href": "https://www.notion.so/pgx",
    }


def _mencao_data() -> dict[str, Any]:
    return {
        "type": "mention",
        "mention": {"type": "date", "date": {"start": "2026-09-30", "end": None}},
        "annotations": {"color": "default"},
        "plain_text": "2026-09-30",
        "href": None,
    }


def _bloco(tipo: str, rich: list[dict[str, Any]], **extra) -> dict[str, Any]:
    return {"id": "b1", "type": tipo, tipo: {"rich_text": rich, **extra}}


# -- várias linhas ------------------------------------------------------------------------


@pytest.mark.parametrize("markdown", ["linha 1\nlinha 2 perdida", "> a\n> b", "# T\n\ncorpo"])
def test_editar_bloco_nao_pode_descartar_linhas_em_silencio(markdown):
    cliente = ClienteBloco()

    with pytest.raises(EdicaoMultiblocoError) as erro:
        svc.editar_bloco("b1", markdown, cliente=cliente)

    assert cliente.patches == []
    assert cliente.leituras == 0
    assert isinstance(erro.value, ValueError) and isinstance(erro.value, NotionSyncError)
    assert "Nada foi alterado".lower() in str(erro.value).lower()


def test_bloco_de_codigo_cercado_com_varias_linhas_continua_aceito():
    cliente = ClienteBloco()

    svc.editar_bloco("b1", "```python\na = 1\nb = 2\n```", cliente=cliente)

    (_, payload), = cliente.patches
    assert payload["code"]["rich_text"][0]["text"]["content"] == "a = 1\nb = 2"


def test_sem_conferir_continua_sem_leitura_previa():
    """Compatível com quem já chama (o MCP do app): um PATCH e nada mais."""

    cliente = ClienteBloco()

    svc.editar_bloco("b1", "## Novo título", cliente=cliente)

    assert cliente.leituras == 0
    assert "heading_2" in cliente.patches[0][1]


# -- conferir o bloco atual ------------------------------------------------------------------


@pytest.mark.parametrize("tipo", ["heading_3", "callout", "toggle", "quote", "bulleted_list_item"])
def test_texto_sem_prefixo_mantem_o_tipo_atual(tipo):
    cliente = ClienteBloco(_bloco(tipo, [_texto("antigo")]))

    svc.editar_bloco("b1", "[20:15] Agente X", conferir_atual=True, cliente=cliente)

    (_, payload), = cliente.patches
    assert list(payload) == [tipo]
    assert payload[tipo]["rich_text"][0]["text"]["content"] == "[20:15] Agente X"


def test_prefixo_de_outro_tipo_e_recusado():
    cliente = ClienteBloco(_bloco("heading_3", [_texto("x")]))

    with pytest.raises(TrocaDeTipoError, match="heading_3"):
        svc.editar_bloco("b1", "# x", conferir_atual=True, cliente=cliente)

    assert cliente.patches == []


def test_to_do_com_marcador_explicito_grava_checked():
    cliente = ClienteBloco(_bloco("to_do", [_texto("x")], checked=False))

    svc.editar_bloco("b1", "- [x] feito", conferir_atual=True, cliente=cliente)

    assert cliente.patches[0][1] == {
        "to_do": {
            "rich_text": [{"type": "text", "text": {"content": "feito"}}],
            "checked": True,
        }
    }


def test_bloco_de_codigo_recebe_o_texto_cru():
    cliente = ClienteBloco(_bloco("code", [_texto("antigo")], language="python"))

    svc.editar_bloco("b1", "x = **1**\ny = 2", conferir_atual=True, cliente=cliente)

    payload = cliente.patches[0][1]
    assert payload == {
        "code": {"rich_text": [{"type": "text", "text": {"content": "x = **1**\ny = 2"}}]}
    }


def test_bloco_sem_texto_e_recusado():
    cliente = ClienteBloco({"id": "b1", "type": "image", "image": {}})

    with pytest.raises(BlocoSemTextoError):
        svc.editar_bloco("b1", "legenda", conferir_atual=True, cliente=cliente)

    assert cliente.patches == []


def test_editar_bloco_recusa_quando_perderia_mencao_sublinhado_e_cor():
    rich = [
        _texto("Prazo ", underline=True, color="red"),
        _mencao_data(),
        _texto(" com "),
        _mencao_pagina("E8 alvo"),
    ]
    cliente = ClienteBloco(_bloco("paragraph", rich, color="blue_background"))

    with pytest.raises(PerdaDeFormatacaoError) as erro:
        svc.editar_bloco(
            "b1", "Prazo 2026-09-30 com [E8 alvo](https://x)", conferir_atual=True,
            cliente=cliente,
        )

    assert cliente.patches == []
    perdas = " | ".join(erro.value.perdas)
    assert "sublinhado em 'Prazo '" in perdas
    assert "cor 'red'" in perdas
    assert "menção de date" in perdas
    assert "menção de page" in perdas
    assert "trocar_trecho" in str(erro.value)


def test_aceitar_perda_de_formatacao_grava_mesmo_assim():
    cliente = ClienteBloco(_bloco("paragraph", [_texto("x", underline=True)]))

    svc.editar_bloco(
        "b1", "y", conferir_atual=True, aceitar_perda_de_formatacao=True, cliente=cliente
    )

    assert len(cliente.patches) == 1


# -- trocar_trecho ----------------------------------------------------------------------------


def test_trocar_preserva_mencoes_equacao_sublinhado_e_cor():
    rich = [
        _texto("[20:12] ", underline=True, color="red"),
        _mencao_pagina(),
        {"type": "equation", "equation": {"expression": "e=mc^2"}, "plain_text": "e=mc^2",
         "annotations": {"color": "default"}, "href": None},
        _texto(" fim", bold=True),
    ]
    cliente = ClienteBloco(_bloco("heading_3", rich, color="blue", is_toggleable=False))

    resultado = svc.trocar_trecho("b1", "[20:12]", "[21:40]", cliente=cliente)

    (_, payload), = cliente.patches
    enviado = payload["heading_3"]["rich_text"]
    assert list(payload["heading_3"]) == ["rich_text"]  # cor do bloco fica intacta
    assert enviado[0]["text"] == {"content": "[21:40] "}
    assert enviado[0]["annotations"]["underline"] is True
    assert enviado[0]["annotations"]["color"] == "red"
    assert enviado[1] == {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": "pg-x"}},
        "annotations": {"bold": False, "color": "default"},
    }
    assert enviado[2]["equation"] == {"expression": "e=mc^2"}
    assert enviado[3]["annotations"]["bold"] is True
    assert resultado.ocorrencias == 1
    assert resultado.markdown.startswith("### [21:40]")
    assert resultado.editado_em


def test_trocar_mencao_de_usuario_vai_so_com_o_id():
    usuario = {
        "type": "mention",
        "mention": {"type": "user", "user": {"object": "user", "id": "u1", "name": "Ana",
                                              "avatar_url": None, "type": "person"}},
        "plain_text": "@Ana",
        "href": None,
    }
    cliente = ClienteBloco(_bloco("paragraph", [_texto("oi "), usuario]))

    svc.trocar_trecho("b1", "oi", "olá", cliente=cliente)

    enviado = cliente.patches[0][1]["paragraph"]["rich_text"][1]
    assert enviado["mention"] == {"type": "user", "user": {"object": "user", "id": "u1"}}


def test_trecho_inexistente_mostra_o_texto_atual():
    cliente = ClienteBloco(_bloco("paragraph", [_texto("abc")]))

    with pytest.raises(TrechoNaoEncontradoError, match="Texto atual: 'abc'"):
        svc.trocar_trecho("b1", "xyz", "w", cliente=cliente)

    assert cliente.patches == []


def test_trecho_repetido_exige_todas():
    cliente = ClienteBloco(_bloco("paragraph", [_texto("a-a"), _texto(" a", bold=True)]))

    with pytest.raises(TrechoAmbiguoError):
        svc.trocar_trecho("b1", "a", "b", cliente=cliente)

    resultado = svc.trocar_trecho("b1", "a", "b", todas=True, cliente=cliente)

    assert resultado.ocorrencias == 3
    enviado = cliente.patches[0][1]["paragraph"]["rich_text"]
    assert [i["text"]["content"] for i in enviado] == ["b-b", " b"]


@pytest.mark.parametrize(
    "rich,trecho",
    [
        ([_texto("ab"), _texto("cd", bold=True)], "bc"),
        ([_texto("veja "), _mencao_pagina("Página X")], "Página"),
    ],
    ids=["atravessa-itens", "dentro-da-mencao"],
)
def test_trecho_que_cruza_itens_ou_fica_em_mencao_e_recusado(rich, trecho):
    cliente = ClienteBloco(_bloco("paragraph", rich))

    with pytest.raises(TrechoAtravessaItensError):
        svc.trocar_trecho("b1", trecho, "x", cliente=cliente)

    assert cliente.patches == []


def test_mencao_somente_leitura_impede_a_troca():
    previa = {"type": "mention", "mention": {"type": "link_preview",
                                              "link_preview": {"url": "https://x"}},
              "plain_text": "https://x", "href": "https://x"}
    cliente = ClienteBloco(_bloco("paragraph", [_texto("veja "), previa]))

    with pytest.raises(RichTextNaoRegravavelError, match="link_preview"):
        svc.trocar_trecho("b1", "veja", "olhe", cliente=cliente)

    assert cliente.patches == []


def test_troca_que_passa_de_2000_caracteres_e_fatiada_com_a_formatacao():
    cliente = ClienteBloco(_bloco("paragraph", [_texto("X", color="red")]))

    svc.trocar_trecho("b1", "X", "y" * 4500, cliente=cliente)

    enviado = cliente.patches[0][1]["paragraph"]["rich_text"]
    assert [len(i["text"]["content"]) for i in enviado] == [2000, 2000, 500]
    assert all(i["annotations"]["color"] == "red" for i in enviado)


def test_trocar_em_bloco_sem_texto_e_recusado():
    cliente = ClienteBloco({"id": "b1", "type": "divider", "divider": {}})

    with pytest.raises(BlocoSemTextoError):
        svc.trocar_trecho("b1", "a", "b", cliente=cliente)
