"""``listar_linhas`` devolvia só ``{"id", "titulo", "url"}`` por design — quem

precisava das propriedades completas de uma database inteira (para
classificar, auditar ou cruzar colunas) tinha que sair da ferramenta e chamar
``consultar_database``/``obter_pagina`` direto pelo client. O parâmetro
``propriedades`` fecha essa lacuna sem mudar o comportamento padrão.
"""

from __future__ import annotations

from typing import Any

from notion_starter.services.conteudo import listar_linhas


class ClienteFalso:
    """Cliente mínimo: um data source com páginas fixas."""

    def __init__(self, paginas: list[dict[str, Any]]) -> None:
        self._paginas = paginas

    def listar_data_sources(self, database_id: str) -> list[dict[str, Any]]:
        return [{"id": "ds1", "name": "Principal"}]

    def consultar_data_source(
        self, data_source_id: str, *, buscar_todos: bool = False
    ) -> list[dict[str, Any]]:
        return self._paginas


def _pagina(page_id: str, titulo: str, **propriedades_extra: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Tarefa": {
            "type": "title",
            "title": [{"type": "text", "text": {"content": titulo}, "plain_text": titulo}],
        }
    }
    props.update(propriedades_extra)
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "properties": props,
    }


def test_padrao_continua_so_id_titulo_url():
    cliente = ClienteFalso([_pagina("p1", "Uma tarefa")])

    linhas = listar_linhas("db1", cliente=cliente)

    assert linhas == [
        {"id": "p1", "titulo": "Uma tarefa", "url": "https://notion.so/p1"}
    ]


def test_completo_adiciona_propriedades_normalizadas():
    cliente = ClienteFalso(
        [
            _pagina(
                "p1",
                "Uma tarefa",
                Prioridade={"type": "select", "select": {"name": "Alta"}},
                Feita={"type": "checkbox", "checkbox": True},
            )
        ]
    )

    linhas = listar_linhas("db1", propriedades=True, cliente=cliente)

    assert linhas == [
        {
            "id": "p1",
            "titulo": "Uma tarefa",
            "url": "https://notion.so/p1",
            "propriedades": {
                "Tarefa": "Uma tarefa",
                "Prioridade": "Alta",
                "Feita": True,
            },
        }
    ]


def test_completo_com_varias_linhas():
    cliente = ClienteFalso(
        [_pagina("p1", "Primeira"), _pagina("p2", "Segunda")]
    )

    linhas = listar_linhas("db1", propriedades=True, cliente=cliente)

    assert [linha["id"] for linha in linhas] == ["p1", "p2"]
    assert all("propriedades" in linha for linha in linhas)


def test_sem_pedir_propriedades_a_chave_nao_aparece():
    cliente = ClienteFalso([_pagina("p1", "Uma tarefa")])

    linhas = listar_linhas("db1", cliente=cliente)

    assert "propriedades" not in linhas[0]
