"""Casos de uso de tarefas — a regra de negócio fina sobre a ``TaskList``.

Cada função é um caso de uso: recebe dados simples, delega à ``TaskList`` do
``notion_starter`` e devolve objetos :class:`Tarefa`. Esta camada **não conhece
HTTP** (isso é da camada ``api``) nem o **formato cru do Notion** (isso é do
``notion_starter``) — é a fronteira de negócio do servidor.

A ``TaskList`` é resolvida da configuração do servidor por padrão, mas pode ser
**injetada** (testes, ou um database alternativo). Isso mantém estas funções
puras e testáveis sem token nem rede real.
"""

from __future__ import annotations

from typing import Any

from notion_starter import Tarefa, TaskList


def _titulo_database(database: dict[str, Any]) -> str:
    """Extrai o título legível de um database do Notion."""

    partes = database.get("title", [])
    titulo = "".join(parte.get("plain_text", "") for parte in partes).strip()
    return titulo or "(sem título)"


def _nomes_data_sources(fontes: list[dict[str, Any]]) -> list[str]:
    """Extrai nomes das fontes de dados do modelo novo do Notion."""

    nomes = []
    for fonte in fontes:
        nome = str(fonte.get("name") or "").strip()
        if nome:
            nomes.append(nome)
    return nomes


def _tasklist_padrao() -> TaskList:
    """Resolve a ``TaskList`` a partir da configuração do servidor.

    Import tardio de propósito: evita acoplar a camada de casos de uso ao Django
    no momento do import — a configuração só é tocada quando nenhuma ``TaskList``
    é injetada (uso real), nunca nos testes que injetam a sua própria.
    """

    from integrations.notion import criar_tasklist

    return criar_tasklist()


def listar_tarefas(
    status: str | None = None,
    duracao: str | None = None,
    areas: list[str] | None = None,
    *,
    tasklist: TaskList | None = None,
) -> list[Tarefa]:
    """Lista as tarefas, opcionalmente filtrando por propriedades do Notion."""

    return (tasklist or _tasklist_padrao()).listar(status=status, duracao=duracao, areas=areas)


def criar_tarefa(
    nome: str,
    status: str | None = None,
    prazo: str | None = None,
    duracao: str | None = None,
    areas: list[str] | None = None,
    *,
    tasklist: TaskList | None = None,
) -> Tarefa:
    """Cria uma tarefa nova (todos os campos exceto ``nome`` são opcionais)."""

    return (tasklist or _tasklist_padrao()).criar(
        nome, status=status, prazo=prazo, duracao=duracao, areas=areas
    )


def editar_tarefa(
    task_id: str,
    *,
    nome: str | None = None,
    status: str | None = None,
    prazo: str | None = None,
    duracao: str | None = None,
    areas: list[str] | None = None,
    tasklist: TaskList | None = None,
) -> Tarefa:
    """Edita uma tarefa existente (um ou mais campos).

    Retrocompatível: ``editar_tarefa(id, status=...)`` faz o mesmo que o antigo
    ``mover_status``.
    """

    return (tasklist or _tasklist_padrao()).editar(
        task_id, nome=nome, status=status, prazo=prazo, duracao=duracao, areas=areas
    )


def listar_opcoes(
    *,
    tasklist: TaskList | None = None,
) -> dict[str, Any]:
    """Retorna os valores possíveis para seletores (status, duração, áreas)."""

    return (tasklist or _tasklist_padrao()).opcoes()


def obter_database_atual() -> dict[str, Any]:
    """Retorna o contexto da database de tarefas ativa no servidor."""

    from core.config import carregar_config
    from integrations.notion import criar_cliente

    cfg = carregar_config()
    if not cfg.notion_database_id:
        raise ValueError("NOTION_DATABASE_ID não configurado.")

    cliente = criar_cliente()
    database = cliente.get_database(cfg.notion_database_id)
    fontes = cliente.listar_data_sources(cfg.notion_database_id)
    return {
        "id": cfg.notion_database_id,
        "titulo": _titulo_database(database),
        "url": database.get("url", ""),
        "data_sources": _nomes_data_sources(fontes),
    }


def mover_status(
    task_id: str,
    status: str,
    *,
    tasklist: TaskList | None = None,
) -> Tarefa:
    """Move uma tarefa existente para outro ``status``."""

    return (tasklist or _tasklist_padrao()).atualizar_status(task_id, status)


def concluir_tarefa(
    task_id: str,
    status_concluido: str,
    *,
    tasklist: TaskList | None = None,
) -> Tarefa:
    """Conclui uma tarefa usando o status de "feito" do workspace.

    Helper de negócio para quem conhece o status de conclusão (IA/MCP); a borda
    HTTP conclui movendo o status pela rota ``PATCH`` comum.
    """

    return (tasklist or _tasklist_padrao()).concluir(task_id, status_concluido)
