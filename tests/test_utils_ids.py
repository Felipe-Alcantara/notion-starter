"""IDs do Notion chegam em várias formas; todas precisam casar com a mesma página.

A própria resposta da API traz o ID **sem hífens** no campo ``url``; quem copia
dali (ou cola o link inteiro) e compara com a forma hifenizada recebia
"não encontrado".
"""

from __future__ import annotations

import pytest

from notion_starter.exceptions import IdNotionInvalidoError, NotionSyncError
from notion_starter.utils import chave_de_id, extrair_id, normalizar_id

CANONICO = "3e691f95-497e-816b-b57e-e8ae6be6d500"
SEM_HIFENS = "3e691f95497e816bb57ee8ae6be6d500"
BLOCO = "3e691f95497e811389e4c13e18c97bd3"
VIEW = "11111111222233334444555555555555"


@pytest.mark.parametrize(
    "valor",
    [
        CANONICO,
        SEM_HIFENS,
        SEM_HIFENS.upper(),
        f"  {CANONICO}  ",
        f"https://www.notion.so/Minha-tarefa-{SEM_HIFENS}",
        f"https://app.notion.com/p/Minha-tarefa-{SEM_HIFENS}",
        f"https://www.notion.so/meu-workspace/Titulo-{SEM_HIFENS}",
        f"https://time.notion.site/Titulo-{SEM_HIFENS}?pvs=4",
        f"https://www.notion.so/{SEM_HIFENS}",
    ],
)
def test_normalizar_id_aceita_uuid_e_links(valor):
    assert normalizar_id(valor) == CANONICO


def test_view_de_database_nunca_vira_o_id():
    """``?v=`` é o ID da view: pegar o último 32hex da URL inteira erraria."""

    url = f"https://www.notion.so/{SEM_HIFENS}?v={VIEW}"

    assert normalizar_id(url) == CANONICO


def test_pagina_aberta_em_painel_vence_o_caminho():
    url = f"https://www.notion.so/{VIEW}?v=abc&p={SEM_HIFENS}&pm=s"

    assert normalizar_id(url) == CANONICO


def test_ancora_de_bloco_so_vence_quando_pedido():
    url = f"https://www.notion.so/Pagina-{SEM_HIFENS}#{BLOCO}"

    assert normalizar_id(url) == CANONICO
    assert normalizar_id(url, preferir_ancora=True) == (
        "3e691f95-497e-8113-89e4-c13e18c97bd3"
    )


@pytest.mark.parametrize("valor", ["", "abc", "https://www.notion.so/sem-id", "p1"])
def test_valor_sem_id_e_recusado_com_mensagem_util(valor):
    with pytest.raises(IdNotionInvalidoError) as erro:
        normalizar_id(valor)

    assert "buscar" in str(erro.value)
    # Mantém compatibilidade com quem trata entrada inválida por ValueError.
    assert isinstance(erro.value, (NotionSyncError, ValueError))


def test_extrair_id_deixa_passar_o_que_nao_e_uuid():
    assert extrair_id(" p1 ") == "p1"
    assert extrair_id(SEM_HIFENS) == CANONICO


def test_chave_de_id_iguala_as_duas_formas():
    assert chave_de_id(CANONICO) == chave_de_id(SEM_HIFENS.upper())
