"""Lista tudo que a integração consegue enxergar no workspace.

Usa ``NotionClient.buscar`` para percorrer todas as páginas e databases
compartilhados com a integração. Útil como primeiro diagnóstico: mostra a que a
integração tem acesso e o ID de cada item.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/listar_paginas.py
"""

from __future__ import annotations

from notion_starter import NotionClient, construir_inventario


def main() -> None:
    client = NotionClient()
    itens = client.buscar(buscar_todos=True)
    inventario = construir_inventario(itens)

    if not inventario.itens:
        print("Nada encontrado. A integração ainda não tem acesso a nenhuma página.")
        print("Compartilhe uma página com ela: ••• -> Conexões -> sua integração.")
        return

    paginas = [i for i in inventario.itens.values() if i.tipo == "page"]
    databases = [i for i in inventario.itens.values() if i.tipo == "database"]

    print(f"Visíveis: {len(paginas)} página(s), {len(databases)} database(s).\n")

    if databases:
        print("== DATABASES ==")
        for db in sorted(databases, key=lambda i: i.titulo.lower()):
            print(f"  [db]   {db.titulo:<35} id={db.id}")
        print()

    if paginas:
        print("== PÁGINAS ==")
        for pg in sorted(paginas, key=lambda i: i.titulo.lower()):
            print(f"  [page] {pg.titulo:<35} id={pg.id}")


if __name__ == "__main__":
    main()
