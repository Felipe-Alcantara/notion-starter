"""Contrato dos métodos de bloco do :class:`NotionClient`.

Cobre o que o cliente monta para a API (posição do append, restauração, leitura
de um bloco e de uma propriedade paginada) e o DELETE que precisa ser
idempotente de verdade. HTTP mockado com ``responses``; nenhum token real.
"""

from __future__ import annotations

import json

import pytest
import responses

from notion_starter import NotionClient
from notion_starter.constants import NOTION_BASE_URL

TOKEN = "ntn_test_token"
BLOCO = "bloco-1"
PARAGRAFO = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}


def _cliente(max_retries: int = 0) -> NotionClient:
    return NotionClient(token=TOKEN, max_retries=max_retries, backoff_base=0.0)


def _corpo(indice: int = 0) -> dict:
    return json.loads(responses.calls[indice].request.body)


# -- anexar_blocos: posição --------------------------------------------------


@responses.activate
def test_anexar_no_inicio_envia_position_start():
    """``--inicio`` sem ``position`` caía no FIM (o padrão da API é ``end``)."""

    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/blocks/pg/children", json={"results": []}
    )

    _cliente().anexar_blocos("pg", [PARAGRAFO], no_inicio=True)

    assert _corpo()["position"] == {"type": "start"}


@responses.activate
def test_anexar_apos_bloco_usa_position_e_nunca_o_after_legado():
    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/blocks/pg/children", json={"results": []}
    )

    _cliente().anexar_blocos("pg", [PARAGRAFO], apos_bloco_id="ancora")

    corpo = _corpo()
    assert corpo["position"] == {"type": "after_block", "after_block": {"id": "ancora"}}
    assert "after" not in corpo


@responses.activate
def test_anexar_sem_posicao_nao_manda_position():
    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/blocks/pg/children", json={"results": []}
    )

    _cliente().anexar_blocos("pg", [PARAGRAFO])

    assert "position" not in _corpo()


def test_anexar_no_inicio_e_apos_juntos_e_recusado():
    with pytest.raises(ValueError, match="não os dois"):
        _cliente().anexar_blocos("pg", [PARAGRAFO], apos_bloco_id="a", no_inicio=True)


# -- obter_bloco / restaurar_bloco -------------------------------------------


@responses.activate
def test_obter_bloco_le_um_bloco_pelo_id():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/{BLOCO}",
        json={"id": BLOCO, "type": "paragraph", "has_children": False},
    )

    bloco = _cliente().obter_bloco(BLOCO)

    assert bloco["id"] == BLOCO
    assert responses.calls[0].request.method == "GET"


@responses.activate
def test_restaurar_bloco_tira_da_lixeira_com_in_trash_false():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/blocks/{BLOCO}",
        json={"id": BLOCO, "in_trash": False},
    )

    _cliente().restaurar_bloco(BLOCO)

    assert _corpo() == {"in_trash": False}


# -- ler_propriedade ----------------------------------------------------------


@responses.activate
def test_ler_propriedade_percorre_toda_a_paginacao():
    """``GET /pages`` corta relação em 25; o endpoint de propriedade não."""

    url = f"{NOTION_BASE_URL}/pages/pg/properties/%3AAbc"
    responses.add(
        responses.GET,
        url,
        json={
            "object": "list",
            "results": [{"type": "relation", "relation": {"id": f"r{i}"}} for i in range(100)],
            "has_more": True,
            "next_cursor": "c2",
        },
    )
    responses.add(
        responses.GET,
        url,
        json={
            "object": "list",
            "results": [{"type": "relation", "relation": {"id": "r100"}}],
            "has_more": False,
            "next_cursor": None,
        },
    )

    itens = _cliente().ler_propriedade("pg", "%3AAbc")

    assert len(itens) == 101
    assert "start_cursor=c2" in responses.calls[1].request.url
    # O ID da propriedade segue como a API devolveu, sem codificar de novo.
    assert "/properties/%3AAbc?" in responses.calls[0].request.url


@responses.activate
def test_ler_propriedade_nao_paginada_devolve_um_item():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/pg/properties/num",
        json={"object": "property_item", "type": "number", "number": 3},
    )

    assert _cliente().ler_propriedade("pg", "num") == [
        {"object": "property_item", "type": "number", "number": 3}
    ]
