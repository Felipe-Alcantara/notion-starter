"""Clonagem de databases do Notion preservando o schema completo.

Copiar um database "na mão" pela API tem armadilhas reais (descobertas em uso):

* No modelo novo, as colunas vivem no *data source*, não no database — criar o
  database só com ``title`` deixa as outras propriedades de fora.
* ``status`` não pode ser criado direto na criação do database; precisa de um
  ``PATCH`` no data source, e suas opções têm que ser recriadas.
* ``relation`` que aponta para o **próprio** database de origem deve virar uma
  auto-relação do clone (não um vínculo de volta à origem); ``relation`` para
  **outros** databases é preservada apontando para o mesmo alvo.
* Propriedades automáticas (``created_time``, ``created_by``, ``last_edited_time``,
  ``formula``, ``rollup``) não recebem valor ao copiar linhas.

Este módulo encapsula tudo isso atrás de :func:`clonar_database`, sem vazar
formato cru do Notion para as bordas (CLI/MCP/API).
"""

from __future__ import annotations

from typing import Any

from notion_starter import NotionClient

# Tipos de propriedade gerados pelo Notion: existem no schema mas não aceitam
# valor na criação/cópia de uma linha.
_PROPRIEDADES_AUTOMATICAS = frozenset(
    {
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "formula",
        "rollup",
        "unique_id",
        "button",
    }
)


def _cliente_padrao() -> NotionClient:
    """Cria o cliente real a partir da configuração do projeto.

    Importado tardiamente para manter o módulo testável sem tocar a config.
    """

    from integrations.notion import criar_cliente

    return criar_cliente()


def _fonte_unica(cliente: NotionClient, database_id: str) -> dict[str, Any]:
    """Resolve o *data source* único de um database (erro se 0 ou vários)."""

    fontes = cliente.listar_data_sources(database_id)
    if not fontes:
        raise ValueError(
            "Database sem data source acessível à integração — compartilhe-o "
            "no Notion ou confira o ID."
        )
    if len(fontes) > 1:
        raise ValueError(
            "Database com múltiplos data sources ainda não é suportado pela "
            "clonagem automática."
        )
    return fontes[0]


def _schema_para_clone(
    propriedades: dict[str, Any],
    *,
    fonte_origem_id: str,
    fonte_destino_id: str,
    relacoes: str,
) -> dict[str, dict[str, object]]:
    """Traduz o schema da origem em payload de criação de propriedades.

    Args:
        propriedades: ``properties`` do data source de origem.
        fonte_origem_id: data source de origem (para detectar auto-relação).
        fonte_destino_id: data source do clone (alvo das auto-relações).
        relacoes: política de relações — ``"auto-novo"`` (auto-relações apontam
            para o clone, externas preservam o alvo) ou ``"texto"`` (toda
            relação vira ``rich_text``, sem vínculo).

    Returns:
        Dicionário ``nome -> definição`` pronto para ``atualizar_data_source``.
        A propriedade ``title`` é omitida (já existe no database recém-criado).
    """

    schema: dict[str, dict[str, object]] = {}
    for nome, definicao in propriedades.items():
        tipo = definicao.get("type")
        if tipo == "title":
            continue  # o database nasce com o título; não recriar.

        if tipo == "relation":
            schema[nome] = _clonar_relacao(
                definicao,
                fonte_origem_id=fonte_origem_id,
                fonte_destino_id=fonte_destino_id,
                relacoes=relacoes,
            )
        elif tipo in {"select", "multi_select"}:
            opcoes = definicao.get(tipo, {}).get("options", [])
            schema[nome] = {tipo: {"options": [{"name": o["name"]} for o in opcoes]}}
        elif tipo == "status":
            opcoes = definicao.get("status", {}).get("options", [])
            schema[nome] = {"status": {"options": [{"name": o["name"]} for o in opcoes]}}
        else:
            # Tipos simples (number, date, checkbox, url, email, phone, people,
            # files, rich_text, created_time, ...) clonam com a definição vazia.
            schema[nome] = {tipo: {}}
    return schema


def _clonar_relacao(
    definicao: dict[str, Any],
    *,
    fonte_origem_id: str,
    fonte_destino_id: str,
    relacoes: str,
) -> dict[str, object]:
    """Decide o alvo de uma propriedade ``relation`` ao clonar."""

    if relacoes == "texto":
        return {"rich_text": {}}

    rel = definicao.get("relation", {})
    alvo = rel.get("data_source_id") or rel.get("database_id")
    # Auto-relação: a origem aponta para si mesma -> o clone aponta para si.
    destino = fonte_destino_id if alvo == fonte_origem_id else alvo
    return {"relation": {"data_source_id": destino, "single_property": {}}}


def _texto_titulo(pagina: dict[str, Any]) -> tuple[str, str]:
    """Devolve ``(nome_da_propriedade_title, texto)`` de uma linha."""

    for nome, prop in pagina.get("properties", {}).items():
        if isinstance(prop, dict) and prop.get("type") == "title":
            texto = "".join(p.get("plain_text", "") for p in prop.get("title", []))
            return nome, texto
    return "", ""


def _valor_para_copia(prop: dict[str, Any]) -> dict[str, object] | None:
    """Extrai o valor copiável de uma propriedade de linha.

    Relações são preservadas (apontam para as mesmas páginas — vínculo externo)
    ou ignoradas quando o schema do clone as transformou em texto. Tipos
    automáticos retornam ``None`` (não recebem valor).
    """

    tipo = prop.get("type")
    if tipo in _PROPRIEDADES_AUTOMATICAS:
        return None
    valor = prop.get(tipo)
    if valor in (None, [], ""):
        return None
    if tipo == "relation":
        return {"relation": [{"id": r["id"]} for r in valor]}
    if tipo in {"select", "status"}:
        return {tipo: {"name": valor["name"]}}
    if tipo == "multi_select":
        return {"multi_select": [{"name": o["name"]} for o in valor]}
    if tipo == "title":
        return {"title": [{"type": "text", "text": {"content": _plano(valor)}}]}
    if tipo == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": _plano(valor)}}]}
    # number, checkbox, date, url, email, phone, people, files copiam direto.
    return {tipo: valor}


def _plano(rich: list[dict[str, Any]]) -> str:
    """Texto puro de um array de ``rich_text``."""

    return "".join(p.get("plain_text", "") for p in rich)


def clonar_database(
    database_id: str,
    *,
    titulo: str | None = None,
    pagina_destino: str | None = None,
    com_linhas: bool = False,
    relacoes: str = "auto-novo",
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Clona um database com todas as propriedades, sem vínculo com a origem.

    Replica o schema completo (status, select, relações) num database novo. As
    relações que a origem fazia consigo mesma viram auto-relações do clone; as
    que apontavam para outros databases são preservadas. Opcionalmente copia as
    linhas (valores de relação são mantidos apontando para as mesmas páginas).

    Args:
        database_id: ID do database de origem.
        titulo: Título do clone. Padrão: ``"<origem> (cópia)"``.
        pagina_destino: ID da página onde criar o clone. Padrão: a mesma página
            pai da origem.
        com_linhas: Quando verdadeiro, copia também as linhas da origem.
        relacoes: ``"auto-novo"`` (padrão) ou ``"texto"``. Ver
            :func:`_schema_para_clone`.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        ``{"id", "data_source_id", "titulo", "propriedades", "linhas_copiadas"}``.

    Raises:
        ValueError: Se a origem não tiver data source acessível ou tiver vários,
            ou se ``relacoes`` for inválido.
    """

    if relacoes not in {"auto-novo", "texto"}:
        raise ValueError("relacoes deve ser 'auto-novo' ou 'texto'.")

    cli = cliente or _cliente_padrao()
    fonte_origem = _fonte_unica(cli, database_id)
    fonte_origem_id = fonte_origem["id"]
    schema_origem = cli.get_data_source(fonte_origem_id).get("properties", {})

    titulo_origem = fonte_origem.get("name") or "Database"
    titulo_clone = titulo or f"{titulo_origem} (cópia)"
    destino = pagina_destino or _pagina_pai(cli, database_id)

    # 1) Cria o database já com a propriedade title (o data source exige uma),
    #    com o mesmo nome de coluna da origem. Descobre então o data source.
    nome_title = _nome_title(schema_origem)
    criado = cli.criar_database(destino, titulo_clone, {nome_title: {"title": {}}})
    clone_id = criado["id"]
    fonte_destino_id = _fonte_unica(cli, clone_id)["id"]

    # 2) Aplica o schema completo no data source do clone.
    schema_clone = _schema_para_clone(
        schema_origem,
        fonte_origem_id=fonte_origem_id,
        fonte_destino_id=fonte_destino_id,
        relacoes=relacoes,
    )
    if schema_clone:
        cli.atualizar_data_source(fonte_destino_id, propriedades=schema_clone)

    copiadas = 0
    if com_linhas:
        copiadas = _copiar_linhas(
            cli,
            fonte_origem_id=fonte_origem_id,
            fonte_destino_id=fonte_destino_id,
            relacoes=relacoes,
        )

    return {
        "id": clone_id,
        "data_source_id": fonte_destino_id,
        "titulo": titulo_clone,
        "propriedades": sorted(schema_clone) + [_nome_title(schema_origem)],
        "linhas_copiadas": copiadas,
    }


def _copiar_linhas(
    cli: NotionClient,
    *,
    fonte_origem_id: str,
    fonte_destino_id: str,
    relacoes: str,
) -> int:
    """Copia as linhas da origem para o clone. Retorna quantas foram criadas."""

    copiar_relacao = relacoes != "texto"
    total = 0
    for linha in cli.consultar_data_source(fonte_origem_id, buscar_todos=True):
        propriedades: dict[str, dict[str, object]] = {}
        for nome, prop in linha.get("properties", {}).items():
            if prop.get("type") == "relation" and not copiar_relacao:
                continue
            valor = _valor_para_copia(prop)
            if valor is not None:
                propriedades[nome] = valor
        if propriedades:
            cli.criar_pagina_em_fonte(fonte_destino_id, propriedades)
            total += 1
    return total


def _pagina_pai(cli: NotionClient, database_id: str) -> str:
    """Descobre a página pai de um database (para criar o clone ao lado)."""

    info = cli.get_data_source(_fonte_unica(cli, database_id)["id"])
    parent = info.get("parent", {})
    pagina = parent.get("page_id")
    if not pagina:
        raise ValueError(
            "Não foi possível resolver a página pai da origem; informe "
            "pagina_destino explicitamente."
        )
    return pagina


def _nome_title(schema: dict[str, Any]) -> str:
    """Nome da propriedade ``title`` no schema (para listar no retorno)."""

    for nome, definicao in schema.items():
        if definicao.get("type") == "title":
            return nome
    return "Name"
