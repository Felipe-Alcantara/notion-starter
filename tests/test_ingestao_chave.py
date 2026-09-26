"""Reimportar uma planilha editada não pode trocar um registro por outro.

A Origem ``arquivo:linha`` é a posição: medido com um database que faz merge
como a API, inserir "Aline" no topo e reimportar fez a página da Ana passar a
descrever a Aline (título, e-mail), a do Bruno virar a da Ana, e o Bruno ganhar
página nova.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.exceptions import NotionSyncError
from notion_starter.services.ingestao import (
    ChaveDePlanilhaInvalidaError,
    FontePlanilha,
    ingerir,
)


class DatabaseFake:
    """Páginas com propriedades; PATCH faz merge (o que não vem, fica)."""

    def __init__(self) -> None:
        self.paginas: dict[str, dict[str, Any]] = {}
        self.escritas: list[str] = []

    def get_database(self, database_id):
        return {
            "properties": {
                "Nome": {"type": "title"},
                "Origem": {"type": "rich_text"},
                "Email": {"type": "rich_text"},
            }
        }

    def _como_resposta(self, page_id: str) -> dict[str, Any]:
        props = self.paginas[page_id]
        titulo = props["Nome"]["title"][0]["text"]["content"]
        return {
            "id": page_id,
            "properties": {"Nome": {"type": "title", "title": [{"plain_text": titulo}]}},
        }

    def consultar_database(self, database_id, page_size=1, filtro=None):
        alvo = filtro["rich_text"]["equals"]
        for page_id, props in self.paginas.items():
            if props["Origem"]["rich_text"][0]["text"]["content"] == alvo:
                return [self._como_resposta(page_id)]
        return []

    def criar_pagina(self, database_id, props):
        page_id = f"pg{len(self.paginas) + 1}"
        self.paginas[page_id] = dict(props)
        self.escritas.append(f"criar {page_id}")
        return {"id": page_id}

    def atualizar_pagina(self, page_id, props):
        self.paginas[page_id].update(props)
        self.escritas.append(f"atualizar {page_id}")
        return {"id": page_id}

    def titulo(self, page_id: str) -> str:
        return self.paginas[page_id]["Nome"]["title"][0]["text"]["content"]

    def email(self, page_id: str) -> str:
        return self.paginas[page_id]["Email"]["rich_text"][0]["text"]["content"]

    def origem(self, page_id: str) -> str:
        return self.paginas[page_id]["Origem"]["rich_text"][0]["text"]["content"]


def _csv(tmp_path, linhas: list[tuple[str, str]], nome: str = "contatos.csv"):
    caminho = tmp_path / nome
    corpo = "\n".join(f"{n},{e}" for n, e in linhas)
    caminho.write_text(f"Nome,Email\n{corpo}\n", encoding="utf-8")
    return caminho


def _importar(db, caminho, **kwargs):
    return ingerir(FontePlanilha(caminho, **kwargs), client=db, database_id="db")


def test_sem_chave_linha_inserida_nao_sobrescreve_outro_registro(tmp_path):
    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "ana@x.com"), ("Bruno", "b@x.com")]))

    resultado = _importar(
        db, _csv(tmp_path, [("Aline", "aline@x.com"), ("Ana", "ana@x.com"), ("Bruno", "b@x.com")])
    )

    assert db.titulo("pg1") == "Ana" and db.email("pg1") == "ana@x.com"
    assert db.titulo("pg2") == "Bruno"
    assert len(resultado.conflitos) == 2
    assert "chave" in resultado.conflitos[0]
    assert resultado.atualizados == 0


def test_sem_chave_linha_removida_nao_sobrescreve(tmp_path):
    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "a"), ("Bruno", "b"), ("Carla", "c")]))

    _importar(db, _csv(tmp_path, [("Bruno", "b"), ("Carla", "c")]))

    assert [db.titulo(p) for p in ("pg1", "pg2", "pg3")] == ["Ana", "Bruno", "Carla"]


def test_com_chave_a_origem_segue_o_registro(tmp_path):
    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "ana@x.com"), ("Bruno", "b@x.com")]), chave="Email")

    resultado = _importar(
        db,
        _csv(tmp_path, [("Aline", "aline@x.com"), ("Ana", "ana@x.com"), ("Bruno", "b@x.com")]),
        chave="Email",
    )

    assert (resultado.criados, resultado.atualizados, resultado.conflitos) == (1, 2, [])
    assert db.titulo("pg1") == "Ana"
    assert db.origem("pg1") == "contatos.csv#Email=ana@x.com"
    assert db.titulo("pg3") == "Aline"


def test_com_chave_renomear_o_titulo_atualiza_a_pagina(tmp_path):
    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "ana@x.com")]), chave="Email")

    resultado = _importar(db, _csv(tmp_path, [("Ana Maria", "ana@x.com")]), chave="Email")

    assert resultado.atualizados == 1 and resultado.conflitos == []
    assert db.titulo("pg1") == "Ana Maria"


def test_primeira_importacao_com_chave_reaproveita_a_pagina_posicional(tmp_path):
    """Quem já importou por posição não pode ganhar uma duplicata de cada linha."""

    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "ana@x.com"), ("Bruno", "b@x.com")]))

    resultado = _importar(
        db, _csv(tmp_path, [("Ana", "ana@x.com"), ("Bruno", "b@x.com")]), chave="Email"
    )

    assert (resultado.criados, resultado.atualizados) == (0, 2)
    assert db.origem("pg1") == "contatos.csv#Email=ana@x.com"


@pytest.mark.parametrize(
    "linhas,trecho",
    [
        ([("Ana", "x@x.com"), ("Bia", "x@x.com")], "repete a linha 2"),
        ([("Ana", "a@x.com"), ("Bia", "")], "vazia"),
    ],
)
def test_chave_repetida_ou_vazia_recusa_antes_de_gravar(tmp_path, linhas, trecho):
    db = DatabaseFake()

    with pytest.raises(ChaveDePlanilhaInvalidaError, match=trecho) as erro:
        _importar(db, _csv(tmp_path, linhas), chave="Email")

    assert db.escritas == []
    assert isinstance(erro.value, NotionSyncError) and isinstance(erro.value, ValueError)


def test_coluna_chave_inexistente_e_recusada(tmp_path):
    with pytest.raises(ValueError, match="Coluna-chave 'CPF'"):
        list(FontePlanilha(_csv(tmp_path, [("Ana", "a")]), chave="CPF").coletar())


def test_duas_abas_do_mesmo_xlsx_nao_colidem(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    caminho = tmp_path / "dados.xlsx"
    pasta = openpyxl.Workbook()
    primeira = pasta.active
    primeira.title = "2025"
    primeira.append(["Nome", "Email"])
    primeira.append(["Ana", "a@x.com"])
    segunda = pasta.create_sheet("2026")
    segunda.append(["Nome", "Email"])
    segunda.append(["Ana", "a@x.com"])
    pasta.save(caminho)

    origens = {
        next(iter(FontePlanilha(caminho, aba=aba, chave="Email").coletar())).origem
        for aba in ("2025", "2026")
    }

    assert origens == {"dados.xlsx#2025#Email=a@x.com", "dados.xlsx#2026#Email=a@x.com"}


def test_simular_nao_grava_nada(tmp_path):
    db = DatabaseFake()
    _importar(db, _csv(tmp_path, [("Ana", "a")]))
    db.escritas.clear()

    resultado = ingerir(
        FontePlanilha(_csv(tmp_path, [("Ana", "a"), ("Bruno", "b")])),
        client=db,
        database_id="db",
        simular=True,
    )

    assert db.escritas == []
    assert (resultado.criados, resultado.atualizados, resultado.simulado) == (1, 1, True)
