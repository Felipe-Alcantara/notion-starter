"""Ingestão extensível de fontes externas para o Notion.

Fontes apenas coletam e normalizam itens. O caso de uso :func:`ingerir`
coordena criação/atualização no Notion e mantém o fluxo idempotente pela
propriedade ``Origem``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from notion_starter import NotionClient, properties

LIMITE_TEXTO_NOTION = 2000
EXTENSOES_TEXTO = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@runtime_checkable
class Fonte(Protocol):
    """Contrato implementado por qualquer origem de dados ingerível."""

    def coletar(self) -> Iterable[ItemColetado]:
        """Itera sobre os itens disponíveis na fonte."""
        ...


@dataclass
class ItemColetado:
    """Item normalizado produzido por uma fonte."""

    nome: str
    tipo_fonte: str
    conteudo: str = ""
    metadados: dict[str, Any] = field(default_factory=dict)
    origem: str = ""


@dataclass
class ResultadoIngestao:
    """Resumo de uma operação de ingestão em lote."""

    criados: int = 0
    atualizados: int = 0
    erros: int = 0
    itens_processados: int = 0


class FonteArquivos:
    """Coleta arquivos de uma pasta, com metadados e prévia textual segura."""

    def __init__(
        self,
        pasta: str | Path,
        *,
        extensoes: list[str] | None = None,
        recursivo: bool = True,
        max_caracteres: int = LIMITE_TEXTO_NOTION,
    ) -> None:
        if max_caracteres < 0:
            raise ValueError("max_caracteres não pode ser negativo.")
        self._pasta = Path(pasta)
        self._extensoes = (
            {self._normalizar_extensao(ext) for ext in extensoes} if extensoes is not None else None
        )
        self._recursivo = recursivo
        self._max_caracteres = max_caracteres

    @staticmethod
    def _normalizar_extensao(extensao: str) -> str:
        limpa = extensao.strip().lower()
        if not limpa:
            raise ValueError("extensoes não pode conter valores vazios.")
        return limpa if limpa.startswith(".") else f".{limpa}"

    def coletar(self) -> Iterable[ItemColetado]:
        if not self._pasta.is_dir():
            return

        candidatos = self._pasta.rglob("*") if self._recursivo else self._pasta.iterdir()
        for arquivo in sorted(candidatos):
            if arquivo.is_symlink() or not arquivo.is_file():
                continue
            extensao = arquivo.suffix.lower()
            if self._extensoes is not None and extensao not in self._extensoes:
                continue

            tamanho = arquivo.stat().st_size
            origem = arquivo.relative_to(self._pasta).as_posix()
            conteudo = self._conteudo(arquivo, tamanho)
            yield ItemColetado(
                nome=arquivo.name,
                tipo_fonte="arquivos",
                conteudo=conteudo,
                metadados={
                    "extensao": extensao,
                    "tamanho_bytes": tamanho,
                    "caminho_relativo": origem,
                },
                origem=origem,
            )

    def _conteudo(self, arquivo: Path, tamanho: int) -> str:
        resumo = f"Arquivo {arquivo.suffix or 'sem extensão'} ({tamanho} bytes)"
        if arquivo.suffix.lower() not in EXTENSOES_TEXTO or self._max_caracteres == 0:
            return resumo
        try:
            previa = arquivo.read_text(encoding="utf-8", errors="replace")[
                : self._max_caracteres
            ].strip()
        except OSError:
            return resumo
        return previa or resumo


class FonteGitHub:
    """Converte repositórios de um usuário em :class:`ItemColetado`."""

    def __init__(self, usuario: str, *, github_client: Any = None) -> None:
        self._usuario = usuario
        self._github_client = github_client

    def _resolver_client(self) -> Any:
        if self._github_client is not None:
            return self._github_client
        from notion_starter.github import GitHubClient

        return GitHubClient()

    def coletar(self) -> Iterable[ItemColetado]:
        for repo in self._resolver_client().listar_repos(self._usuario):
            yield ItemColetado(
                nome=repo.nome,
                tipo_fonte="github",
                conteudo=repo.descricao or "",
                metadados={
                    "linguagem": repo.linguagem,
                    "estrelas": repo.estrelas,
                    "forks": repo.forks,
                    "topicos": repo.topicos,
                    "privado": repo.privado,
                    "url_html": repo.url_html,
                    "atualizado_em": repo.atualizado_em,
                },
                origem=repo.nome_completo,
            )


def _limitar_texto(valor: str) -> str:
    return valor[:LIMITE_TEXTO_NOTION]


def _propriedades_de_item(item: ItemColetado) -> dict[str, Any]:
    nome = item.nome.strip()
    tipo_fonte = item.tipo_fonte.strip()
    if not nome:
        raise ValueError("ItemColetado.nome não pode estar vazio.")
    if not tipo_fonte:
        raise ValueError("ItemColetado.tipo_fonte não pode estar vazio.")

    props: dict[str, Any] = {
        "Nome": properties.title(_limitar_texto(nome)),
        "Fonte": properties.select(tipo_fonte),
    }
    if item.conteudo:
        props["Descrição"] = properties.rich_text(_limitar_texto(item.conteudo))
    if item.origem:
        props["Origem"] = properties.rich_text(_limitar_texto(item.origem))
    return props


def _pagina_por_origem(
    client: NotionClient,
    database_id: str,
    origem: str,
) -> dict[str, Any] | None:
    if not origem:
        return None
    paginas = client.consultar_database(
        database_id,
        page_size=1,
        filtro={
            "property": "Origem",
            "rich_text": {"equals": _limitar_texto(origem)},
        },
    )
    return paginas[0] if paginas else None


def ingerir(
    fonte: Fonte,
    *,
    client: NotionClient | None = None,
    database_id: str | None = None,
) -> ResultadoIngestao:
    """Cria ou atualiza no Notion os itens produzidos por ``fonte``."""

    if client is None:
        from integrations.notion import criar_cliente

        client = criar_cliente()

    db_id = database_id or os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_id:
        raise ValueError(
            "database_id é obrigatório. Passe como argumento ou defina "
            "NOTION_DATABASE_ID no ambiente."
        )

    resultado = ResultadoIngestao()
    for item in fonte.coletar():
        resultado.itens_processados += 1
        try:
            props = _propriedades_de_item(item)
            existente = _pagina_por_origem(client, db_id, item.origem)
            if existente and existente.get("id"):
                client.atualizar_pagina(str(existente["id"]), props)
                resultado.atualizados += 1
            else:
                client.criar_pagina(db_id, props)
                resultado.criados += 1
        except Exception:
            # Ingestão é lote: uma fonte inválida ou item rejeitado não impede
            # os itens seguintes. O resumo mantém a falha observável.
            resultado.erros += 1

    return resultado
