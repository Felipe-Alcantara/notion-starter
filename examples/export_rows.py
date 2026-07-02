"""Exporta uma lista de dicts comuns para um database do Notion.

Mostra o fluxo típico, independente de framework:

1. Cria um ``NotionClient`` (token vindo da env var ``NOTION_TOKEN``).
2. Mapeia cada linha para propriedades do Notion com os helpers de ``properties``.
3. Cria uma página por linha.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/export_rows.py <DATABASE_ID>
"""

from __future__ import annotations

import sys

from notion_starter import NotionClient, configure_logging
from notion_starter import properties as p

# Troque por linhas vindas da sua própria fonte de dados (banco, CSV, API, ...).
LINHAS = [
    {
        "nome": "Ada Lovelace",
        "email": "ada@example.com",
        "perfil": "Engenharia",
        "cadastro": "2026-01-10",
    },
    {
        "nome": "Alan Turing",
        "email": "alan@example.com",
        "perfil": "Pesquisa",
        "cadastro": "2026-02-02",
    },
]


def linha_para_propriedades(linha: dict[str, str]) -> dict[str, dict]:
    """Mapeia uma única linha para valores de propriedade do Notion.

    As chaves devem casar com os nomes das colunas no seu database Notion.
    """

    return {
        "Nome": p.title(linha["nome"]),
        "Email": p.email(linha["email"]),
        "Perfil": p.select(linha["perfil"]),
        "Cadastro": p.date(linha["cadastro"]),
    }


def main(database_id: str) -> None:
    configure_logging()  # logging opcional em console para um script
    client = NotionClient()  # lê NOTION_TOKEN do ambiente

    criadas = 0
    for linha in LINHAS:
        client.criar_pagina(database_id, linha_para_propriedades(linha))
        criadas += 1

    print(f"Concluído. {criadas} página(s) criada(s) no database {database_id}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python examples/export_rows.py <DATABASE_ID>", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1])
