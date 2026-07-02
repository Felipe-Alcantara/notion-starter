"""Testes de resiliência do NotionClient — retry, backoff, rate limit e cache.

Complementa ``test_client.py`` (que testa comportamento HTTP base e resolução de
token). Aqui o foco é a Fase 1 do PLANO: robustez do cliente contra rate limit,
erros de servidor e falhas de rede, e o cache de schema.

Todos os testes usam HTTP mockado (``responses``), sem token nem rede real.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
import responses

from notion_starter import NotionClient
from notion_starter.constants import NOTION_BASE_URL
from notion_starter.exceptions import (
    NotionConfigurationError,
    NotionConnectionError,
    NotionHTTPError,
)

TOKEN = "ntn_test_token"


def criar_client(
    max_retries: int = 2,
    backoff_base: float = 0.0,
    cache_ttl: int = 300,
) -> NotionClient:
    """Cria um client com backoff zerado para os testes não esperarem."""

    return NotionClient(
        token=TOKEN,
        max_retries=max_retries,
        backoff_base=backoff_base,
        cache_ttl=cache_ttl,
    )


# -- Retry em HTTP 429 (rate limit) ----------------------------------------


@responses.activate
def test_retry_429_sucesso_na_segunda_tentativa():
    """429 na primeira, 200 na segunda → retorna normalmente."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "rate limited"},
        status=429,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "properties": {}},
        status=200,
    )
    client = criar_client()
    data = client.get_database("db1")
    assert data["id"] == "db1"
    assert len(responses.calls) == 2


@responses.activate
def test_retry_429_respeita_retry_after():
    """429 com Retry-After: o tempo de espera vem do header, não do backoff."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "rate limited"},
        status=429,
        headers={"Retry-After": "2.5"},
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client(backoff_base=0.01)
    with patch("notion_starter.client.time.sleep") as mock_sleep:
        client.get_database("db1")
        mock_sleep.assert_called_once_with(2.5)


@responses.activate
def test_retry_429_esgota_retries():
    """429 em todas as tentativas → levanta NotionHTTPError(429)."""

    for _ in range(3):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"message": "rate limited"},
            status=429,
        )
    client = criar_client(max_retries=2)
    with pytest.raises(NotionHTTPError) as exc_info:
        client.get_database("db1")
    assert exc_info.value.status_code == 429
    assert len(responses.calls) == 3


# -- Retry em erros transitórios ------------------------------------------


@responses.activate
def test_retry_500_em_atualizacao_idempotente():
    """PATCH idempotente pode ser repetido após erro transitório."""

    for _ in range(2):
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/pages/page1",
            json={"message": "internal error"},
            status=500,
        )
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/page1",
        json={"id": "page1"},
        status=200,
    )
    client = criar_client()
    data = client.atualizar_pagina("page1", {"Nome": {"title": []}})
    assert data["id"] == "page1"
    assert len(responses.calls) == 3


@responses.activate
def test_retry_502_esgota_retries():
    """502 em todas as tentativas → levanta NotionHTTPError(502)."""

    for _ in range(3):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"message": "bad gateway"},
            status=502,
        )
    client = criar_client(max_retries=2)
    with pytest.raises(NotionHTTPError) as exc_info:
        client.get_database("db1")
    assert exc_info.value.status_code == 502


@responses.activate
def test_retry_503_sucesso():
    """503 na primeira, 200 na segunda."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "unavailable"},
        status=503,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client()
    assert client.get_database("db1")["id"] == "db1"


@responses.activate
def test_retry_529_respeita_retry_after():
    """529 é sobrecarga temporária e segue o Retry-After do Notion."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "service overload"},
        status=529,
        headers={"Retry-After": "1"},
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client()
    with patch("notion_starter.client.time.sleep") as mock_sleep:
        assert client.get_database("db1")["id"] == "db1"
        mock_sleep.assert_called_once_with(1.0)


@responses.activate
def test_retry_409_em_operacao_idempotente():
    """409 documentado como transitório é repetido em operação idempotente."""

    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/page1",
        json={"message": "conflict"},
        status=409,
    )
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/page1",
        json={"id": "page1"},
        status=200,
    )
    client = criar_client()
    assert client.arquivar_pagina("page1")["id"] == "page1"
    assert len(responses.calls) == 2


# -- Escritas não idempotentes não são repetidas --------------------------


@responses.activate
def test_criar_pagina_nao_retenta_erro_500():
    """Criação falha sem retry para não duplicar página após resposta perdida."""

    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"message": "internal error"},
        status=500,
    )
    client = criar_client()
    with pytest.raises(NotionHTTPError) as exc_info:
        client.criar_pagina("db1", {"Nome": {"title": []}})
    assert exc_info.value.status_code == 500
    assert len(responses.calls) == 1


@responses.activate
def test_criar_pagina_retenta_rate_limit_429():
    """429 confirma rejeição por limite e pode repetir a criação após espera."""

    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"message": "rate limited"},
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"id": "page1"},
        status=200,
    )
    client = criar_client()
    assert client.criar_pagina("db1", {"Nome": {"title": []}})["id"] == "page1"
    assert len(responses.calls) == 2


@responses.activate
def test_criar_database_nao_retenta_falha_de_rede():
    """Falha de rede em criação não é repetida sem garantia de idempotência."""

    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases",
        body=requests.exceptions.ConnectionError("resposta perdida"),
    )
    client = criar_client()
    with pytest.raises(NotionConnectionError):
        client.criar_database("page1", "Projetos", {"Nome": {"title": {}}})
    assert len(responses.calls) == 1


@responses.activate
def test_consulta_post_idempotente_continua_com_retry():
    """POST usado apenas para consulta mantém retry por ser semanticamente seguro."""

    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db1/query",
        json={"message": "bad gateway"},
        status=502,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db1/query",
        json={"results": [{"id": "page1"}], "has_more": False},
        status=200,
    )
    client = criar_client()
    assert client.consultar_database("db1") == [{"id": "page1"}]
    assert len(responses.calls) == 2


# -- Sem retry em 4xx (exceto 429) ----------------------------------------


@responses.activate
def test_404_nao_retenta():
    """404 não é retentável — levanta imediatamente."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "not found"},
        status=404,
    )
    client = criar_client()
    with pytest.raises(NotionHTTPError) as exc_info:
        client.get_database("db1")
    assert exc_info.value.status_code == 404
    assert len(responses.calls) == 1


@responses.activate
def test_400_nao_retenta():
    """400 não é retentável — levanta imediatamente."""

    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json={"message": "bad request"},
        status=400,
    )
    client = criar_client()
    with pytest.raises(NotionHTTPError) as exc_info:
        client.criar_pagina("db1", {})
    assert exc_info.value.status_code == 400
    assert len(responses.calls) == 1


# -- Retry em falha de rede -----------------------------------------------


@responses.activate
def test_retry_conexao_sucesso_na_segunda():
    """Falha de rede na primeira, sucesso na segunda."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        body=requests.exceptions.ConnectionError("rede caiu"),
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client()
    data = client.get_database("db1")
    assert data["id"] == "db1"
    assert len(responses.calls) == 2


@responses.activate
def test_retry_conexao_esgota_retries():
    """Falha de rede em todas as tentativas → NotionConnectionError."""

    for _ in range(3):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            body=requests.exceptions.ConnectionError("rede caiu"),
        )
    client = criar_client(max_retries=2)
    with pytest.raises(NotionConnectionError):
        client.get_database("db1")
    assert len(responses.calls) == 3


# -- Backoff exponencial ---------------------------------------------------


@responses.activate
def test_backoff_exponencial_sem_retry_after():
    """Verifica que o backoff é exponencial: base * 2^tentativa."""

    for _ in range(3):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"message": "error"},
            status=500,
        )
    client = criar_client(max_retries=2, backoff_base=1.0)
    with patch("notion_starter.client.time.sleep") as mock_sleep:
        try:
            client.get_database("db1")
        except NotionHTTPError:
            pass
        assert mock_sleep.call_count == 2
        # tentativa 0: 1.0 * 2^0 = 1.0
        # tentativa 1: 1.0 * 2^1 = 2.0
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)


@responses.activate
def test_retry_after_header_invalido_usa_backoff():
    """Retry-After com valor não numérico → cai no backoff exponencial."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "rate limited"},
        status=429,
        headers={"Retry-After": "invalid"},
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client(backoff_base=0.5)
    with patch("notion_starter.client.time.sleep") as mock_sleep:
        client.get_database("db1")
        # Retry-After inválido → backoff: 0.5 * 2^0 = 0.5
        mock_sleep.assert_called_once_with(0.5)


# -- max_retries=0 desabilita retry ----------------------------------------


@responses.activate
def test_sem_retry_quando_max_retries_zero():
    """Com max_retries=0, 429 levanta imediatamente."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"message": "rate limited"},
        status=429,
    )
    client = criar_client(max_retries=0)
    with pytest.raises(NotionHTTPError) as exc_info:
        client.get_database("db1")
    assert exc_info.value.status_code == 429
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    ("parametro", "valor"),
    [
        ("max_retries", -1),
        ("backoff_base", -0.1),
        ("cache_ttl", -1),
    ],
)
def test_configuracao_negativa_e_rejeitada(parametro, valor):
    """Parâmetros operacionais negativos falham cedo e com erro claro."""

    with pytest.raises(ValueError):
        NotionClient(token=TOKEN, **{parametro: valor})


# -- Cache de schema (get_database) ----------------------------------------


@responses.activate
def test_cache_retorna_sem_chamada_extra():
    """Segunda chamada ao mesmo database usa cache, sem ir à rede."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "properties": {"Nome": {}}},
        status=200,
    )
    client = criar_client(cache_ttl=300)
    primeiro = client.get_database("db1")
    segundo = client.get_database("db1")
    assert primeiro == segundo
    assert len(responses.calls) == 1


@responses.activate
def test_cache_expira_apos_ttl():
    """Após TTL expirar, get_database vai à rede de novo."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "v": 1},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "v": 2},
        status=200,
    )
    client = criar_client(cache_ttl=10)
    with patch(
        "notion_starter.client.time.monotonic",
        side_effect=[100.0, 111.0, 111.0],
    ):
        client.get_database("db1")
        segundo = client.get_database("db1")
    assert segundo["v"] == 2
    assert len(responses.calls) == 2


@responses.activate
def test_cache_desabilitado_com_ttl_zero():
    """cache_ttl=0 desabilita o cache — cada chamada vai à rede."""

    for _ in range(2):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"id": "db1"},
            status=200,
        )
    client = criar_client(cache_ttl=0)
    client.get_database("db1")
    client.get_database("db1")
    assert len(responses.calls) == 2


@responses.activate
def test_invalidar_cache_especifico():
    """invalidar_cache(id) remove só aquele database do cache."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "atualizado": True},
        status=200,
    )
    client = criar_client()
    client.get_database("db1")
    client.invalidar_cache("db1")
    segundo = client.get_database("db1")
    assert segundo.get("atualizado") is True
    assert len(responses.calls) == 2


@responses.activate
def test_invalidar_cache_total():
    """invalidar_cache() sem argumento limpa todo o cache."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    client = criar_client()
    client.get_database("db1")
    client.invalidar_cache()
    client.get_database("db1")
    assert len(responses.calls) == 2


@responses.activate
def test_cache_nao_e_corrompido_por_mutacao_do_retorno():
    """Quem recebe o dict pode alterá-lo sem contaminar o valor em cache."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1", "properties": {"Nome": {"type": "title"}}},
        status=200,
    )
    client = criar_client()
    primeiro = client.get_database("db1")
    primeiro["properties"]["Nome"]["type"] = "mutado"
    segundo = client.get_database("db1")
    assert segundo["properties"]["Nome"]["type"] == "title"
    segundo["properties"]["Nome"]["type"] = "mutado-novamente"
    terceiro = client.get_database("db1")
    assert terceiro["properties"]["Nome"]["type"] == "title"
    assert len(responses.calls) == 1


def test_invalidar_cache_rejeita_id_vazio():
    """Invalidação específica usa a mesma validação dos demais métodos."""

    client = criar_client()
    with pytest.raises(
        NotionConfigurationError,
        match="database_id não pode estar vazio",
    ):
        client.invalidar_cache("   ")


# -- Databases diferentes não colidem no cache ----------------------------


@responses.activate
def test_cache_por_database_id():
    """Cada database tem sua entrada no cache."""

    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db1",
        json={"id": "db1"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/db2",
        json={"id": "db2"},
        status=200,
    )
    client = criar_client()
    d1 = client.get_database("db1")
    d2 = client.get_database("db2")
    assert d1["id"] == "db1"
    assert d2["id"] == "db2"
    # Cache hit — sem chamadas extras
    client.get_database("db1")
    client.get_database("db2")
    assert len(responses.calls) == 2
