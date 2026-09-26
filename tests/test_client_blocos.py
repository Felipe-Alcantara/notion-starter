"""Contrato dos métodos de bloco do :class:`NotionClient`.

Cobre o que o cliente monta para a API (posição do append, restauração, leitura
de um bloco e de uma propriedade paginada) e o DELETE que precisa ser
idempotente de verdade. HTTP mockado com ``responses``; nenhum token real.
"""

from __future__ import annotations

import json

import pytest
import requests
import responses

from notion_starter import NotionClient
from notion_starter.constants import NOTION_BASE_URL
from notion_starter.exceptions import NotionHTTPError

TOKEN = "ntn_test_token"
BLOCO = "bloco-1"
PARAGRAFO = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}
ARQUIVADO_400 = {
    "object": "error",
    "status": 400,
    "code": "validation_error",
    "message": "Can't edit block that is archived. You must unarchive the block before editing.",
}


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


# -- excluir_bloco idempotente -----------------------------------------------


def _registrar_get_do_bloco(*, in_trash: bool) -> None:
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/{BLOCO}",
        json={"id": BLOCO, "type": "paragraph", "in_trash": in_trash, "archived": in_trash},
    )


@responses.activate
def test_delete_retentado_apos_timeout_nao_vira_erro():
    """1º DELETE arquiva mas perde a resposta; o 2º recebe 400 'archived'."""

    url = f"{NOTION_BASE_URL}/blocks/{BLOCO}"
    responses.add(responses.DELETE, url, body=requests.exceptions.ReadTimeout("lento"))
    responses.add(responses.DELETE, url, json=ARQUIVADO_400, status=400)
    _registrar_get_do_bloco(in_trash=True)

    resultado = _cliente(max_retries=2).excluir_bloco(BLOCO)

    assert resultado["in_trash"] is True
    metodos = [chamada.request.method for chamada in responses.calls]
    assert metodos == ["DELETE", "DELETE", "GET"]


@responses.activate
def test_delete_retentado_apos_502_nao_vira_erro():
    url = f"{NOTION_BASE_URL}/blocks/{BLOCO}"
    responses.add(responses.DELETE, url, json={"message": "bad gateway"}, status=502)
    responses.add(responses.DELETE, url, json=ARQUIVADO_400, status=400)
    _registrar_get_do_bloco(in_trash=True)

    resultado = _cliente(max_retries=2).excluir_bloco(BLOCO)

    assert resultado["id"] == BLOCO


@responses.activate
def test_400_com_bloco_ainda_ativo_continua_erro():
    """Se o bloco não está na lixeira, o 400 é um erro de verdade."""

    responses.add(
        responses.DELETE, f"{NOTION_BASE_URL}/blocks/{BLOCO}", json=ARQUIVADO_400, status=400
    )
    _registrar_get_do_bloco(in_trash=False)

    with pytest.raises(NotionHTTPError) as erro:
        _cliente().excluir_bloco(BLOCO)

    assert erro.value.status_code == 400


@responses.activate
def test_400_com_bloco_ilegivel_continua_erro_original():
    responses.add(
        responses.DELETE, f"{NOTION_BASE_URL}/blocks/{BLOCO}", json=ARQUIVADO_400, status=400
    )
    responses.add(
        responses.GET, f"{NOTION_BASE_URL}/blocks/{BLOCO}", json={"message": "x"}, status=404
    )

    with pytest.raises(NotionHTTPError) as erro:
        _cliente().excluir_bloco(BLOCO)

    assert erro.value.status_code == 400


@responses.activate
def test_404_no_delete_nao_rele_o_bloco():
    responses.add(
        responses.DELETE, f"{NOTION_BASE_URL}/blocks/{BLOCO}", json={"message": "x"}, status=404
    )

    with pytest.raises(NotionHTTPError):
        _cliente().excluir_bloco(BLOCO)

    assert [c.request.method for c in responses.calls] == ["DELETE"]


# -- ler_itens_de_propriedade ----------------------------------------------------------


@responses.activate
def test_ler_itens_de_propriedade_percorre_toda_a_paginacao():
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

    itens = _cliente().ler_itens_de_propriedade("pg", "%3AAbc")

    assert len(itens) == 101
    assert "start_cursor=c2" in responses.calls[1].request.url
    # O ID da propriedade segue como a API devolveu, sem codificar de novo.
    assert "/properties/%3AAbc?" in responses.calls[0].request.url


@responses.activate
def test_ler_itens_de_propriedade_nao_paginada_devolve_um_item():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/pg/properties/num",
        json={"object": "property_item", "type": "number", "number": 3},
    )

    assert _cliente().ler_itens_de_propriedade("pg", "num") == [
        {"object": "property_item", "type": "number", "number": 3}
    ]
