from __future__ import annotations

import pytest

from notion_starter.services import schema as svc


class ClienteFake:
    """NotionClient mínimo: um database, com ou sem data source."""

    def __init__(self, propriedades: dict, *, com_data_source: bool = True):
        self._propriedades = dict(propriedades)
        self._com_data_source = com_data_source
        self.atualizacoes_data_source: list[tuple[str, dict]] = []
        self.atualizacoes_database: list[tuple[str, dict]] = []

    def listar_data_sources(self, database_id):
        if not self._com_data_source:
            return []
        return [{"id": "ds1", "name": "Principal"}]

    def get_data_source(self, data_source_id):
        return {"properties": self._propriedades}

    def atualizar_data_source(self, data_source_id, *, propriedades):
        self.atualizacoes_data_source.append((data_source_id, propriedades))
        self._propriedades.update(propriedades)

    def get_database(self, database_id):
        return {"properties": self._propriedades}

    def atualizar_database(self, database_id, *, propriedades):
        self.atualizacoes_database.append((database_id, propriedades))
        self._propriedades.update(propriedades)


def test_garantir_coluna_adiciona_quando_falta_via_data_source():
    cliente = ClienteFake({"Nome": {"type": "title", "title": {}}})

    criada = svc.garantir_coluna(
        "db1", "Idioma", {"select": {}}, cliente=cliente
    )

    assert criada is True
    assert cliente.atualizacoes_data_source == [("ds1", {"Idioma": {"select": {}}})]
    assert cliente.atualizacoes_database == []


def test_garantir_coluna_nao_mexe_quando_ja_existe():
    cliente = ClienteFake(
        {"Nome": {"type": "title", "title": {}}, "Idioma": {"type": "select", "select": {}}}
    )

    criada = svc.garantir_coluna(
        "db1", "Idioma", {"select": {}}, cliente=cliente
    )

    assert criada is False
    assert cliente.atualizacoes_data_source == []
    assert cliente.atualizacoes_database == []


def test_garantir_coluna_usa_endpoint_classico_sem_data_source():
    cliente = ClienteFake({"Nome": {"type": "title", "title": {}}}, com_data_source=False)

    criada = svc.garantir_coluna(
        "db1", "Idioma", {"select": {}}, cliente=cliente
    )

    assert criada is True
    assert cliente.atualizacoes_database == [("db1", {"Idioma": {"select": {}}})]
    assert cliente.atualizacoes_data_source == []


def test_garantir_coluna_rejeita_nome_vazio():
    cliente = ClienteFake({})
    with pytest.raises(ValueError):
        svc.garantir_coluna("db1", "", {"select": {}}, cliente=cliente)
