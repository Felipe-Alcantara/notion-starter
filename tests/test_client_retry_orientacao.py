"""A política de retry segue o que a API manda fazer em cada erro.

https://developers.notion.com/reference/request-limits: uma escrita pode ser
salva e ainda devolver 503, com ``additional_data.retry_guidance`` pedindo para
não repetir; 429 com ``public_api_request_blocked`` não se repete; e o backoff
leva jitter. O corpo oficial compacto já passa dos 500 caracteres que
``NotionHTTPError.body`` guarda, então os dados vêm do corpo inteiro.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import responses

from notion_starter import NotionClient
from notion_starter.client import deve_retentar
from notion_starter.constants import NOTION_BASE_URL
from notion_starter.exceptions import NotionEscritaSalvaError, NotionHTTPError

TOKEN = "ntn_test_token"
FILHO = "3e691f95-497e-8113-89e4-c13e18c97bd3"


def _cliente(jitter: float = 0.0) -> NotionClient:
    return NotionClient(token=TOKEN, max_retries=3, backoff_base=0.0, jitter=jitter)


def _corpo_503_salvo(**extra) -> dict:
    return {
        "object": "error",
        "status": 503,
        "code": "service_unavailable",
        "message": "The change was saved, but the response could not be built in time. " * 3,
        "request_id": "00000000-0000-0000-0000-000000000000",
        "additional_data": {
            "retry_guidance": [
                "Read the object again to confirm the saved change.",
                "Do not repeat the write.",
            ],
            **extra,
        },
    }


@responses.activate
def test_503_salvo_numa_atualizacao_nao_e_repetido():
    """Antes: 4 PATCH seguidos mesmo com 'Do not repeat the write'."""

    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/blocks/b1", json=_corpo_503_salvo(), status=503
    )

    with pytest.raises(NotionEscritaSalvaError, match="NÃO repita"):
        _cliente().atualizar_bloco("b1", {"paragraph": {"rich_text": []}})

    assert len(responses.calls) == 1


@responses.activate
def test_503_salvo_no_append_expoe_os_filhos_criados():
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/blocks/pg/children",
        json=_corpo_503_salvo(committed_child_ids=[FILHO]),
        status=503,
    )

    with pytest.raises(NotionEscritaSalvaError) as erro:
        _cliente().anexar_blocos("pg", [{"type": "paragraph", "paragraph": {"rich_text": []}}])

    assert erro.value.filhos_criados == [FILHO]
    assert FILHO in str(erro.value)
    assert len(erro.value.body) <= 500  # o corpo exibido continua truncado


@responses.activate
def test_503_sem_orientacao_numa_escrita_idempotente_nao_e_repetido():
    responses.add(
        responses.PATCH, f"{NOTION_BASE_URL}/blocks/b1", json={"code": "x"}, status=503
    )

    with pytest.raises(NotionHTTPError) as erro:
        _cliente().atualizar_bloco("b1", {"paragraph": {"rich_text": []}})

    assert not isinstance(erro.value, NotionEscritaSalvaError)
    assert len(responses.calls) == 1


@responses.activate
def test_503_em_leitura_continua_sendo_repetido():
    url = f"{NOTION_BASE_URL}/blocks/b1"
    responses.add(responses.GET, url, json={"code": "service_unavailable"}, status=503)
    responses.add(responses.GET, url, json={"id": "b1"})

    assert _cliente().obter_bloco("b1")["id"] == "b1"


@responses.activate
def test_429_bloqueado_nao_e_repetido():
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/blocks/b1",
        json={
            "code": "rate_limited",
            "additional_data": {"rate_limit_reason": "public_api_request_blocked"},
        },
        status=429,
    )

    with pytest.raises(NotionHTTPError) as erro:
        _cliente().obter_bloco("b1")

    assert len(responses.calls) == 1
    assert erro.value.codigo == "rate_limited"
    assert erro.value.dados_adicionais["rate_limit_reason"] == "public_api_request_blocked"


def test_regra_de_retentativa_documentada():
    base = {"path": "/blocks/b1", "dados_adicionais": {}}
    assert deve_retentar(metodo="GET", status_code=429, idempotente=True, **base)
    assert deve_retentar(metodo="POST", status_code=529, idempotente=False, **base)
    assert not deve_retentar(metodo="POST", status_code=500, idempotente=False, **base)
    assert deve_retentar(metodo="PATCH", status_code=500, idempotente=True, **base)
    assert not deve_retentar(metodo="PATCH", status_code=503, idempotente=True, **base)
    assert deve_retentar(
        metodo="POST", path="/databases/x/query", status_code=503, idempotente=True,
        dados_adicionais={},
    )
    assert not deve_retentar(metodo="GET", status_code=404, idempotente=True, **base)


@responses.activate
def test_jitter_soma_ate_a_fracao_configurada():
    url = f"{NOTION_BASE_URL}/blocks/b1"
    responses.add(responses.GET, url, json={}, status=429, headers={"Retry-After": "2"})
    responses.add(responses.GET, url, json={"id": "b1"})

    with patch("notion_starter.client.time.sleep") as dormir, patch(
        "notion_starter.client.random.uniform", return_value=0.3
    ) as sorteio:
        _cliente(jitter=0.25).obter_bloco("b1")

    sorteio.assert_called_once_with(0, 0.5)
    dormir.assert_called_once_with(2.3)


def test_backoff_exponencial_tem_teto():
    cliente = NotionClient(token=TOKEN, backoff_base=1.0, jitter=0.0)
    assert cliente._espera_exponencial(10) == 30.0


def test_upload_nao_repete_503_salvo():
    class Resposta:
        status_code = 503
        headers: dict = {}
        text = '{"additional_data": {"retry_guidance": ["Do not repeat the write."]}}'

    cliente = _cliente()
    with patch("notion_starter.client.requests.post", return_value=Resposta()) as enviar:
        with pytest.raises(NotionEscritaSalvaError):
            cliente._enviar_multipart(path="/file_uploads/u1/send", files={})
    assert enviar.call_count == 1
