"""Exemplo end-to-end: de um CSV para um database do Notion.

Mostra o fluxo completo que um projeto sobre o Notion costuma precisar — é o
ponto de partida típico deste boilerplate:

1. Lê linhas de um arquivo CSV (sua fonte de dados).
2. Valida que o database de destino tem as colunas esperadas (``comparar_schema``).
3. Mapeia cada linha para propriedades do Notion com os helpers de ``properties``.
4. Cria uma página por linha.

Adapte ``SCHEMA_ESPERADO`` e ``linha_para_propriedades`` ao seu próprio CSV e
database — é exatamente esse o trecho que você reescreve ao usar o boilerplate.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/sync_from_csv.py <DATABASE_ID> <CAMINHO_DO_CSV>

Formato de CSV esperado (cabeçalho na primeira linha):
    nome,email,perfil,cadastro
    Ada Lovelace,ada@example.com,Engenharia,2026-01-10
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from notion_starter import NotionClient, comparar_schema
from notion_starter import properties as p

# Colunas que o database de destino precisa ter, e o tipo Notion de cada uma.
# Ajuste ao seu database.
SCHEMA_ESPERADO = {
    "Nome": "title",
    "Email": "email",
    "Perfil": "select",
    "Cadastro": "date",
}


def linha_para_propriedades(linha: dict[str, str]) -> dict[str, dict]:
    """Mapeia uma linha do CSV para valores de propriedade do Notion.

    As chaves do retorno devem casar com os nomes das colunas no database.
    Adapte este mapeamento ao seu CSV e ao seu schema.
    """

    return {
        "Nome": p.title(linha["nome"]),
        "Email": p.email(linha["email"]),
        "Perfil": p.select(linha["perfil"]),
        "Cadastro": p.date(linha["cadastro"]),
    }


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    """Lê o CSV em uma lista de dicts (uma entrada por linha)."""

    with caminho.open(encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def main(database_id: str, caminho_csv: str) -> None:
    caminho = Path(caminho_csv)
    if not caminho.is_file():
        print(f"CSV não encontrado: {caminho}", file=sys.stderr)
        raise SystemExit(1)

    client = NotionClient()  # lê NOTION_TOKEN do ambiente

    # 1. Falha cedo se o database não tiver as colunas esperadas.
    database = client.get_database(database_id)
    resultado = comparar_schema(database, SCHEMA_ESPERADO)
    if not resultado.compativel:
        print("Database incompatível com o schema esperado:", file=sys.stderr)
        for nome, esperado, encontrado in resultado.tipo_errado:
            print(
                f"  [TIPO]  {nome}: esperado={esperado}, encontrado={encontrado}",
                file=sys.stderr,
            )
        for nome, tipo in resultado.faltando:
            print(f"  [FALTA] {nome} (tipo: {tipo})", file=sys.stderr)
        raise SystemExit(1)

    # 2. Cria uma página por linha do CSV.
    linhas = ler_csv(caminho)
    criadas = 0
    for linha in linhas:
        client.criar_pagina(database_id, linha_para_propriedades(linha))
        criadas += 1

    print(f"Concluído. {criadas} página(s) criada(s) no database {database_id}.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Uso: python examples/sync_from_csv.py <DATABASE_ID> <CAMINHO_DO_CSV>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
