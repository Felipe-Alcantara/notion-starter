"""Transforma itens crus do Notion em um inventário navegável do workspace.

Lógica pura, sem rede: recebe a lista de páginas/databases retornada por
:meth:`NotionClient.buscar` e reconstrói a hierarquia (via ``parent``), além de
destacar duplicatas por nome, itens possivelmente vazios e itens órfãos.

Fluxo típico:
    itens_crus = client.buscar(buscar_todos=True)
    inventario = construir_inventario(itens_crus)
    inventario.duplicatas        # nomes repetidos
    inventario.raizes            # topo da árvore (filhos em cada NoArvore)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEM_TITULO = "(sem título)"


@dataclass
class ItemInventario:
    """Forma normalizada de uma página ou database do Notion.

    Attributes:
        id: Identificador do item no Notion.
        tipo: ``"page"`` ou ``"database"``.
        titulo: Título legível (ou ``"(sem título)"``).
        parent_tipo: Tipo do parent (``workspace``/``page_id``/``database_id``/``block_id``).
        parent_id: ID do parent, ou ``None`` quando o parent é o workspace.
        url: URL do item no Notion, quando disponível.
    """

    id: str
    tipo: str
    titulo: str
    parent_tipo: str
    parent_id: str | None
    url: str | None = None


@dataclass
class NoArvore:
    """Nó da árvore do workspace: um item com seus filhos diretos."""

    item: ItemInventario
    filhos: list[NoArvore] = field(default_factory=list)


@dataclass
class Inventario:
    """Resultado do inventário do workspace.

    Attributes:
        itens: Todos os itens normalizados, indexados por ``id``.
        raizes: Nós de topo da árvore (parent fora do conjunto ou workspace).
        duplicatas: Mapa de título para a lista de itens que o compartilham.
        vazios: Itens sem filhos na árvore (candidatos a revisão/arquivamento).
        orfaos: Itens cujo parent não está entre os itens visíveis.
    """

    itens: dict[str, ItemInventario]
    raizes: list[NoArvore]
    duplicatas: dict[str, list[ItemInventario]]
    vazios: list[ItemInventario]
    orfaos: list[ItemInventario]

    @property
    def total_paginas(self) -> int:
        return sum(1 for i in self.itens.values() if i.tipo == "page")

    @property
    def total_databases(self) -> int:
        return sum(1 for i in self.itens.values() if i.tipo == "database")


def _extrair_titulo(item: dict[str, Any]) -> str:
    """Extrai um título legível de um item cru de página ou database."""

    if item.get("object") == "database":
        partes = item.get("title", [])
        return "".join(p.get("plain_text", "") for p in partes).strip() or SEM_TITULO

    for prop in item.get("properties", {}).values():
        if prop.get("type") == "title":
            partes = prop.get("title", [])
            return "".join(p.get("plain_text", "") for p in partes).strip() or SEM_TITULO
    return SEM_TITULO


def _extrair_parent(item: dict[str, Any]) -> tuple[str, str | None]:
    """Devolve ``(parent_tipo, parent_id)`` de um item cru.

    O Notion usa uma chave diferente conforme o tipo de parent
    (``page_id``/``database_id``/``block_id``); ``workspace`` não tem id.
    """

    parent = item.get("parent", {})
    parent_tipo = parent.get("type", "workspace")
    parent_id = parent.get(parent_tipo) if parent_tipo != "workspace" else None
    # ``workspace`` vem como booleano ``True``; normaliza para None.
    if not isinstance(parent_id, str):
        parent_id = None
    return parent_tipo, parent_id


def normalizar_item(item: dict[str, Any]) -> ItemInventario:
    """Converte um item cru do ``/search`` em :class:`ItemInventario`.

    Args:
        item: JSON de uma página ou database como vem de :meth:`NotionClient.buscar`.

    Returns:
        O item normalizado.
    """

    parent_tipo, parent_id = _extrair_parent(item)
    return ItemInventario(
        id=item.get("id", ""),
        tipo=item.get("object", "page"),
        titulo=_extrair_titulo(item),
        parent_tipo=parent_tipo,
        parent_id=parent_id,
        url=item.get("url"),
    )


def construir_inventario(itens_crus: list[dict[str, Any]]) -> Inventario:
    """Monta o inventário completo a partir dos itens crus do workspace.

    Args:
        itens_crus: Lista de páginas/databases de :meth:`NotionClient.buscar`.

    Returns:
        Um :class:`Inventario` com árvore, duplicatas, vazios e órfãos.
    """

    itens = {item.id: item for item in (normalizar_item(cru) for cru in itens_crus) if item.id}

    nos = {item_id: NoArvore(item=item) for item_id, item in itens.items()}

    raizes: list[NoArvore] = []
    orfaos: list[ItemInventario] = []

    for no in nos.values():
        pai_id = no.item.parent_id
        if pai_id is None:
            # Parent é o workspace: nó de topo.
            raizes.append(no)
        elif pai_id in nos:
            nos[pai_id].filhos.append(no)
        else:
            # Parent existe no Notion mas não está entre os itens visíveis.
            orfaos.append(no.item)
            raizes.append(no)

    duplicatas: dict[str, list[ItemInventario]] = {}
    for item in itens.values():
        if item.titulo != SEM_TITULO:
            duplicatas.setdefault(item.titulo, []).append(item)
    duplicatas = {titulo: lista for titulo, lista in duplicatas.items() if len(lista) > 1}

    vazios = [no.item for no in nos.values() if not no.filhos]

    return Inventario(
        itens=itens,
        raizes=raizes,
        duplicatas=duplicatas,
        vazios=vazios,
        orfaos=orfaos,
    )


@dataclass
class GrupoSchema:
    """Databases que compartilham a mesma estrutura de colunas.

    Attributes:
        assinatura: A impressão digital do schema (colunas normalizadas).
        databases: IDs dos databases com essa mesma assinatura.
        nomes: Títulos desses databases (pode haver nomes diferentes).
    """

    assinatura: str
    databases: list[str]
    nomes: list[str]

    @property
    def mesmos_nomes(self) -> bool:
        """Se todos os databases do grupo têm o mesmo título."""

        return len(set(self.nomes)) == 1


def assinatura_schema(colunas: dict[str, str]) -> str:
    """Gera uma impressão digital estável de um schema de database.

    Dois databases com as mesmas colunas (nome + tipo) produzem a mesma
    assinatura, independentemente da ordem em que as colunas aparecem. Serve
    para identificar databases com estrutura idêntica — possivelmente "o mesmo"
    database copiado para lugares distintos, mesmo que tenham nomes diferentes.

    Args:
        colunas: Mapeamento de nome de coluna para tipo Notion, como em
            :func:`schema.extrair_tipos_propriedades`.

    Returns:
        Uma string canônica representando o conjunto de colunas.
    """

    pares = sorted(f"{nome}:{tipo}" for nome, tipo in colunas.items())
    return "|".join(pares)


def agrupar_por_schema(
    schemas: dict[str, dict[str, str]],
    nomes: dict[str, str] | None = None,
) -> list[GrupoSchema]:
    """Agrupa databases que têm exatamente a mesma estrutura de colunas.

    Args:
        schemas: Mapeamento de ``database_id`` para suas colunas
            (``{nome_coluna: tipo}``).
        nomes: Mapeamento opcional de ``database_id`` para título, usado só
            para exibição no resultado.

    Returns:
        Os grupos com mais de um database compartilhando a mesma assinatura,
        ordenados do maior grupo para o menor.
    """

    assinaturas = {
        db_id: assinatura_schema(colunas)
        for db_id, colunas in schemas.items()
        if colunas  # database sem colunas legíveis não entra na comparação
    }
    return agrupar_por_assinatura(assinaturas, nomes)


def agrupar_por_assinatura(
    assinaturas: dict[str, str],
    nomes: dict[str, str] | None = None,
) -> list[GrupoSchema]:
    """Agrupa databases que compartilham a mesma assinatura já calculada.

    Útil quando a assinatura inclui mais do que as colunas (ex.: as opções das
    propriedades, via :func:`assinatura_perfil`). Mantém o agrupamento separado
    de como a impressão digital foi gerada.

    Args:
        assinaturas: Mapeamento de ``database_id`` para sua assinatura.
        nomes: Mapeamento opcional de ``database_id`` para título (exibição).

    Returns:
        Os grupos com mais de um database por assinatura, do maior ao menor.
    """

    nomes = nomes or {}
    por_assinatura: dict[str, list[str]] = {}
    for db_id, assinatura in assinaturas.items():
        por_assinatura.setdefault(assinatura, []).append(db_id)

    grupos = [
        GrupoSchema(
            assinatura=assinatura,
            databases=ids,
            nomes=[nomes.get(i, SEM_TITULO) for i in ids],
        )
        for assinatura, ids in por_assinatura.items()
        if len(ids) > 1
    ]
    grupos.sort(key=lambda g: len(g.databases), reverse=True)
    return grupos


#: Tipos de propriedade cujas opções entram na assinatura de perfil.
_TIPOS_COM_OPCOES = ("select", "status", "multi_select")


def extrair_perfil_database(database: dict[str, Any]) -> dict[str, str]:
    """Extrai um perfil rico de um database: colunas + opções das propriedades.

    Diferente de :func:`schema.extrair_tipos_propriedades` (só nome→tipo), aqui
    cada coluna de ``select``/``status``/``multi_select`` carrega também as suas
    opções. Em workspaces onde a estrutura "geral" se repete, são as opções (ex.:
    os Status, as áreas) que de fato distinguem um database do outro.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.

    Returns:
        Mapeamento de nome de coluna para uma descrição (tipo + opções ordenadas).
    """

    perfil: dict[str, str] = {}
    for nome, info in database.get("properties", {}).items():
        tipo = info.get("type", "?")
        if tipo in _TIPOS_COM_OPCOES:
            opcoes = sorted(o.get("name", "") for o in info.get(tipo, {}).get("options", []))
            perfil[nome] = f"{tipo}({','.join(opcoes)})"
        else:
            perfil[nome] = tipo
    return perfil


def assinatura_perfil(perfil: dict[str, str]) -> str:
    """Gera a impressão digital de um perfil de database (colunas + opções).

    Args:
        perfil: Saída de :func:`extrair_perfil_database`.

    Returns:
        Uma string canônica; dois databases com as mesmas colunas E as mesmas
        opções produzem a mesma assinatura.
    """

    pares = sorted(f"{nome}={descricao}" for nome, descricao in perfil.items())
    return "||".join(pares)
