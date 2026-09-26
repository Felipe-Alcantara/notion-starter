"""A sincronização de README não pode deixar cópias para trás.

``_localizar_subpaginas_readme`` lia só a primeira página de filhos (100 blocos):
numa página de projeto com mais de 100 blocos de topo o README antigo passava
despercebido e a sincronização criava outro a cada mudança.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from notion_starter import NotionClient
from notion_starter.services import inventario_github as svc


def _pagina_de_filhos(inicio: int, fim: int) -> list[dict[str, Any]]:
    return [
        {"id": f"p{i}", "type": "paragraph", "paragraph": {"rich_text": []}}
        for i in range(inicio, fim)
    ]


class ClientePaginado(NotionClient):
    """NotionClient real com a rede trocada por respostas paginadas como a API."""

    def __init__(self) -> None:
        super().__init__(token="ntn_teste", max_retries=0)
        readme_antigo = {"id": "readme-2", "type": "child_page", "child_page": {"title": "README"}}
        self.paginas = {
            None: {
                "results": [
                    {"id": "readme-1", "type": "child_page", "child_page": {"title": "README"}},
                    *_pagina_de_filhos(0, 99),
                ],
                "has_more": True,
                "next_cursor": "c2",
            },
            "c2": {"results": [*_pagina_de_filhos(99, 130), readme_antigo], "has_more": False},
        }
        self.excluidos: list[str] = []
        self.criadas: list[str] = []

    def _request_json(self, *, method, path, payload=None, idempotente, version=None):
        consulta = parse_qs(urlsplit(path).query)
        cursor = consulta.get("start_cursor", [None])[0]
        return self.paginas[cursor]

    def excluir_bloco(self, block_id: str) -> dict[str, Any]:
        self.excluidos.append(block_id)
        return {"id": block_id}

    def criar_subpagina(self, pagina_pai_id, titulo, *, blocos=None):
        self.criadas.append(titulo)
        return {"id": "novo"}


def test_localiza_readme_depois_do_100o_bloco():
    cliente = ClientePaginado()

    assert svc._localizar_subpaginas_readme(cliente, "pg") == ["readme-1", "readme-2"]


def test_sincronizar_apaga_todos_os_readmes_antes_de_criar_um():
    cliente = ClientePaginado()

    escrito = svc._sincronizar_readme(
        cliente, "pg", "# Projeto", hash_atual="velho", hash_novo="novo"
    )

    assert escrito is True
    assert cliente.excluidos == ["readme-1", "readme-2"]
    assert cliente.criadas == [svc.TITULO_README]
