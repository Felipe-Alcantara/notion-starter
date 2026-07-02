"""Camada de alto nível para trabalhar com um database de tarefas do Notion.

Traduz entre o JSON cru do Notion e um objeto :class:`Tarefa` simples — a forma
que um front ou um sistema de IA consome sem precisar conhecer o formato da API.
Fica acima de :class:`NotionClient`: lê, cria e atualiza tarefas, mapeando as
colunas comuns (Tarefa, Etapa, Prazo) de um database de tasklist.

Os nomes das colunas são configuráveis porque variam entre workspaces; os
padrões batem com um database de tarefas típico do Notion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import properties as p
from .client import NotionClient


@dataclass
class CamposTarefa:
    """Nomes das colunas do database de tarefas (configurável por workspace).

    Permite reaproveitar o módulo em databases que nomeiam as colunas de forma
    diferente, sem mudar a lógica.
    """

    nome: str = "Tarefa"
    status: str = "Etapa"
    prazo: str = "Prazo"
    duracao: str = "Esforço"
    areas: str = "Áreas da vida"


@dataclass
class Tarefa:
    """Uma tarefa lida de um database do Notion, em forma simples.

    Attributes:
        id: ID da página (a tarefa) no Notion.
        nome: Texto do título.
        status: Nome do status atual (ou ``None`` se não definido).
        prazo: Data do prazo em ISO (ou ``None``).
        duracao: Nome do status de duração/esforço (ou ``None``).
        areas: IDs das páginas relacionadas em "Áreas da vida".
        areas_nomes: Nomes das áreas, resolvidos pela ``TaskList`` (vazio até
            o enriquecimento; ``tarefa_de_pagina`` é pura).
        url: Link da tarefa no Notion.
        bruto: O JSON original, para quem precisar de campos não mapeados.
    """

    id: str
    nome: str
    status: str | None = None
    prazo: str | None = None
    duracao: str | None = None
    areas: list[str] = field(default_factory=list)
    areas_nomes: list[str] = field(default_factory=list)
    url: str | None = None
    bruto: dict[str, Any] = field(default_factory=dict, repr=False)


def _texto_title(prop: dict[str, Any]) -> str:
    partes = prop.get("title", [])
    return "".join(t.get("plain_text", t.get("text", {}).get("content", "")) for t in partes)


def _ler_nome_status(prop: dict[str, Any]) -> str | None:
    """Extrai o nome de uma propriedade do tipo ``status`` (ou similar com ``name``)."""
    valor = prop.get(prop.get("type", ""))
    if isinstance(valor, dict):
        return valor.get("name")
    return None


def _extrair_opcoes_status(prop_schema: dict[str, Any]) -> list[str]:
    """Extrai os nomes das opções de uma propriedade ``status`` no schema do database."""
    status_obj = prop_schema.get("status") or prop_schema.get("select") or {}
    opcoes = status_obj.get("options", [])
    return [opt.get("name", "") for opt in opcoes if opt.get("name")]


def _texto_title_de_pagina(pagina: dict[str, Any]) -> str:
    """Extrai o texto do título da primeira propriedade ``title`` de uma página."""
    for prop in (pagina.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _texto_title(prop)
    return ""


def _combinar_filtros(filtros: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Combina filtros do Notion mantendo o caso simples legível."""

    if not filtros:
        return None
    if len(filtros) == 1:
        return filtros[0]
    return {"and": filtros}


def tarefa_de_pagina(pagina: dict[str, Any], campos: CamposTarefa) -> Tarefa:
    """Converte o JSON cru de uma página do Notion em :class:`Tarefa`.

    Args:
        pagina: Item retornado por :meth:`NotionClient.consultar_database`.
        campos: Nomes das colunas a ler.

    Returns:
        A tarefa normalizada.
    """

    props = pagina.get("properties", {})

    nome = ""
    if campos.nome in props:
        nome = _texto_title(props[campos.nome])

    status = _ler_nome_status(props.get(campos.status, {}))
    duracao = _ler_nome_status(props.get(campos.duracao, {}))

    prazo = None
    prop_prazo = props.get(campos.prazo, {})
    if prop_prazo.get("type") == "date" and isinstance(prop_prazo.get("date"), dict):
        prazo = prop_prazo["date"].get("start")

    areas: list[str] = []
    prop_areas = props.get(campos.areas, {})
    if isinstance(prop_areas.get("relation"), list):
        areas = [r.get("id", "") for r in prop_areas["relation"]]

    return Tarefa(
        id=pagina.get("id", ""),
        nome=nome,
        status=status,
        prazo=prazo,
        duracao=duracao,
        areas=areas,
        url=pagina.get("url"),
        bruto=pagina,
    )


class TaskList:
    """Operações de tasklist sobre um database de tarefas do Notion.

    Args:
        client: Um :class:`NotionClient` já configurado.
        database_id: ID do database de tarefas.
        campos: Nomes das colunas (use o padrão ou ajuste ao seu database).
    """

    def __init__(
        self,
        client: NotionClient,
        database_id: str,
        campos: CamposTarefa | None = None,
    ) -> None:
        self._client = client
        self._database_id = database_id
        self._campos = campos or CamposTarefa()
        self._cache_areas: dict[str, str] = {}  # {area_id: nome}

    # -- Leitura ---------------------------------------------------------------

    def listar(
        self,
        status: str | None = None,
        duracao: str | None = None,
        areas: list[str] | None = None,
        buscar_todos: bool = True,
    ) -> list[Tarefa]:
        """Lista as tarefas, opcionalmente filtrando por propriedades.

        Enriquece cada tarefa com os nomes das áreas relacionadas
        (``areas_nomes``), resolvidos via cache em memória.

        Args:
            status: Quando informado, retorna só as tarefas nesse status.
            duracao: Quando informado, filtra pela coluna de duração/esforço.
            areas: IDs de áreas relacionadas; todas devem estar presentes.
            buscar_todos: Percorre toda a paginação (padrão).

        Returns:
            As tarefas normalizadas e enriquecidas.
        """

        filtros: list[dict[str, Any]] = []
        if status is not None:
            filtros.append({"property": self._campos.status, "status": {"equals": status}})
        if duracao is not None:
            filtros.append({"property": self._campos.duracao, "status": {"equals": duracao}})
        for area_id in areas or []:
            filtros.append({"property": self._campos.areas, "relation": {"contains": area_id}})

        paginas = self._client.consultar_database(
            self._database_id,
            buscar_todos=buscar_todos,
            filtro=_combinar_filtros(filtros),
        )
        tarefas = [tarefa_de_pagina(pg, self._campos) for pg in paginas]
        self._enriquecer_areas(tarefas)
        return tarefas

    def opcoes(self) -> dict[str, Any]:
        """Lê os valores possíveis para seletores (status, duração, áreas).

        Usa o schema do database para status/duração e consulta o database
        relacionado para áreas.

        Returns:
            ``{"status": [...], "duracao": [...], "areas": [{"id": ..., "nome": ...}]}``.
        """

        schema = self._client.get_database(self._database_id)
        props = schema.get("properties", {})

        status_opcoes = _extrair_opcoes_status(props.get(self._campos.status, {}))
        duracao_opcoes = _extrair_opcoes_status(props.get(self._campos.duracao, {}))

        areas: list[dict[str, str]] = []
        areas_prop = props.get(self._campos.areas, {})
        areas_db_id = (areas_prop.get("relation") or {}).get("database_id")
        if areas_db_id:
            paginas = self._client.consultar_database(areas_db_id, buscar_todos=True)
            for pg in paginas:
                nome = _texto_title_de_pagina(pg)
                if nome:
                    areas.append({"id": pg["id"], "nome": nome})
                    self._cache_areas[pg["id"]] = nome

        return {"status": status_opcoes, "duracao": duracao_opcoes, "areas": areas}

    # -- Escrita ---------------------------------------------------------------

    def criar(
        self,
        nome: str,
        status: str | None = None,
        prazo: str | None = None,
        duracao: str | None = None,
        areas: list[str] | None = None,
    ) -> Tarefa:
        """Cria uma tarefa nova no database.

        Args:
            nome: Título da tarefa.
            status: Etapa inicial (deve existir no database).
            prazo: Data do prazo (ISO, ex.: ``"2026-07-01"``).
            duracao: Nome da duração/esforço (deve existir no database).
            areas: IDs das páginas de "Áreas da vida" a relacionar.

        Returns:
            A tarefa criada.
        """

        propriedades: dict[str, Any] = {self._campos.nome: p.title(nome)}
        if status is not None:
            propriedades[self._campos.status] = p.status(status)
        if prazo is not None:
            propriedades[self._campos.prazo] = p.date(prazo)
        if duracao is not None:
            propriedades[self._campos.duracao] = p.status(duracao)
        if areas is not None:
            propriedades[self._campos.areas] = p.relation(areas)

        pagina = self._client.criar_pagina(self._database_id, propriedades)
        tarefa = tarefa_de_pagina(pagina, self._campos)
        self._enriquecer_areas([tarefa])
        return tarefa

    def editar(
        self,
        task_id: str,
        *,
        nome: str | None = None,
        status: str | None = None,
        prazo: str | None = None,
        duracao: str | None = None,
        areas: list[str] | None = None,
    ) -> Tarefa:
        """Edita uma tarefa existente (um ou mais campos).

        Aceita qualquer subconjunto dos campos; ao menos um deve ser informado.
        Mover/concluir continua sendo mudar ``status``.

        Args:
            task_id: ID da página (a tarefa).
            nome: Novo título.
            status: Novo status.
            prazo: Nova data de prazo (ISO).
            duracao: Nova duração/esforço.
            areas: Novos IDs de áreas relacionadas.

        Returns:
            A tarefa atualizada.

        Raises:
            ValueError: Se nenhum campo for informado.
        """

        propriedades: dict[str, Any] = {}
        if nome is not None:
            propriedades[self._campos.nome] = p.title(nome)
        if status is not None:
            propriedades[self._campos.status] = p.status(status)
        if prazo is not None:
            propriedades[self._campos.prazo] = p.date(prazo)
        if duracao is not None:
            propriedades[self._campos.duracao] = p.status(duracao)
        if areas is not None:
            propriedades[self._campos.areas] = p.relation(areas)

        if not propriedades:
            raise ValueError("Ao menos um campo deve ser informado para editar.")

        pagina = self._client.atualizar_pagina(task_id, propriedades)
        tarefa = tarefa_de_pagina(pagina, self._campos)
        self._enriquecer_areas([tarefa])
        return tarefa

    def atualizar_status(self, task_id: str, status: str) -> Tarefa:
        """Muda o status de uma tarefa existente.

        Atalho para ``editar(task_id, status=status)``.
        """

        return self.editar(task_id, status=status)

    def concluir(self, task_id: str, status_concluido: str) -> Tarefa:
        """Marca uma tarefa como concluída usando o status de conclusão do workspace."""

        return self.atualizar_status(task_id, status_concluido)

    # -- Internos --------------------------------------------------------------

    def _enriquecer_areas(self, tarefas: list[Tarefa]) -> None:
        """Preenche ``areas_nomes`` das tarefas usando o cache de áreas.

        IDs que não estão no cache são consultados no Notion em lote.
        """

        ids_desconhecidos: set[str] = set()
        for t in tarefas:
            for aid in t.areas:
                if aid and aid not in self._cache_areas:
                    ids_desconhecidos.add(aid)

        if ids_desconhecidos:
            self._popular_cache_areas(ids_desconhecidos)

        for t in tarefas:
            t.areas_nomes = [self._cache_areas.get(aid, "") for aid in t.areas]

    def _popular_cache_areas(self, ids: set[str]) -> None:
        """Consulta o database de áreas e popula o cache.

        Busca o database relacionado (via schema) e carrega todas as páginas
        de uma vez — mais eficiente do que consultar página a página.
        """

        schema = self._client.get_database(self._database_id)
        props = schema.get("properties", {})
        areas_prop = props.get(self._campos.areas, {})
        areas_db_id = (areas_prop.get("relation") or {}).get("database_id")
        if not areas_db_id:
            return
        paginas = self._client.consultar_database(areas_db_id, buscar_todos=True)
        for pg in paginas:
            pid = pg.get("id", "")
            nome = _texto_title_de_pagina(pg)
            if pid:
                self._cache_areas[pid] = nome
