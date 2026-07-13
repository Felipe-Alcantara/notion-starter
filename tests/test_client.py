from __future__ import annotations

import pytest
import requests
import responses

from notion_starter import NotionClient
from notion_starter.constants import NOTION_BASE_URL, NOTION_TOKEN_ENV
from notion_starter.exceptions import (
    NotionConfigurationError,
    NotionConnectionError,
    NotionHTTPError,
    NotionInvalidResponseError,
)

TOKEN = "ntn_test_token"


def criar_client() -> NotionClient:
    return NotionClient(token=TOKEN, max_retries=0)


# -- Resolução de token ----------------------------------------------------


def test_token_explicito_e_usado():
    client = NotionClient(token=TOKEN)
    assert client._headers()["Authorization"] == f"Bearer {TOKEN}"


def test_token_do_ambiente(monkeypatch):
    monkeypatch.setenv(NOTION_TOKEN_ENV, TOKEN)
    client = NotionClient()
    assert client._headers()["Authorization"] == f"Bearer {TOKEN}"


def test_token_ausente_levanta(monkeypatch):
    monkeypatch.delenv(NOTION_TOKEN_ENV, raising=False)
    with pytest.raises(NotionConfigurationError):
        NotionClient()


def test_token_malformado_levanta():
    with pytest.raises(NotionConfigurationError):
        NotionClient(token="secret_sem_prefixo")


def test_identificador_vazio_levanta():
    client = criar_client()
    with pytest.raises(NotionConfigurationError):
        client.get_database("   ")


# -- Comportamento HTTP ----------------------------------------------------


@responses.activate
def test_get_database_ok():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        json={"id": "db123", "properties": {}},
        status=200,
    )
    client = criar_client()
    data = client.get_database("db123")
    assert data["id"] == "db123"
    assert responses.calls[0].request.headers["Notion-Version"]


@responses.activate
def test_obter_pagina_ok():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/pages/page1",
        json={"id": "page1", "properties": {"Nome": {"type": "title", "title": []}}},
        status=200,
    )
    client = criar_client()
    data = client.obter_pagina("page1")
    assert data["id"] == "page1"
    assert data["properties"]["Nome"]["type"] == "title"


@responses.activate
def test_criar_pagina_envia_payload_esperado():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"id": "page1"},
        status=200,
    )
    client = criar_client()
    client.criar_pagina("db123", {"Nome": {"title": [{"text": {"content": "Oi"}}]}})
    body = responses.calls[0].request.body
    assert b'"database_id": "db123"' in body
    assert b'"Nome"' in body


@responses.activate
def test_criar_subpagina_envia_parent_page_e_titulo():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"id": "sub1"},
        status=200,
    )
    client = criar_client()
    bloco = {"type": "paragraph", "paragraph": {"rich_text": []}}
    resposta = client.criar_subpagina("pai123", "README", blocos=[bloco])
    assert resposta["id"] == "sub1"
    body = responses.calls[0].request.body
    assert b'"page_id": "pai123"' in body
    assert b'"README"' in body
    assert b'"children"' in body


@responses.activate
def test_criar_subpagina_quebra_blocos_em_lotes_de_100():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"id": "sub1"},
        status=200,
    )
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/blocks/sub1/children",
        json={"results": []},
        status=200,
    )
    client = criar_client()
    blocos = [
        {"type": "paragraph", "paragraph": {"rich_text": []}} for _ in range(150)
    ]
    client.criar_subpagina("pai123", "README", blocos=blocos)
    # 1 criação (100 blocos) + 1 anexação (50 restantes).
    assert len(responses.calls) == 2
    assert responses.calls[1].request.url.endswith("/blocks/sub1/children")


def test_criar_subpagina_exige_titulo():
    client = criar_client()
    with pytest.raises(NotionConfigurationError):
        client.criar_subpagina("pai123", "   ")


@responses.activate
def test_atualizar_database_envia_payload_e_invalida_cache():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        json={"id": "db123", "properties": {"Status": {"type": "status"}}},
        status=200,
    )
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/databases/db123",
        json={"id": "db123", "title": [{"plain_text": "Tarefas"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        json={"id": "db123", "properties": {"Etapa": {"type": "status"}}},
        status=200,
    )

    client = NotionClient(token=TOKEN)
    assert "Status" in client.get_database("db123")["properties"]
    client.atualizar_database(
        "db123",
        titulo="Tarefas",
        propriedades={"Status": {"name": "Etapa"}},
    )
    assert "Etapa" in client.get_database("db123")["properties"]

    body = responses.calls[1].request.body
    assert b'"title":' in body
    assert b'"Status": {"name": "Etapa"}' in body


def test_atualizar_database_exige_campo():
    with pytest.raises(ValueError, match="titulo ou propriedades"):
        criar_client().atualizar_database("db123")


@responses.activate
def test_erro_http_levanta_notion_http_error():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        json={"message": "not found"},
        status=404,
    )
    client = criar_client()
    with pytest.raises(NotionHTTPError) as exc_info:
        client.get_database("db123")
    assert exc_info.value.status_code == 404


@responses.activate
def test_erro_de_conexao_levanta():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        body=requests.exceptions.ConnectionError("boom"),
    )
    client = criar_client()
    with pytest.raises(NotionConnectionError):
        client.get_database("db123")


@responses.activate
def test_json_invalido_levanta():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db123",
        body="nao-json",
        status=200,
        content_type="text/plain",
    )
    client = criar_client()
    with pytest.raises(NotionInvalidResponseError):
        client.get_database("db123")


# -- Paginação -------------------------------------------------------------


@responses.activate
def test_consultar_database_buscar_todos_percorre_paginas():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db123/query",
        json={"results": [{"id": "a"}], "has_more": True, "next_cursor": "c1"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db123/query",
        json={"results": [{"id": "b"}], "has_more": False},
        status=200,
    )
    client = criar_client()
    linhas = client.consultar_database("db123", buscar_todos=True)
    assert [linha["id"] for linha in linhas] == ["a", "b"]


def test_consultar_database_rejeita_page_size_invalido():
    client = criar_client()
    with pytest.raises(ValueError):
        client.consultar_database("db123", page_size=0)


# -- Busca -----------------------------------------------------------------


@responses.activate
def test_buscar_buscar_todos_percorre_paginas():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/search",
        json={"results": [{"id": "a"}], "has_more": True, "next_cursor": "c1"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/search",
        json={"results": [{"id": "b"}], "has_more": False},
        status=200,
    )
    client = criar_client()
    itens = client.buscar(buscar_todos=True)
    assert [item["id"] for item in itens] == ["a", "b"]


@responses.activate
def test_buscar_inclui_query_no_payload():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/search",
        json={"results": [], "has_more": False},
        status=200,
    )
    client = criar_client()
    client.buscar(query="Tarefas")
    assert b'"query": "Tarefas"' in responses.calls[0].request.body


def test_buscar_rejeita_page_size_invalido():
    client = criar_client()
    with pytest.raises(ValueError):
        client.buscar(page_size=0)


# -- Re-parent e upload (novas primitivas) ---------------------------------


@responses.activate
def test_mover_pagina_envia_novo_parent():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/pag1",
        json={"id": "pag1"},
        status=200,
    )
    client = criar_client()
    client.mover_pagina("pag1", "destino1")
    corpo = responses.calls[0].request.body
    assert b'"parent"' in corpo
    assert b'"page_id"' in corpo
    assert b"destino1" in corpo


@responses.activate
def test_mover_pagina_aceita_database_como_pai():
    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/pages/pag1", json={"id": "pag1"}, status=200
    )
    client = criar_client()
    client.mover_pagina("pag1", "db1", tipo_pai="database_id")
    assert b'"database_id"' in responses.calls[0].request.body


def test_mover_pagina_tipo_pai_invalido_levanta():
    client = criar_client()
    with pytest.raises(ValueError):
        client.mover_pagina("pag1", "destino1", tipo_pai="workspace")


@responses.activate
def test_mover_database_usa_versao_data_source():
    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/databases/db1", json={"id": "db1"}, status=200
    )
    client = criar_client()
    client.mover_database("db1", "destino1")
    headers = responses.calls[0].request.headers
    assert headers["Notion-Version"] == "2025-09-03"
    assert b"destino1" in responses.calls[0].request.body


@responses.activate
def test_enviar_arquivo_faz_dois_passos_e_retorna_id():
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/file_uploads",
        json={"id": "upload42"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/file_uploads/upload42/send",
        json={"id": "upload42", "status": "uploaded"},
        status=200,
    )
    client = criar_client()
    uid = client.enviar_arquivo(b"conteudo", "relatorio.docx", "application/msword")
    assert uid == "upload42"
    assert len(responses.calls) == 2
    assert responses.calls[1].request.url.endswith("/file_uploads/upload42/send")


@responses.activate
def test_enviar_arquivo_erro_no_send_levanta():
    responses.add(
        responses.POST, f"{NOTION_BASE_URL}/file_uploads", json={"id": "u1"}, status=200
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/file_uploads/u1/send",
        json={"message": "too large"},
        status=400,
    )
    client = criar_client()
    with pytest.raises(NotionHTTPError):
        client.enviar_arquivo(b"x", "a.bin")
