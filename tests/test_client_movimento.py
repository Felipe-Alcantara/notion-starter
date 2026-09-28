"""``NotionClient.mover_pagina`` move de verdade e confere o pai relido.

Medido em 2026-09-27: ``PATCH /pages/{id}`` com ``parent`` responde 200 e o
Notion ignora o campo. O endpoint que move é ``POST /pages/{id}/move`` com
``Notion-Version: 2025-09-03``; depois dele, a releitura precisa mostrar o
destino — senão o método sobe ``MovimentoNaoAplicadoError``.
"""

from __future__ import annotations

import json

import pytest
import responses

from notion_starter import NotionClient
from notion_starter.constants import NOTION_BASE_URL, NOTION_DATA_SOURCE_VERSION
from notion_starter.exceptions import (
    FonteDeDadosIndefinidaError,
    MovimentoNaoAplicadoError,
    NotionSyncError,
)

PAGINA = "3ab91f95-497e-8190-9d77-fba045d775a8"
DESTINO = "3ab91f95-497e-817b-97fd-c8f79374e7d9"
DATABASE = "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
FONTE = "38e91f95-497e-818b-ab08-ff19918d6c7c"
ORIGEM = "11111111-2222-3333-4444-555555555555"


def _cliente() -> NotionClient:
    return NotionClient(token="ntn_teste", max_retries=0)


def _pagina(parent: dict[str, str]) -> dict[str, object]:
    return {"object": "page", "id": PAGINA, "parent": parent, "properties": {}}


@responses.activate
def test_move_para_pagina_pelo_endpoint_move_e_confere_o_pai():
    responses.add(responses.POST, f"{NOTION_BASE_URL}/pages/{PAGINA}/move", json={"id": PAGINA})
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/{PAGINA}",
        json=_pagina({"type": "page_id", "page_id": DESTINO.replace("-", "")}),
    )

    relida = _cliente().mover_pagina(PAGINA, DESTINO)

    movimento = responses.calls[0].request
    assert movimento.method == "POST"
    assert movimento.headers["Notion-Version"] == NOTION_DATA_SOURCE_VERSION
    assert json.loads(movimento.body) == {"parent": {"type": "page_id", "page_id": DESTINO}}
    assert all(chamada.request.method != "PATCH" for chamada in responses.calls)
    assert relida["parent"]["page_id"] == DESTINO.replace("-", "")


@responses.activate
def test_pai_relido_diferente_levanta_movimento_nao_aplicado():
    # É exatamente o sintoma medido: 200 no pedido, pai antigo na releitura.
    responses.add(responses.POST, f"{NOTION_BASE_URL}/pages/{PAGINA}/move", json={"id": PAGINA})
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/{PAGINA}",
        json=_pagina({"type": "page_id", "page_id": ORIGEM}),
    )

    with pytest.raises(MovimentoNaoAplicadoError) as erro:
        _cliente().mover_pagina(PAGINA, DESTINO)

    assert erro.value.page_id == PAGINA
    assert erro.value.pai_atual == {"type": "page_id", "page_id": ORIGEM}
    assert isinstance(erro.value, NotionSyncError)


@responses.activate
def test_destino_database_resolve_a_fonte_unica_e_aceita_pai_database():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DATABASE}",
        json={"id": DATABASE, "data_sources": [{"id": FONTE, "name": "Artigos"}]},
    )
    responses.add(responses.POST, f"{NOTION_BASE_URL}/pages/{PAGINA}/move", json={"id": PAGINA})
    # Medido: a releitura mostra o database dono da fonte, não a fonte.
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/{PAGINA}",
        json=_pagina({"type": "database_id", "database_id": DATABASE}),
    )

    _cliente().mover_pagina(PAGINA, DATABASE, tipo_pai="database_id")

    corpo = json.loads(responses.calls[1].request.body)
    assert corpo == {"parent": {"type": "data_source_id", "data_source_id": FONTE}}


@responses.activate
def test_database_com_varias_fontes_exige_escolha_sem_mover():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DATABASE}",
        json={
            "id": DATABASE,
            "data_sources": [{"id": FONTE, "name": "A"}, {"id": ORIGEM, "name": "B"}],
        },
    )

    with pytest.raises(FonteDeDadosIndefinidaError) as erro:
        _cliente().mover_pagina(PAGINA, DATABASE, tipo_pai="database_id")

    assert erro.value.fontes == [(FONTE, "A"), (ORIGEM, "B")]
    assert isinstance(erro.value, ValueError)
    assert len(responses.calls) == 1  # nada foi movido


@responses.activate
def test_database_sem_fonte_visivel_explica_o_compartilhamento():
    responses.add(
        responses.GET, f"{NOTION_BASE_URL}/databases/{DATABASE}", json={"id": DATABASE}
    )

    with pytest.raises(FonteDeDadosIndefinidaError, match="compartilhe"):
        _cliente().resolver_data_source(DATABASE)


@responses.activate
def test_destino_data_source_confere_pelo_database_dono():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/data_sources/{FONTE}",
        json={"id": FONTE, "parent": {"type": "database_id", "database_id": DATABASE}},
    )
    responses.add(responses.POST, f"{NOTION_BASE_URL}/pages/{PAGINA}/move", json={"id": PAGINA})
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/{PAGINA}",
        json=_pagina({"type": "database_id", "database_id": DATABASE.replace("-", "")}),
    )

    relida = _cliente().mover_pagina(PAGINA, FONTE, tipo_pai="data_source_id")

    assert relida["parent"]["type"] == "database_id"
    corpo = json.loads(responses.calls[1].request.body)
    assert corpo["parent"] == {"type": "data_source_id", "data_source_id": FONTE}


@responses.activate
def test_destino_data_source_com_pai_de_outro_database_falha():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/data_sources/{FONTE}",
        json={"id": FONTE, "parent": {"type": "database_id", "database_id": DATABASE}},
    )
    responses.add(responses.POST, f"{NOTION_BASE_URL}/pages/{PAGINA}/move", json={"id": PAGINA})
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/{PAGINA}",
        json=_pagina({"type": "database_id", "database_id": ORIGEM}),
    )

    with pytest.raises(MovimentoNaoAplicadoError):
        _cliente().mover_pagina(PAGINA, FONTE, tipo_pai="data_source_id")
