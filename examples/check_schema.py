"""Valida se um database Notion casa com um schema esperado antes de exportar.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/check_schema.py <DATABASE_ID>
"""

from __future__ import annotations

import sys

from notion_starter import NotionClient, comparar_schema

# Um schema mapeia cada nome de coluna para o tipo de propriedade Notion esperado.
SCHEMA_ESPERADO = {
    "Nome": "title",
    "Email": "email",
    "Perfil": "select",
    "Cadastro": "date",
}


def main(database_id: str) -> None:
    client = NotionClient()
    database = client.get_database(database_id)
    resultado = comparar_schema(database, SCHEMA_ESPERADO)

    for nome, tipo in resultado.ok:
        print(f"  [OK]     {nome:<20} ({tipo})")
    for nome, esperado, encontrado in resultado.tipo_errado:
        print(f"  [TIPO]   {nome:<20} esperado={esperado}, encontrado={encontrado}")
    for nome, tipo in resultado.faltando:
        print(f"  [FALTA]  {nome:<20} (tipo: {tipo})")

    if resultado.compativel:
        print("\nDatabase compatível — pode exportar.")
    else:
        print("\nDatabase NÃO compatível. Corrija as colunas acima.")
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python examples/check_schema.py <DATABASE_ID>", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1])
