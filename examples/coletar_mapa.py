"""Coleta o mapa do workspace e salva como ``mapa.json``.

Varre todas as páginas e databases visíveis (``NotionClient.buscar``), reconstrói
a estrutura (``construir_inventario``) e conta as linhas de cada database — esse
último passo faz uma chamada de API por database, então é o trecho mais lento.

O resultado é um JSON "fonte da verdade", consumido depois por
``gerar_arvore_html.py`` (e por qualquer automação futura). Inclui IDs e títulos
reais do workspace; mantenha-o em repositório privado.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/coletar_mapa.py [caminho_saida.json]
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from notion_starter import NotionClient, construir_inventario
from notion_starter.exceptions import NotionSyncError

SAIDA_PADRAO = Path("mapa.json")


def _contar_linhas_databases(client: NotionClient, database_ids: list[str]) -> dict[str, int]:
    """Conta as linhas de cada database (uma chamada de API por database).

    Erros por database (ex.: sem permissão) não abortam a coleta: o database
    fica sem contagem (``-1``) e o restante segue.
    """

    contagem: dict[str, int] = {}
    total = len(database_ids)
    for i, db_id in enumerate(database_ids, start=1):
        try:
            linhas = client.consultar_database(db_id, buscar_todos=True)
            contagem[db_id] = len(linhas)
        except NotionSyncError as exc:
            print(f"  [aviso] database {db_id[:8]} não contado: {exc}", file=sys.stderr)
            contagem[db_id] = -1
        print(f"  contando databases... {i}/{total}", end="\r", file=sys.stderr)
    print(file=sys.stderr)
    return contagem


def main(saida: Path) -> None:
    client = NotionClient()

    print("Varrendo o workspace (/search)...", file=sys.stderr)
    itens = client.buscar(buscar_todos=True)
    inventario = construir_inventario(itens)

    print(
        f"Encontrados: {inventario.total_paginas} páginas, {inventario.total_databases} databases.",
        file=sys.stderr,
    )

    database_ids = [i.id for i in inventario.itens.values() if i.tipo == "database"]
    linhas_por_db = _contar_linhas_databases(client, database_ids)

    payload = {
        "total_paginas": inventario.total_paginas,
        "total_databases": inventario.total_databases,
        "itens": [asdict(item) for item in inventario.itens.values()],
        "linhas_por_database": linhas_por_db,
        "duplicatas": {
            titulo: [item.id for item in itens] for titulo, itens in inventario.duplicatas.items()
        },
        "orfaos": [item.id for item in inventario.orfaos],
    }

    saida.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapa salvo em {saida} ({len(payload['itens'])} itens).", file=sys.stderr)


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else SAIDA_PADRAO
    main(destino)
