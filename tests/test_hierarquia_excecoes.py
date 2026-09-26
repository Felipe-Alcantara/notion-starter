"""Toda falha da biblioteca deriva de NotionSyncError (AGENTS.md do módulo).

A base builtin antiga continua como segunda base: quem já capturava
``ValueError``/``RuntimeError`` (a CLI e o MCP do app) segue igual, e quem
captura ``NotionSyncError`` passa a pegar todas.
"""

from __future__ import annotations

import pytest

from notion_starter.exceptions import NotionSyncError
from notion_starter.git_historico import GitIndisponivelError
from notion_starter.github import GitHubAPIError, GitHubConnectionError
from notion_starter.openrouter import CatalogoErro, ProvedorErro
from notion_starter.services.ia import InterpretacaoErro
from notion_starter.services.reordenacao import BlocoArriscadoError, BlocoImpossivelError


@pytest.mark.parametrize(
    "classe,base_antiga",
    [
        (BlocoArriscadoError, ValueError),
        (BlocoImpossivelError, ValueError),
        (InterpretacaoErro, ValueError),
        (GitIndisponivelError, RuntimeError),
        (CatalogoErro, RuntimeError),
        (ProvedorErro, RuntimeError),
        (GitHubAPIError, Exception),
        (GitHubConnectionError, Exception),
    ],
)
def test_excecoes_derivam_de_notion_sync_error_sem_perder_a_base_antiga(classe, base_antiga):
    assert issubclass(classe, NotionSyncError)
    assert issubclass(classe, base_antiga)


def test_github_api_error_mantem_a_assinatura():
    erro = GitHubAPIError(404, "x" * 600)
    assert erro.status_code == 404 and len(erro.body) == 500
