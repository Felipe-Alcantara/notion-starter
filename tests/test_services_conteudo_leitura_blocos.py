"""Ler e apagar um bloco sabendo o que ele é.

``blocos`` jogava fora os carimbos que a API já devolve e cortava o texto em
100 caracteres; não havia como ler UM bloco pelo ID; e ``apagar-bloco`` mandava
uma subpágina inteira para a lixeira respondendo igual a um parágrafo.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.exceptions import ExclusaoArriscadaError, NotionSyncError
from notion_starter.services import conteudo as svc

CARIMBOS = {
    "created_time": "2026-09-25T23:01:00.000Z",
    "last_edited_time": "2026-09-25T23:02:00.000Z",
    "created_by": {"object": "user", "id": "u-criou"},
    "last_edited_by": {"object": "user", "id": "u-editou"},
    "in_trash": False,
}


class Cliente:
    def __init__(self, blocos: dict[str, dict[str, Any]], filhos: dict[str, list] | None = None):
        self.blocos = blocos
        self.filhos = filhos or {}
        self.lidos: list[str] = []
        self.excluidos: list[str] = []

    def obter_bloco(self, block_id):
        return dict(self.blocos[block_id])

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.lidos.append(block_id)
        return [dict(b) for b in self.filhos.get(block_id, [])]

    def excluir_bloco(self, block_id):
        self.excluidos.append(block_id)
        return {"id": block_id, "in_trash": True}


def _paragrafo(id_: str, texto: str, **extra) -> dict[str, Any]:
    return {
        "id": id_,
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": texto}]},
        **extra,
    }


def test_listar_blocos_sem_flags_mantem_o_formato_de_sempre():
    cliente = Cliente({}, {"pg": [_paragrafo("b1", "oi", **CARIMBOS)]})

    assert svc.listar_blocos("pg", cliente=cliente) == [
        {"id": "b1", "tipo": "paragraph", "preview": "oi"}
    ]


def test_listar_blocos_com_metadados_e_texto_completo():
    longo = "x" * 500
    cliente = Cliente({}, {"pg": [_paragrafo("b1", longo, has_children=True, **CARIMBOS)]})

    (bloco,) = svc.listar_blocos("pg", metadados=True, completo=True, cliente=cliente)

    assert bloco["tem_filhos"] is True
    assert bloco["criado_em"] == "2026-09-25T23:01:00.000Z"
    assert bloco["editado_por"] == "u-editou"
    assert bloco["na_lixeira"] is False
    assert bloco["markdown"] == longo
    assert len(bloco["preview"]) <= 100


def test_listar_blocos_com_metadados_tolera_bloco_sem_carimbos():
    cliente = Cliente({}, {"pg": [_paragrafo("b1", "oi")]})

    (bloco,) = svc.listar_blocos("pg", metadados=True, cliente=cliente)

    assert bloco["criado_em"] is None and bloco["criado_por"] is None


def test_ler_bloco_traz_filhos_pai_e_carimbos():
    toggle = {
        "id": "t1",
        "type": "toggle",
        "has_children": True,
        "toggle": {"rich_text": [{"plain_text": "Detalhes"}]},
        "parent": {"type": "page_id", "page_id": "pg"},
        **CARIMBOS,
    }
    cliente = Cliente({"t1": toggle}, {"t1": [_paragrafo("f1", "dentro")]})

    lido = svc.ler_bloco("t1", cliente=cliente)

    assert lido["tipo"] == "toggle"
    assert "dentro" in lido["markdown"]
    assert lido["pai"] == {"tipo": "page_id", "id": "pg"}
    assert lido["criado_por"] == "u-criou"


def test_ler_bloco_nao_desce_em_subpagina():
    subpagina = {
        "id": "sp",
        "type": "child_page",
        "has_children": True,
        "child_page": {"title": "Sub"},
        "parent": {"type": "workspace", "workspace": True},
    }
    cliente = Cliente({"sp": subpagina})

    lido = svc.ler_bloco("sp", cliente=cliente)

    assert cliente.lidos == []
    assert lido["pai"] == {"tipo": "workspace", "id": None}
    assert "Sub" in lido["markdown"]


def test_apagar_subpagina_sem_pedido_explicito_e_recusado():
    subpagina = {"id": "sp", "type": "child_page", "has_children": True,
                 "child_page": {"title": "Sandbox inteira"}}
    cliente = Cliente({"sp": subpagina})

    with pytest.raises(ExclusaoArriscadaError, match="Sandbox inteira") as erro:
        svc.apagar_bloco_verificado("sp", cliente=cliente)

    assert cliente.excluidos == []
    assert isinstance(erro.value, NotionSyncError) and isinstance(erro.value, ValueError)


def test_apagar_subpagina_com_pedido_explicito_diz_o_que_apagou():
    subpagina = {"id": "sp", "type": "child_page", "has_children": True,
                 "child_page": {"title": "Sandbox"}}
    cliente = Cliente({"sp": subpagina})

    resultado = svc.apagar_bloco_verificado("sp", forcar_tipos_arriscados=True, cliente=cliente)

    assert cliente.excluidos == ["sp"]
    assert (resultado.tipo, resultado.resumo, resultado.tem_filhos) == (
        "child_page",
        "Sandbox",
        True,
    )


def test_apagar_paragrafo_devolve_tipo_e_preview():
    cliente = Cliente({"b1": _paragrafo("b1", "texto do bloco")})

    resultado = svc.apagar_bloco_verificado("b1", cliente=cliente)

    assert (resultado.tipo, resultado.resumo) == ("paragraph", "texto do bloco")
