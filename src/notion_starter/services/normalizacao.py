"""Caso de uso de normalização de nomes do database de tarefas.

Migra um database do Notion vindo de um template em inglês/numerado para os
nomes intuitivos que o resto do sistema espera: renomeia propriedades (``Status``
-> ``Etapa``, ``Duração`` -> ``Esforço``…), traduz as opções de ``status`` e os
valores das linhas, e ajusta o database de "Áreas da vida".

Esta lógica vivia na borda (CLI), misturando regra de negócio com o controller.
Movida para cá como caso de uso explícito: a CLI/MCP só chamam
:func:`normalizar_nomes` e formatam o resultado. Como as demais camadas de
serviço, **não conhece HTTP** e aceita um :class:`NotionClient` injetado,
mantendo o fluxo testável sem token nem rede.

Toda a migração respeita ``aplicar``: com ``aplicar=False`` (dry-run) o serviço
calcula e devolve o que *seria* alterado sem escrever no Notion.
"""

from __future__ import annotations

from typing import Any

from notion_starter import NotionClient, properties

#: Renomeações de propriedades (coluna): nome do template -> nome intuitivo.
RENOMEAR_PROPRIEDADES = {
    "Nome": "Tarefa",
    "Status": "Etapa",
    "Duração": "Esforço",
    "Próximo prazo": "Prazo",
    "Áreas-da-Vida": "Áreas da vida",
    "Priority": "Prioridade",
    "Subitem": "Subtarefas",
    "Subitem 1": "Subtarefas relacionadas",
    "item principal": "Tarefa principal",
}

#: Renomeações das opções de status (etapa) do template numerado.
RENOMEAR_STATUS = {
    "00. Inbox": "Entrada",
    "01. Urgente": "Urgente",
    "02. ASAP": "Assim que possível",
    "03. Delegar": "Delegar",
    "04. Aguardando Resposta": "Aguardando resposta",
    "05. Referências": "Referência",
    "06. Feito": "Concluída",
    "07. Someday": "Algum dia",
    "xx. Agendado": "Agendada",
}

#: Renomeações das opções de duração (esforço).
RENOMEAR_DURACAO = {
    "Mais rápido possível": "Agora",
    "Pra hoje": "Hoje",
    "Concluido": "Concluída",
}

#: Renomeações das páginas do database de Áreas da vida.
RENOMEAR_AREAS = {
    "Money": "Finanças",
    "Projects": "Projetos",
    "Shoppe": "Compras",
}


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` a partir da configuração do servidor.

    Import tardio de propósito: evita acoplar a camada de casos de uso ao Django
    no import — a config só é tocada quando nenhum cliente é injetado (uso real).
    """

    from integrations.notion import criar_cliente

    return criar_cliente()


def normalizar_nomes(
    database_id: str,
    *,
    aplicar: bool = True,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Normaliza propriedades, opções e valores do database de tarefas.

    Args:
        database_id: ID do database de tarefas a migrar.
        aplicar: Quando ``False`` (dry-run), apenas calcula o que mudaria.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um relatório do que foi (ou seria) alterado: opções adicionadas,
        páginas migradas, opções antigas removidas, propriedades e áreas
        renomeadas.
    """

    cli = cliente or _cliente_padrao()
    schema = cli.get_database(database_id)
    props = schema.get("properties") or {}
    prop_status = _nome_propriedade(props, "Status", "Etapa")
    prop_duracao = _nome_propriedade(props, "Duração", "Esforço")
    prop_areas = _nome_propriedade(props, "Áreas-da-Vida", "Áreas da vida")
    areas_db_id = ((props.get(prop_areas or "") or {}).get("relation") or {}).get("database_id")

    status_adicionados = (
        _adicionar_opcoes_status(cli, database_id, prop_status, RENOMEAR_STATUS, aplicar=aplicar)
        if prop_status
        else []
    )
    duracao_adicionadas = (
        _adicionar_opcoes_status(cli, database_id, prop_duracao, RENOMEAR_DURACAO, aplicar=aplicar)
        if prop_duracao
        else []
    )
    paginas_alteradas = _migrar_valores_paginas(
        cli, database_id, prop_status, prop_duracao, aplicar=aplicar
    )
    status_removidos = (
        _limpar_opcoes_antigas(cli, database_id, prop_status, RENOMEAR_STATUS, aplicar=aplicar)
        if prop_status
        else []
    )
    duracao_removidas = (
        _limpar_opcoes_antigas(cli, database_id, prop_duracao, RENOMEAR_DURACAO, aplicar=aplicar)
        if prop_duracao
        else []
    )
    areas = _normalizar_database_areas(cli, areas_db_id, aplicar=aplicar)
    propriedades = _renomear_propriedades(cli, database_id, RENOMEAR_PROPRIEDADES, aplicar=aplicar)

    return {
        "aplicado": aplicar,
        "database_id": database_id,
        "opcoes_adicionadas": {"status": status_adicionados, "duracao": duracao_adicionadas},
        "paginas_alteradas": paginas_alteradas,
        "opcoes_antigas_removidas": {"status": status_removidos, "duracao": duracao_removidas},
        "propriedades_renomeadas": propriedades,
        "areas": areas,
    }


# -- Auxiliares de schema --------------------------------------------------


def _nome_propriedade(
    propriedades: dict[str, Any], nome_antigo: str, nome_novo: str
) -> str | None:
    """Resolve o nome de uma propriedade que pode estar no estado antigo ou novo."""

    if nome_antigo in propriedades:
        return nome_antigo
    if nome_novo in propriedades:
        return nome_novo
    return None


def _valor_status(propriedade: dict[str, Any] | None) -> str | None:
    """Nome da opção atual de uma propriedade ``status``/``select`` de uma linha."""

    if not propriedade:
        return None
    valor = propriedade.get(propriedade.get("type", ""))
    return valor.get("name") if isinstance(valor, dict) else None


def _texto_title(propriedade: dict[str, Any] | None) -> str:
    """Texto puro de uma propriedade ``title``."""

    if not propriedade:
        return ""
    return "".join(
        item.get("plain_text", item.get("text", {}).get("content", ""))
        for item in propriedade.get("title", [])
    )


def _nome_title_property(schema: dict[str, Any]) -> str | None:
    """Nome da propriedade ``title`` de um schema de database."""

    for nome, prop in (schema.get("properties") or {}).items():
        if prop.get("type") == "title":
            return nome
    return None


def _titulo_database(database: dict[str, Any]) -> str:
    """Título textual de um objeto database do Notion."""

    return "".join(parte.get("plain_text", "") for parte in database.get("title", [])).strip()


def _grupo_por_opcao(status_schema: dict[str, Any]) -> dict[str, str]:
    """Mapeia ``option_id -> nome do grupo`` de um schema de ``status``."""

    grupos: dict[str, str] = {}
    for grupo in status_schema.get("groups", []):
        nome = grupo.get("name")
        if not nome:
            continue
        for option_id in grupo.get("option_ids", []):
            grupos[option_id] = nome
    return grupos


def _payload_opcao_existente(opcao: dict[str, Any]) -> dict[str, str]:
    """Referência a uma opção existente (por id, ou por nome se não houver id)."""

    if opcao.get("id"):
        return {"id": opcao["id"]}
    return {"name": opcao.get("name", "")}


# -- Passos da migração ----------------------------------------------------


def _adicionar_opcoes_status(
    cliente: NotionClient,
    database_id: str,
    propriedade: str,
    renomes: dict[str, str],
    *,
    aplicar: bool,
) -> list[dict[str, str]]:
    """Adiciona as opções de status renomeadas, preservando cor e grupo."""

    schema = cliente.get_database(database_id)
    prop = (schema.get("properties") or {}).get(propriedade, {})
    status_schema = prop.get("status") or {}
    opcoes = status_schema.get("options", [])
    por_nome = {op.get("name"): op for op in opcoes if op.get("name")}
    grupo_por_id = _grupo_por_opcao(status_schema)

    adicionadas: list[dict[str, str]] = []
    payload = [_payload_opcao_existente(op) for op in opcoes]
    for antigo, novo in renomes.items():
        if antigo not in por_nome or novo in por_nome:
            continue
        antiga = por_nome[antigo]
        nova_opcao = {"name": novo, "color": antiga.get("color") or "default"}
        grupo = grupo_por_id.get(antiga.get("id", ""))
        if grupo:
            nova_opcao["group"] = grupo
        payload.append(nova_opcao)
        adicionadas.append({"de": antigo, "para": novo})

    if adicionadas and aplicar:
        cliente.atualizar_database(
            database_id, propriedades={propriedade: {"status": {"options": payload}}}
        )
    return adicionadas


def _limpar_opcoes_antigas(
    cliente: NotionClient,
    database_id: str,
    propriedade: str,
    renomes: dict[str, str],
    *,
    aplicar: bool,
) -> list[str]:
    """Remove as opções antigas cujo equivalente novo já existe."""

    schema = cliente.get_database(database_id)
    prop = (schema.get("properties") or {}).get(propriedade, {})
    status_schema = prop.get("status") or {}
    opcoes = status_schema.get("options", [])
    nomes = {op.get("name") for op in opcoes}
    antigas_para_remover = {
        antigo for antigo, novo in renomes.items() if antigo in nomes and novo in nomes
    }
    if not antigas_para_remover:
        return []

    payload = [
        _payload_opcao_existente(op) for op in opcoes if op.get("name") not in antigas_para_remover
    ]
    if aplicar:
        cliente.atualizar_database(
            database_id, propriedades={propriedade: {"status": {"options": payload}}}
        )
    return sorted(antigas_para_remover)


def _migrar_valores_paginas(
    cliente: NotionClient,
    database_id: str,
    propriedade_status: str | None,
    propriedade_duracao: str | None,
    *,
    aplicar: bool,
) -> int:
    """Migra os valores de status/duração de cada linha para os novos nomes."""

    alteradas = 0
    for pagina in cliente.consultar_database(database_id, buscar_todos=True):
        props = pagina.get("properties") or {}
        atualizacoes: dict[str, dict[str, Any]] = {}
        if propriedade_status:
            atual = _valor_status(props.get(propriedade_status))
            if atual in RENOMEAR_STATUS:
                atualizacoes[propriedade_status] = properties.status(RENOMEAR_STATUS[atual])
        if propriedade_duracao:
            atual = _valor_status(props.get(propriedade_duracao))
            if atual in RENOMEAR_DURACAO:
                atualizacoes[propriedade_duracao] = properties.status(RENOMEAR_DURACAO[atual])
        if atualizacoes:
            alteradas += 1
            if aplicar:
                cliente.atualizar_pagina(pagina["id"], atualizacoes)
    return alteradas


def _renomear_propriedades(
    cliente: NotionClient,
    database_id: str,
    renomes: dict[str, str],
    *,
    aplicar: bool,
) -> list[dict[str, str]]:
    """Renomeia colunas que existem com o nome antigo e ainda não têm o novo."""

    schema = cliente.get_database(database_id)
    props = schema.get("properties") or {}
    payload: dict[str, dict[str, str]] = {}
    feitas: list[dict[str, str]] = []
    for antigo, novo in renomes.items():
        if antigo in props and novo not in props:
            payload[antigo] = {"name": novo}
            feitas.append({"de": antigo, "para": novo})
    if payload and aplicar:
        cliente.atualizar_database(database_id, propriedades=payload)
    return feitas


def _normalizar_database_areas(
    cliente: NotionClient,
    database_id: str | None,
    *,
    aplicar: bool,
) -> dict[str, Any]:
    """Normaliza o database de Áreas da vida (páginas, coluna e título)."""

    if not database_id:
        return {"database_id": None, "paginas_renomeadas": [], "propriedades_renomeadas": []}

    schema = cliente.get_database(database_id)
    title_prop = _nome_title_property(schema)
    paginas_renomeadas: list[dict[str, str]] = []
    if title_prop:
        for pagina in cliente.consultar_database(database_id, buscar_todos=True):
            atual = _texto_title((pagina.get("properties") or {}).get(title_prop))
            novo = RENOMEAR_AREAS.get(atual)
            if not novo:
                continue
            paginas_renomeadas.append({"de": atual, "para": novo})
            if aplicar:
                cliente.atualizar_pagina(pagina["id"], {title_prop: properties.title(novo)})

    propriedades_renomeadas = _renomear_propriedades(
        cliente, database_id, {"Name": "Área"}, aplicar=aplicar
    )

    titulo_atual = _titulo_database(cliente.get_database(database_id))
    titulo_renomeado = titulo_atual != "Áreas da vida"
    if titulo_renomeado and aplicar:
        cliente.atualizar_database(database_id, titulo="Áreas da vida")

    return {
        "database_id": database_id,
        "titulo_renomeado": titulo_renomeado,
        "paginas_renomeadas": paginas_renomeadas,
        "propriedades_renomeadas": propriedades_renomeadas,
    }
