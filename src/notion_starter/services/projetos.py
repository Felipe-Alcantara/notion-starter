"""Casos de uso de páginas de projeto no Notion."""

from __future__ import annotations

from dataclasses import dataclass

from notion_starter.github import RepoInfo

from notion_starter import NotionClient
from notion_starter.services.sincronizar_github import CamposProjeto, _propriedades_pagina


@dataclass(frozen=True)
class ProjetoAtualizado:
    """Referência pública de uma página de projeto atualizada."""

    id: str
    url: str | None = None


def atualizar_pagina_projeto(
    page_id: str,
    repo: RepoInfo,
    *,
    notion_client: NotionClient | None = None,
    campos: CamposProjeto | None = None,
) -> ProjetoAtualizado:
    """Atualiza uma página de projeto com metadados normalizados do GitHub."""

    if notion_client is None:
        from integrations.notion import criar_cliente

        notion_client = criar_cliente()

    pagina = notion_client.atualizar_pagina(
        page_id,
        _propriedades_pagina(repo, campos),
    )
    return ProjetoAtualizado(
        id=str(pagina.get("id") or page_id),
        url=str(pagina["url"]) if pagina.get("url") else None,
    )
