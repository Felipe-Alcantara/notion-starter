"""Ligar duas linhas por uma relação sem deixar a volta faltando.

Uma relação ``single_property`` do Notion parece bidirecional na interface, mas
pela API grava só o lado escrito. Uma malha de tarefas ligadas escrita de um
lado só fica pela metade — e o buraco só aparece quando alguém abre a página do
outro lado e não acha o caminho de volta.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.services.relacoes import relacionar

DATABASE = "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
OUTRO_DATABASE = "38e91f95-497e-818b-ab08-ff19918d6c7c"


class ClienteFalso:
    """Duas linhas do mesmo database, com uma coluna de relação configurável."""

    def __init__(
        self,
        *,
        tipo: str = "single_property",
        alvo: str = DATABASE,
        ligados: dict[str, list[str]] | None = None,
        coluna: str = "Relacionadas",
    ) -> None:
        self.tipo = tipo
        self.alvo = alvo
        self.coluna = coluna
        self.ligados = ligados or {}
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def obter_pagina(self, page_id: str) -> dict[str, Any]:
        relacao = [{"id": item} for item in self.ligados.get(page_id, [])]
        return {
            "id": page_id,
            "parent": {"type": "database_id", "database_id": DATABASE},
            "properties": {
                self.coluna: {"type": "relation", "relation": relacao},
                "Nome": {"type": "title", "title": []},
            },
        }

    def get_database(self, database_id: str) -> dict[str, Any]:
        return {
            "id": DATABASE,
            "properties": {
                self.coluna: {
                    "type": "relation",
                    "relation": {"database_id": self.alvo, "type": self.tipo},
                }
            },
        }

    def atualizar_pagina(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.patches.append((page_id, payload))
        ids = [item["id"] for item in payload[self.coluna]["relation"]]
        self.ligados[page_id] = ids
        return {"id": page_id}


def test_relacao_de_mao_unica_escreve_as_duas_pontas():
    cliente = ClienteFalso()

    resultado = relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    assert [page_id for page_id, _ in cliente.patches] == ["pagina-a", "pagina-b"]
    assert cliente.ligados["pagina-a"] == ["pagina-b"]
    assert cliente.ligados["pagina-b"] == ["pagina-a"]
    assert resultado["paginas_escritas"] == ["pagina-a", "pagina-b"]
    assert resultado["bidirecional"] is False


def test_relacao_bidirecional_escreve_so_um_lado():
    """Em dual_property o Notion espelha sozinho — escrever a volta é redundante."""

    cliente = ClienteFalso(tipo="dual_property", alvo=OUTRO_DATABASE)

    resultado = relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    assert [page_id for page_id, _ in cliente.patches] == ["pagina-a"]
    assert resultado["bidirecional"] is True


def test_mao_unica_entre_databases_diferentes_nao_inventa_volta():
    """Não existe coluna de volta no outro database: escrever daria erro."""

    cliente = ClienteFalso(tipo="single_property", alvo=OUTRO_DATABASE)

    resultado = relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    assert [page_id for page_id, _ in cliente.patches] == ["pagina-a"]
    assert resultado["paginas_escritas"] == ["pagina-a"]


def test_operacao_e_idempotente():
    """Rodar de novo não duplica a ligação nem gasta requisição."""

    cliente = ClienteFalso()
    relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)
    cliente.patches.clear()

    resultado = relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    assert cliente.patches == []
    assert resultado["paginas_ja_no_estado"] == ["pagina-a", "pagina-b"]
    assert cliente.ligados["pagina-a"] == ["pagina-b"]


def test_ligacao_nova_preserva_as_que_ja_existiam():
    cliente = ClienteFalso(ligados={"pagina-a": ["antiga"]})

    relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    assert cliente.ligados["pagina-a"] == ["antiga", "pagina-b"]


def test_desfazer_remove_das_duas_pontas():
    cliente = ClienteFalso()
    relacionar("pagina-a", "pagina-b", "Relacionadas", cliente=cliente)

    resultado = relacionar(
        "pagina-a", "pagina-b", "Relacionadas", desfazer=True, cliente=cliente
    )

    assert cliente.ligados["pagina-a"] == []
    assert cliente.ligados["pagina-b"] == []
    assert resultado["acao"] == "desfeita"


def test_desfazer_o_que_nao_existe_nao_escreve():
    cliente = ClienteFalso()

    resultado = relacionar(
        "pagina-a", "pagina-b", "Relacionadas", desfazer=True, cliente=cliente
    )

    assert cliente.patches == []
    assert resultado["paginas_escritas"] == []


def test_id_com_e_sem_hifen_conta_como_a_mesma_pagina():
    """A API aceita as duas formas; comparar cru duplicaria a ligação."""

    com_hifen = "3bf91f95-497e-81c3-a67e-da4f60abaab9"
    sem_hifen = "3bf91f9549 7e81c3a67eda4f60abaab9".replace(" ", "")
    cliente = ClienteFalso(ligados={"pagina-a": [com_hifen]})

    resultado = relacionar("pagina-a", sem_hifen, "Relacionadas", cliente=cliente)

    assert "pagina-a" in resultado["paginas_ja_no_estado"]
    assert cliente.ligados["pagina-a"] == [com_hifen]


def test_coluna_inexistente_lista_as_relacoes_disponiveis():
    cliente = ClienteFalso()

    with pytest.raises(ValueError, match="Relacionadas"):
        relacionar("pagina-a", "pagina-b", "Não existe", cliente=cliente)


def test_coluna_que_nao_e_relacao_aponta_o_comando_certo():
    cliente = ClienteFalso()

    with pytest.raises(ValueError, match="editar-linha"):
        relacionar("pagina-a", "pagina-b", "Nome", cliente=cliente)
