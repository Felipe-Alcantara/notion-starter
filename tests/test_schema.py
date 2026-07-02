from __future__ import annotations

import pytest

from notion_starter import comparar_schema
from notion_starter.exceptions import NotionSchemaError

ESPERADO = {"Nome": "title", "Email": "email", "Cadastro": "date"}


def database_com(tipos: dict[str, str]) -> dict:
    return {"properties": {nome: {"type": t} for nome, t in tipos.items()}}


def test_schema_compativel():
    db = database_com({"Nome": "title", "Email": "email", "Cadastro": "date"})
    resultado = comparar_schema(db, ESPERADO)
    assert resultado.compativel
    assert len(resultado.ok) == 3
    resultado.levantar_se_incompativel()  # não deve levantar


def test_coluna_faltando():
    db = database_com({"Nome": "title", "Email": "email"})
    resultado = comparar_schema(db, ESPERADO)
    assert not resultado.compativel
    assert ("Cadastro", "date") in resultado.faltando


def test_tipo_errado():
    db = database_com({"Nome": "title", "Email": "rich_text", "Cadastro": "date"})
    resultado = comparar_schema(db, ESPERADO)
    assert ("Email", "email", "rich_text") in resultado.tipo_errado


def test_levantar_se_incompativel():
    db = database_com({"Nome": "title"})
    resultado = comparar_schema(db, ESPERADO)
    with pytest.raises(NotionSchemaError):
        resultado.levantar_se_incompativel()
