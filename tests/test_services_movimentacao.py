"""Mover uma linha entre databases prevê o que acontece com as colunas.

Os casos seguem o que foi medido no workspace real em 2026-09-27: a coluna que
não existe no destino é criada lá; o ``select`` com opção inexistente perde o
valor; a relação é descartada.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.services.movimentacao import (
    MovimentoComPerdasError,
    classificar_colunas,
    mover_pagina,
    prever_movimento,
)

PAGINA = "pag-1"
DATABASE = "db-destino"
FONTE = "ds-destino"


def _propriedades() -> dict[str, Any]:
    return {
        "Nome": {"type": "title", "title": [{"plain_text": "Ideia de artigo"}]},
        "Tema/Pilar": {"type": "multi_select", "multi_select": [{"name": "IA"}]},
        "Etapa": {"type": "select", "select": {"name": "Rascunho"}},
        "Formato": {"type": "select", "select": {"name": "Artigo"}},
        "Projeto": {"type": "relation", "relation": [{"id": "proj-1"}]},
        "Criado em": {"type": "created_time", "created_time": "2026-09-01T10:00:00.000Z"},
        "Notas": {"type": "rich_text", "rich_text": []},
    }


def _schema_destino() -> dict[str, Any]:
    return {
        "Título": {"type": "title", "title": {}},
        "Etapa": {"type": "select", "select": {"options": [{"name": "Ideia"}]}},
        "Formato": {"type": "select", "select": {"options": [{"name": "Artigo"}]}},
        "Projeto": {"type": "relation", "relation": {"data_source_id": "outro"}},
        "Notas": {"type": "number", "number": {}},
    }


class ClienteFalso:
    """Uma página de database e um destino com uma fonte."""

    def __init__(self, propriedades: dict[str, Any] | None = None) -> None:
        self.propriedades = propriedades if propriedades is not None else _propriedades()
        self.movimentos: list[tuple[str, str, str]] = []

    def obter_pagina(self, page_id: str) -> dict[str, Any]:
        return {
            "id": page_id,
            "parent": {"type": "database_id", "database_id": "db-origem"},
            "properties": self.propriedades,
        }

    def resolver_data_source(self, database_id: str) -> str:
        assert database_id == DATABASE
        return FONTE

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        assert data_source_id == FONTE
        return {"id": FONTE, "properties": _schema_destino()}

    def mover_pagina(self, page_id: str, novo_pai_id: str, *, tipo_pai: str) -> dict[str, Any]:
        self.movimentos.append((page_id, novo_pai_id, tipo_pai))
        return {"id": page_id, "parent": {"type": "database_id", "database_id": DATABASE}}


def test_classificacao_segue_o_comportamento_medido():
    acrescentadas, perdidas, mantidas, calculadas = classificar_colunas(
        _propriedades(), _schema_destino()
    )

    assert [c.nome for c in acrescentadas] == ["Tema/Pilar"]
    assert {c.nome for c in perdidas} == {"Etapa", "Projeto"}
    motivo_etapa = next(c.motivo for c in perdidas if c.nome == "Etapa")
    assert "'Rascunho'" in motivo_etapa
    # Formato tem a opção no destino; Notas está vazia, então o tipo diferente
    # não custa nada.
    assert mantidas == ["Formato", "Notas"]
    assert calculadas == ["Criado em"]


def test_destino_pagina_perde_toda_coluna_preenchida():
    _, perdidas, mantidas, _ = classificar_colunas(_propriedades(), None)

    assert {c.nome for c in perdidas} == {"Tema/Pilar", "Etapa", "Formato", "Projeto"}
    assert mantidas == []


def test_previsao_le_a_pagina_e_o_schema_da_fonte():
    previsao = prever_movimento(PAGINA, DATABASE, tipo_pai="database_id", cliente=ClienteFalso())

    assert previsao.titulo == "Ideia de artigo"
    assert previsao.data_source_id == FONTE
    assert previsao.muda_schema_do_destino
    dados = previsao.para_dict()
    assert dados["colunas_acrescentadas_no_destino"][0]["nome"] == "Tema/Pilar"
    assert {c["nome"] for c in dados["valores_perdidos"]} == {"Etapa", "Projeto"}


def test_dry_run_nao_move():
    cliente = ClienteFalso()

    resultado = mover_pagina(
        PAGINA, DATABASE, tipo_pai="database_id", dry_run=True, cliente=cliente
    )

    assert resultado.movido is False
    assert cliente.movimentos == []


def test_perda_sem_aceite_recusa_antes_de_mover():
    cliente = ClienteFalso()

    with pytest.raises(MovimentoComPerdasError) as erro:
        mover_pagina(PAGINA, DATABASE, tipo_pai="database_id", cliente=cliente)

    assert cliente.movimentos == []
    assert {c.nome for c in erro.value.previsao.perdidas} == {"Etapa", "Projeto"}
    assert isinstance(erro.value, ValueError)


def test_com_aceite_move_para_a_fonte_ja_resolvida():
    cliente = ClienteFalso()

    resultado = mover_pagina(
        PAGINA, DATABASE, tipo_pai="database_id", aceitar_perdas=True, cliente=cliente
    )

    assert cliente.movimentos == [(PAGINA, FONTE, "data_source_id")]
    assert resultado.movido is True
    assert resultado.pai_novo == {"type": "database_id", "database_id": DATABASE}


def test_sem_perda_move_sem_pedir_aceite():
    so_compativeis = {
        "Nome": {"type": "title", "title": [{"plain_text": "Oi"}]},
        "Formato": {"type": "select", "select": {"name": "Artigo"}},
    }
    cliente = ClienteFalso(so_compativeis)

    resultado = mover_pagina(PAGINA, DATABASE, tipo_pai="database_id", cliente=cliente)

    assert resultado.movido and cliente.movimentos == [(PAGINA, FONTE, "data_source_id")]


def test_tipo_pai_desconhecido_recusa():
    with pytest.raises(ValueError):
        prever_movimento(PAGINA, DATABASE, tipo_pai="workspace", cliente=ClienteFalso())
