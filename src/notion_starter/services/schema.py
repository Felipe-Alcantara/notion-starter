"""Caso de uso: garantir que uma coluna exista num database já criado.

Nenhuma ferramenta do ecossistema atualiza o schema de um database existente
de forma genérica — `criar-database` só define colunas na criação;
`editar-linha`/`importar-planilha` só escrevem em colunas que já existem. Este
módulo generaliza o padrão já usado internamente por
:func:`~notion_starter.services.inventario_github.garantir_coluna_hash` (que
adiciona só a coluna de hash do README) para qualquer coluna, em qualquer
database.
"""

from __future__ import annotations

from typing import Any

from notion_starter import NotionClient


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


def garantir_coluna(
    database_id: str,
    nome_coluna: str,
    definicao: dict[str, object],
    *,
    cliente: NotionClient | None = None,
) -> bool:
    """Garante que ``nome_coluna`` exista no schema do database, sem apagar nada.

    Usa o *data source* (modelo novo do Notion) quando o database expõe um;
    cai para o endpoint clássico de database caso contrário — mesma estratégia
    de :func:`~notion_starter.services.inventario_github.garantir_coluna_hash`.
    Não mexe em nada se a coluna já existe (idempotente).

    Args:
        database_id: ID do database a alterar.
        nome_coluna: Nome da propriedade/coluna a garantir.
        definicao: Definição de schema da API do Notion para o tipo desejado
            (ex.: ``{"select": {}}``, ``{"rich_text": {}}``).
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        ``True`` se a coluna foi criada agora, ``False`` se já existia.

    Raises:
        ValueError: Se ``database_id`` ou ``nome_coluna`` forem vazios.
    """

    database_id = (database_id or "").strip()
    nome_coluna = (nome_coluna or "").strip()
    if not database_id:
        raise ValueError("database_id é obrigatório.")
    if not nome_coluna:
        raise ValueError("nome_coluna é obrigatório.")

    cli = cliente or _cliente_padrao()
    nova: dict[str, Any] = {nome_coluna: definicao}

    fontes = cli.listar_data_sources(database_id)
    if fontes:
        data_source_id = str(fontes[0].get("id") or "")
        fonte = cli.get_data_source(data_source_id)
        if nome_coluna in fonte.get("properties", {}):
            return False
        cli.atualizar_data_source(data_source_id, propriedades=nova)
        return True

    database = cli.get_database(database_id)
    if nome_coluna in database.get("properties", {}):
        return False
    cli.atualizar_database(database_id, propriedades=nova)
    return True
