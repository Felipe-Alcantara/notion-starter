from __future__ import annotations

import pytest

from notion_starter.services import estrutura_projeto as svc


class ClienteFake:
    """NotionClient mínimo: blocos por página e registro do que foi escrito."""

    def __init__(self, blocos_por_pagina: dict[str, list[dict]] | None = None):
        self._blocos = blocos_por_pagina or {}
        self.subpaginas_criadas: list[tuple[str, str]] = []
        self.databases_criados: list[tuple[str, str, dict]] = []
        self.blocos_anexados: list[tuple[str, list[dict]]] = []

    def ler_blocos(self, block_id, buscar_todos=False):
        return self._blocos.get(block_id, [])

    def criar_subpagina(self, pagina_pai_id, titulo, *, blocos=None):
        self.subpaginas_criadas.append((pagina_pai_id, titulo))
        return {"id": f"sub-{titulo}", "url": f"https://notion.so/{titulo}"}

    def criar_database(self, pagina_id, titulo, propriedades, **kwargs):
        self.databases_criados.append((pagina_id, titulo, propriedades))
        return {"id": f"db-{titulo}"}

    def anexar_blocos(self, page_id, blocos):
        self.blocos_anexados.append((page_id, blocos))
        return {"results": blocos}


def _bloco_pagina(id_, titulo):
    return {"id": id_, "type": "child_page", "child_page": {"title": titulo}}


def _bloco_database(id_, titulo):
    return {"id": id_, "type": "child_database", "child_database": {"title": titulo}}


def _bloco_heading(texto):
    return {
        "id": "h1",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"plain_text": texto}]},
    }


# -- inspecionar_estrutura --------------------------------------------------


def test_inspecionar_estrutura_le_filhos_diretos():
    cliente = ClienteFake(
        {"raiz": [_bloco_pagina("p1", "README"), _bloco_database("d1", "Docs")]}
    )

    arvore = svc.inspecionar_estrutura("raiz", cliente=cliente)

    tipos = [(no.tipo, no.titulo) for no in arvore.filhos]
    assert tipos == [("child_page", "README"), ("child_database", "Docs")]


def test_inspecionar_estrutura_desce_em_subpaginas_ate_profundidade():
    cliente = ClienteFake(
        {
            "raiz": [_bloco_pagina("p1", "Nível 1")],
            "p1": [_bloco_pagina("p2", "Nível 2")],
            "p2": [_bloco_pagina("p3", "Nível 3 (não deve aparecer)")],
        }
    )

    arvore = svc.inspecionar_estrutura("raiz", profundidade=2, cliente=cliente)

    nivel1 = arvore.filhos[0]
    assert nivel1.titulo == "Nível 1"
    nivel2 = nivel1.filhos[0]
    assert nivel2.titulo == "Nível 2"
    assert nivel2.filhos == []  # profundidade 2 não desce no nível 3


def test_inspecionar_estrutura_rejeita_profundidade_invalida():
    with pytest.raises(ValueError):
        svc.inspecionar_estrutura("raiz", profundidade=0, cliente=ClienteFake())


def test_inspecionar_estrutura_rejeita_pagina_vazia():
    with pytest.raises(ValueError):
        svc.inspecionar_estrutura("", cliente=ClienteFake())


# -- clonar_estrutura_projeto -----------------------------------------------


def test_clonar_estrutura_projeto_recria_subpaginas_e_databases(monkeypatch):
    cliente = ClienteFake(
        {
            "ref": [
                _bloco_heading("Acompanhamento"),
                {"id": "div1", "type": "divider", "divider": {}},
                _bloco_pagina("p1", "Estado atual"),
                _bloco_database("d1", "Próximos passos"),
            ]
        }
    )
    monkeypatch.setattr(
        svc,
        "clonar_database",
        lambda database_id, **kwargs: {"id": f"clone-{database_id}"},
    )

    resumo = svc.clonar_estrutura_projeto("ref", "destino", cliente=cliente)

    assert resumo.subpaginas_criadas == ["Estado atual"]
    assert resumo.databases_clonados == ["Próximos passos"]
    assert cliente.subpaginas_criadas == [("destino", "Estado atual")]
    # heading + divider foram replicados como blocos simples no destino.
    tipos_anexados = [b["type"] for _, blocos in cliente.blocos_anexados for b in blocos]
    assert "heading_2" in tipos_anexados
    assert "divider" in tipos_anexados


def test_clonar_estrutura_projeto_registra_blocos_ignorados():
    cliente = ClienteFake({"ref": [{"id": "img1", "type": "image", "image": {}}]})

    resumo = svc.clonar_estrutura_projeto("ref", "destino", cliente=cliente)

    assert resumo.subpaginas_criadas == []
    assert resumo.databases_clonados == []
    assert resumo.ignorados == ["image"]


def test_clonar_estrutura_projeto_rejeita_ids_vazios():
    with pytest.raises(ValueError):
        svc.clonar_estrutura_projeto("", "destino", cliente=ClienteFake())
    with pytest.raises(ValueError):
        svc.clonar_estrutura_projeto("ref", "", cliente=ClienteFake())


# -- montar_estrutura_projeto ------------------------------------------------


def test_montar_estrutura_projeto_cria_o_padrao_completo():
    cliente = ClienteFake()

    resumo = svc.montar_estrutura_projeto("pagina", cliente=cliente)

    assert resumo.subpaginas_criadas == list(svc.SUBPAGINAS_ACOMPANHAMENTO)
    assert resumo.databases_criados == list(svc.DATABASES_PLANEJAMENTO)
    assert len(cliente.subpaginas_criadas) == 4
    assert len(cliente.databases_criados) == 2
    # Cada database criado tem título + Observações no schema mínimo.
    for _, _, propriedades in cliente.databases_criados:
        assert "Nome" in propriedades
        assert "Observações" in propriedades


def test_montar_estrutura_projeto_rejeita_pagina_vazia():
    with pytest.raises(ValueError):
        svc.montar_estrutura_projeto("", cliente=ClienteFake())
