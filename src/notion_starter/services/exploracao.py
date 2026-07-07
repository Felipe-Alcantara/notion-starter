"""Exploração genérica e somente-leitura de qualquer database do Notion.

Onde ``services.tarefas`` fala um schema fixo (Etapa/Esforço/Áreas) para o app
de tarefas, esta camada não pressupõe schema nenhum: descobre as colunas de um
database e devolve cada linha como um mapa ``coluna -> texto``. É o que permite
ao site mostrar um database qualquer (livros, finanças, …) numa tabela genérica,
sem depender do formato de tarefa.

Read-only por escopo: lista databases visíveis, descreve colunas e linhas. Não
cria nem edita — a escrita genérica (relation, date, multi-select…) é
complexa o suficiente para ser um passo próprio depois. Como as demais camadas
de serviço, **não conhece HTTP** e aceita um :class:`NotionClient` injetado.
"""

from __future__ import annotations

from typing import Any

from notion_starter import NotionClient

#: Tipos de coluna sem valor textual útil numa tabela (ruído visual).
_TIPOS_OCULTOS = frozenset({"button"})


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


def listar_databases(
    query: str | None = None,
    *,
    cliente: NotionClient | None = None,
) -> list[dict[str, str]]:
    """Lista os databases visíveis à integração, para o seletor do site.

    Args:
        query: Texto opcional para filtrar pelo título.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        Lista de ``{"id", "titulo", "url"}`` — só objetos do tipo ``database``.
    """

    cli = cliente or _cliente_padrao()
    itens = cli.buscar(
        query=query,
        buscar_todos=True,
        filtro={"value": "database", "property": "object"},
    )
    databases = [
        {
            "id": item.get("id", ""),
            "titulo": _titulo_database(item),
            "url": item.get("url", ""),
        }
        for item in itens
    ]
    databases.sort(key=lambda d: d["titulo"].lower())
    return databases


def descrever_database(
    database_id: str,
    *,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Descreve um database genérico: colunas + linhas como texto.

    Resolve os *data sources* (modelo novo), lê o schema de cada um e devolve
    as linhas já achatadas em ``coluna -> texto`` — pronto para uma tabela.

    Args:
        database_id: ID do database.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        ``{"id", "colunas": [{"nome", "tipo"}], "linhas": [{"id", "url",
        "valores": {coluna: texto}}]}``. Colunas e linhas vêm vazias quando o
        database não tem *data source* acessível à integração.
    """

    cli = cliente or _cliente_padrao()
    fontes = cli.listar_data_sources(database_id)
    if not fontes:
        return {"id": database_id, "colunas": [], "linhas": []}

    colunas = _colunas_unificadas(cli, fontes)
    linhas: list[dict[str, Any]] = []
    for fonte in fontes:
        fonte_id = fonte.get("id")
        if not fonte_id:
            continue
        for pagina in cli.consultar_data_source(fonte_id, buscar_todos=True):
            linhas.append(_linha_para_valores(pagina, colunas))

    return {
        "id": database_id,
        "colunas": [{"nome": nome, "tipo": tipo} for nome, tipo in colunas],
        "linhas": linhas,
    }


def _colunas_unificadas(
    cliente: NotionClient, fontes: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Lista ``(nome, tipo)`` das colunas, com a coluna ``title`` primeiro."""

    vistas: dict[str, str] = {}
    titulo_nome: str | None = None
    for fonte in fontes:
        fonte_id = fonte.get("id")
        if not fonte_id:
            continue
        schema = cliente.get_data_source(fonte_id).get("properties", {})
        for nome, definicao in schema.items():
            tipo = definicao.get("type", "")
            if tipo in _TIPOS_OCULTOS or nome in vistas:
                continue
            vistas[nome] = tipo
            if tipo == "title":
                titulo_nome = nome

    ordenadas = sorted(vistas.items(), key=lambda item: item[0].lower())
    if titulo_nome:
        # Título sempre na frente — é a coluna que identifica a linha.
        ordenadas.sort(key=lambda item: item[0] != titulo_nome)
    return ordenadas


def _linha_para_valores(
    pagina: dict[str, Any], colunas: list[tuple[str, str]]
) -> dict[str, Any]:
    """Achata uma linha do Notion em ``{coluna: texto}`` para as colunas dadas."""

    props = pagina.get("properties", {})
    valores = {nome: _valor_texto(props.get(nome)) for nome, _tipo in colunas}
    return {"id": pagina.get("id", ""), "url": pagina.get("url", ""), "valores": valores}


def _valor_texto(prop: dict[str, Any] | None) -> str:
    """Converte qualquer propriedade de linha do Notion num texto exibível.

    Cobre os tipos comuns; tipos desconhecidos caem para string vazia em vez de
    quebrar — a meta é nunca falhar ao mostrar um database de schema imprevisto.
    """

    if not prop:
        return ""
    tipo = prop.get("type", "")
    valor = prop.get(tipo)

    if tipo in {"title", "rich_text"}:
        return "".join(p.get("plain_text", "") for p in (valor or []))
    if tipo in {"select", "status"}:
        return valor.get("name", "") if isinstance(valor, dict) else ""
    if tipo == "multi_select":
        return ", ".join(o.get("name", "") for o in (valor or []))
    if tipo == "number":
        return "" if valor is None else str(valor)
    if tipo == "checkbox":
        return "✓" if valor else ""
    if tipo == "date":
        return _texto_data(valor)
    if tipo == "people":
        return ", ".join(p.get("name", "") for p in (valor or []))
    if tipo == "relation":
        n = len(valor or [])
        return f"{n} vínculo(s)" if n else ""
    if tipo in {"url", "email", "phone_number"}:
        return valor or ""
    if tipo == "files":
        return ", ".join(f.get("name", "") for f in (valor or []))
    if tipo == "formula":
        return _valor_formula(valor)
    if tipo in {"created_time", "last_edited_time"}:
        return valor or ""
    if tipo in {"created_by", "last_edited_by"}:
        return valor.get("name", "") if isinstance(valor, dict) else ""
    if tipo == "unique_id" and isinstance(valor, dict):
        prefixo = valor.get("prefix") or ""
        numero = valor.get("number")
        return f"{prefixo}{numero}" if numero is not None else ""
    return ""


def _valor_formula(valor: dict[str, Any] | None) -> str:
    """Texto do resultado de uma ``formula`` (string/number/boolean/date)."""

    if not isinstance(valor, dict):
        return ""
    tipo = valor.get("type", "")
    interno = valor.get(tipo)
    if tipo == "date":
        return _texto_data(interno)
    if tipo == "boolean":
        return "✓" if interno else ""
    if interno is None:
        return ""
    return str(interno)


def _texto_data(valor: dict[str, Any] | None) -> str:
    """Formata uma propriedade ``date`` (início, ou intervalo início → fim)."""

    if not isinstance(valor, dict):
        return ""
    inicio = valor.get("start") or ""
    fim = valor.get("end")
    return f"{inicio} → {fim}" if fim else inicio


def _titulo_database(item: dict[str, Any]) -> str:
    """Título textual de um objeto database do ``/search``."""

    titulo = "".join(p.get("plain_text", "") for p in item.get("title", [])).strip()
    return titulo or "(sem título)"
