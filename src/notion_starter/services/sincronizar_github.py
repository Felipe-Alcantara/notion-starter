"""Caso de uso idempotente de sincronização GitHub → Notion."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from notion_starter.github import GitHubClient, RepoInfo

from notion_starter import NotionClient, TaskList, properties


@dataclass(frozen=True)
class CamposProjeto:
    """Nomes das propriedades do database de projetos."""

    nome: str = "Nome"
    descricao: str = "Descrição"
    url: str = "URL"
    homepage: str = "Homepage"
    linguagem: str = "Linguagem"
    topicos: str = "Tópicos"
    estrelas: str = "Estrelas"
    forks: str = "Forks"
    privado: str = "Privado"
    atualizado_em: str = "Atualizado em"


@dataclass
class ResumoSync:
    """Resultado de uma sincronização em lote."""

    repos_encontrados: int = 0
    paginas_criadas: int = 0
    paginas_atualizadas: int = 0
    tarefas_criadas: int = 0
    tarefas_existentes: int = 0
    erros: int = 0


def _propriedades_pagina(
    repo: RepoInfo,
    campos: CamposProjeto | None = None,
) -> dict[str, Any]:
    """Monta as propriedades de projeto sem expor JSON cru do GitHub."""

    c = campos or CamposProjeto()
    props: dict[str, Any] = {
        c.nome: properties.title(repo.nome_completo),
        c.estrelas: properties.number(repo.estrelas),
        c.forks: properties.number(repo.forks),
        c.privado: properties.checkbox(repo.privado),
    }
    if repo.descricao:
        props[c.descricao] = properties.rich_text(repo.descricao[:2000])
    if repo.url_html:
        props[c.url] = properties.url(repo.url_html)
    if repo.homepage:
        props[c.homepage] = properties.url(repo.homepage)
    if repo.linguagem:
        props[c.linguagem] = properties.select(repo.linguagem)
    if repo.topicos:
        props[c.topicos] = properties.multi_select(repo.topicos)
    if repo.atualizado_em:
        props[c.atualizado_em] = properties.date(repo.atualizado_em)
    return props


def _nome_tarefa(repo: RepoInfo) -> str:
    return f"Revisar repo: {repo.nome}"


def _propriedades_tarefa(repo: RepoInfo) -> dict[str, Any]:
    """Mantém o mapeamento puro disponível para consumidores sem ``TaskList``."""

    return {"Nome": properties.title(_nome_tarefa(repo))}


def _pagina_existente(
    client: NotionClient,
    database_id: str,
    repo: RepoInfo,
    campos: CamposProjeto,
) -> dict[str, Any] | None:
    if repo.url_html:
        filtro: dict[str, object] = {
            "property": campos.url,
            "url": {"equals": repo.url_html},
        }
    else:
        filtro = {
            "property": campos.nome,
            "title": {"equals": repo.nome_completo},
        }
    paginas = client.consultar_database(database_id, page_size=1, filtro=filtro)
    return paginas[0] if paginas else None


def sincronizar(
    usuario: str,
    *,
    github_client: GitHubClient | None = None,
    notion_client: NotionClient | None = None,
    tasklist: TaskList | None = None,
    database_projetos_id: str | None = None,
    database_tarefas_id: str | None = None,
    campos_projeto: CamposProjeto | None = None,
    status_tarefa: str | None = None,
) -> ResumoSync:
    """Sincroniza repositórios como páginas e tarefas sem criar duplicatas."""

    github_client = github_client or GitHubClient()
    if notion_client is None:
        from integrations.notion import criar_cliente

        notion_client = criar_cliente()

    db_projetos = database_projetos_id or os.environ.get("NOTION_PROJECTS_DATABASE_ID", "").strip()
    if not db_projetos:
        raise ValueError(
            "database_projetos_id é obrigatório. Passe como argumento ou defina "
            "NOTION_PROJECTS_DATABASE_ID no ambiente."
        )

    if tasklist is None:
        db_tarefas = database_tarefas_id or os.environ.get("NOTION_DATABASE_ID", "").strip()
        if not db_tarefas:
            raise ValueError(
                "database_tarefas_id é obrigatório. Passe como argumento ou defina "
                "NOTION_DATABASE_ID no ambiente."
            )
        tasklist = TaskList(notion_client, db_tarefas)

    campos = campos_projeto or CamposProjeto()
    repos = github_client.listar_repos(usuario)
    resumo = ResumoSync(repos_encontrados=len(repos))
    nomes_tarefas = {tarefa.nome for tarefa in tasklist.listar()}

    for repo in repos:
        try:
            props = _propriedades_pagina(repo, campos)
            existente = _pagina_existente(
                notion_client,
                db_projetos,
                repo,
                campos,
            )
            if existente and existente.get("id"):
                notion_client.atualizar_pagina(str(existente["id"]), props)
                resumo.paginas_atualizadas += 1
            else:
                notion_client.criar_pagina(db_projetos, props)
                resumo.paginas_criadas += 1
        except Exception:
            resumo.erros += 1

        nome_tarefa = _nome_tarefa(repo)
        if nome_tarefa in nomes_tarefas:
            resumo.tarefas_existentes += 1
            continue
        try:
            tasklist.criar(nome_tarefa, status=status_tarefa)
            nomes_tarefas.add(nome_tarefa)
            resumo.tarefas_criadas += 1
        except Exception:
            resumo.erros += 1

    return resumo
