from __future__ import annotations

import json

import pytest

from notion_starter.services import reordenacao as svc


class ClienteFake:
    def __init__(self, blocos: list[dict]):
        self._blocos = blocos
        self.excluidos: list[str] = []
        self.anexados: list[tuple[str, list[dict], str | None]] = []
        self._proximo_id = 100

    def ler_blocos(self, block_id, buscar_todos=False):
        return self._blocos

    def excluir_bloco(self, block_id):
        self.excluidos.append(block_id)
        return {"id": block_id, "archived": True}

    def anexar_blocos(self, block_id, blocos, *, apos_bloco_id=None):
        self._proximo_id += 1
        novo_id = f"novo-{self._proximo_id}"
        self.anexados.append((block_id, blocos, apos_bloco_id))
        return {"results": [{"id": novo_id, **blocos[0]}]}


def _paragrafo(id_):
    return {
        "id": id_,
        "type": "paragraph",
        "object": "block",
        "created_time": "2026-01-01",
        "paragraph": {"rich_text": [{"plain_text": "oi"}]},
    }


def _child_page(id_):
    return {"id": id_, "type": "child_page", "child_page": {"title": "Estado atual"}}


def test_reordenar_bloco_apos_outro(tmp_path):
    cliente = ClienteFake([_paragrafo("p1"), _paragrafo("p2")])

    resultado = svc.reordenar_bloco(
        "pagina", "p1", apos_bloco_id="p2", diretorio_backup=tmp_path, cliente=cliente
    )

    assert cliente.excluidos == ["p1"]
    assert cliente.anexados[0][2] == "p2"
    assert resultado.tipo == "paragraph"
    assert resultado.id_mudou is True


def test_reordenar_bloco_para_o_inicio(tmp_path):
    cliente = ClienteFake([_paragrafo("p1")])

    resultado = svc.reordenar_bloco(
        "pagina", "p1", inicio=True, diretorio_backup=tmp_path, cliente=cliente
    )

    assert cliente.anexados[0][2] is None
    assert resultado.bloco_id_antigo == "p1"


def test_reordenar_bloco_grava_backup_antes_de_apagar(tmp_path):
    cliente = ClienteFake([_paragrafo("p1")])

    resultado = svc.reordenar_bloco(
        "pagina",
        "p1",
        apos_bloco_id=None,
        inicio=True,
        diretorio_backup=tmp_path,
        cliente=cliente,
    )

    conteudo = json.loads(open(resultado.backup_path, encoding="utf-8").read())
    assert conteudo["id"] == "p1"
    assert conteudo["type"] == "paragraph"


def test_reordenar_bloco_rejeita_child_page_sem_forcar():
    cliente = ClienteFake([_child_page("cp1")])

    with pytest.raises(svc.BlocoArriscadoError):
        svc.reordenar_bloco("pagina", "cp1", inicio=True, cliente=cliente)

    assert cliente.excluidos == []  # nada foi apagado


def test_reordenar_bloco_permite_child_page_com_forcar(tmp_path):
    cliente = ClienteFake([_child_page("cp1")])

    resultado = svc.reordenar_bloco(
        "pagina",
        "cp1",
        inicio=True,
        forcar_tipos_arriscados=True,
        diretorio_backup=tmp_path,
        cliente=cliente,
    )

    assert cliente.excluidos == ["cp1"]
    assert resultado.tipo == "child_page"


def test_reordenar_bloco_exige_exatamente_um_alvo():
    cliente = ClienteFake([_paragrafo("p1")])
    with pytest.raises(ValueError):
        svc.reordenar_bloco("pagina", "p1", cliente=cliente)
    with pytest.raises(ValueError):
        svc.reordenar_bloco(
            "pagina", "p1", apos_bloco_id="p2", inicio=True, cliente=cliente
        )


def test_reordenar_bloco_nao_encontrado():
    cliente = ClienteFake([_paragrafo("p1")])
    with pytest.raises(ValueError, match="não encontrado"):
        svc.reordenar_bloco("pagina", "inexistente", inicio=True, cliente=cliente)
