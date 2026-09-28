"""Caso de uso: inventário plano do workspace, com datas, caminho e colunas.

Uma única busca paginada (``/search`` sem termo) devolve tudo o que a
integração enxerga, já com ``created_time`` e ``last_edited_time``. Medido em
2026-09-27: 3.841 itens em 62 s. Cada item vira um :class:`RegistroWorkspace`
com o **caminho** de ancestrais (títulos da raiz até o pai) e as colunas
preenchidas das linhas de database — o suficiente para ordenar ideias pela data
em que foram anotadas e decidir o que baixar (``services.corpos``) sem
consultar a API de novo.

O inventário é gravado em JSON (``{"versao": 1, "gerado_em", "total",
"itens"}``); :func:`carregar_inventario` também aceita a lista pura de itens.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from notion_starter import NotionClient
from notion_starter.exceptions import NotionSyncError
from notion_starter.inventory import normalizar_item
from notion_starter.readers import extrair_valores

VERSAO_INVENTARIO = 1

#: Valores que não carregam informação e ficam fora de ``propriedades``.
_VAZIOS: tuple[Any, ...] = (None, "", [], False)

#: Proteção contra ciclos ao subir pelos pais.
LIMITE_CAMINHO = 12


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


class InventarioInvalidoError(NotionSyncError, ValueError):
    """O arquivo de inventário não pôde ser lido ou não tem o formato esperado."""


@dataclass
class RegistroWorkspace:
    """Página ou database do workspace, reduzido ao que a triagem precisa.

    Attributes:
        id: ID do item (com hífens, como a API devolve).
        objeto: ``"page"`` ou ``"database"``.
        titulo: Título legível.
        criado_em: ``created_time`` (ISO 8601).
        editado_em: ``last_edited_time`` (ISO 8601).
        pai_tipo: ``workspace``, ``page_id``, ``database_id`` ou ``block_id``.
        pai_id: ID do pai, quando houver.
        caminho: Títulos dos ancestrais conhecidos, da raiz até o pai.
        url: Link do item.
        arquivado: Item arquivado ou na lixeira.
        propriedades: Colunas preenchidas (valores simples), para linhas.
    """

    id: str
    objeto: str
    titulo: str
    criado_em: str | None
    editado_em: str | None
    pai_tipo: str
    pai_id: str | None
    caminho: list[str] = field(default_factory=list)
    url: str | None = None
    arquivado: bool = False
    propriedades: dict[str, Any] = field(default_factory=dict)

    @property
    def caminho_completo(self) -> tuple[str, ...]:
        """Caminho dos ancestrais seguido do próprio título."""

        return (*self.caminho, self.titulo)

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return asdict(self)

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> RegistroWorkspace:
        """Reconstrói um registro gravado por :meth:`para_dict` (ignora chaves extras)."""

        campos = cls.__dataclass_fields__
        return cls(**{chave: valor for chave, valor in dados.items() if chave in campos})


def normalizar_registro(cru: dict[str, Any]) -> RegistroWorkspace:
    """Converte um item cru do ``/search`` em :class:`RegistroWorkspace`."""

    item = normalizar_item(cru)
    valores = extrair_valores(cru) if cru.get("object") == "page" else {}
    return RegistroWorkspace(
        id=item.id,
        objeto=item.tipo,
        titulo=item.titulo,
        criado_em=cru.get("created_time"),
        editado_em=cru.get("last_edited_time"),
        pai_tipo=item.parent_tipo,
        pai_id=item.parent_id,
        url=item.url,
        arquivado=bool(cru.get("archived") or cru.get("in_trash")),
        propriedades={k: v for k, v in valores.items() if v not in _VAZIOS},
    )


def _chave(identificador: str | None) -> str:
    return str(identificador or "").replace("-", "").lower()


def preencher_caminhos(registros: list[RegistroWorkspace], limite: int = LIMITE_CAMINHO) -> None:
    """Preenche ``caminho`` de cada registro subindo pelos pais conhecidos.

    Pais fora do conjunto (ex.: blocos de coluna, que o ``/search`` não
    devolve) encerram a subida; ``limite`` protege contra ciclos.
    """

    por_id = {_chave(r.id): r for r in registros}
    for registro in registros:
        caminho: list[str] = []
        visitados = {_chave(registro.id)}
        atual = por_id.get(_chave(registro.pai_id))
        while atual is not None and len(caminho) < limite and _chave(atual.id) not in visitados:
            caminho.append(atual.titulo)
            visitados.add(_chave(atual.id))
            atual = por_id.get(_chave(atual.pai_id))
        registro.caminho = list(reversed(caminho))


def varrer_workspace(
    *,
    filtro: str | None = None,
    cliente: NotionClient | None = None,
) -> list[RegistroWorkspace]:
    """Lista tudo o que a integração enxerga, normalizado e com caminhos.

    Args:
        filtro: ``"page"`` ou ``"database"`` para limitar o ``/search``;
            ``None`` traz os dois. Com filtro, os pais do outro tipo não vêm
            na busca e o ``caminho`` para neles.
        cliente: Cliente Notion opcional (injeção para testes).

    Raises:
        ValueError: ``filtro`` diferente de ``page``/``database``.
    """

    if filtro not in (None, "page", "database"):
        raise ValueError("filtro deve ser 'page' ou 'database'.")
    cli = cliente or _cliente_padrao()
    filtro_api = {"property": "object", "value": filtro} if filtro else None
    registros = [
        normalizar_registro(cru) for cru in cli.buscar(buscar_todos=True, filtro=filtro_api)
    ]
    preencher_caminhos(registros)
    return registros


def gravar_texto_atomico(destino: Path, texto: str) -> None:
    """Grava ``texto`` num arquivo temporário e troca de nome no fim.

    Uma interrupção (rede, Ctrl+C, disco cheio) nunca deixa um arquivo pela
    metade com o nome final — quem retoma pelo nome não pula um arquivo
    truncado.
    """

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".parcial")
    temporario.write_text(texto, encoding="utf-8")
    os.replace(temporario, destino)


def salvar_inventario(registros: list[RegistroWorkspace], destino: Path | str) -> Path:
    """Grava o inventário em JSON (UTF-8, legível) e devolve o caminho."""

    destino = Path(destino)
    documento = {
        "versao": VERSAO_INVENTARIO,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(registros),
        "itens": [r.para_dict() for r in registros],
    }
    gravar_texto_atomico(
        destino, json.dumps(documento, ensure_ascii=False, indent=1, default=str)
    )
    return destino


def carregar_inventario(origem: Path | str) -> list[RegistroWorkspace]:
    """Lê um inventário gravado por :func:`salvar_inventario` (ou a lista pura).

    Raises:
        InventarioInvalidoError: Arquivo ausente, JSON inválido ou formato estranho.
    """

    origem = Path(origem)
    try:
        dados = json.loads(origem.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InventarioInvalidoError(f"Não foi possível ler o inventário {origem}: {exc}") from exc
    itens = dados.get("itens") if isinstance(dados, dict) else dados
    if not isinstance(itens, list) or not all(isinstance(i, dict) and "id" in i for i in itens):
        raise InventarioInvalidoError(
            f"{origem} não é um inventário: esperava uma lista de itens com 'id'."
        )
    return [RegistroWorkspace.de_dict(item) for item in itens]


def resumir(registros: list[RegistroWorkspace]) -> dict[str, Any]:
    """Contagens rápidas para mostrar depois de uma varredura."""

    datas = sorted(r.criado_em for r in registros if r.criado_em)
    return {
        "total": len(registros),
        "paginas": sum(1 for r in registros if r.objeto == "page"),
        "databases": sum(1 for r in registros if r.objeto == "database"),
        "arquivados": sum(1 for r in registros if r.arquivado),
        "criado_mais_antigo": datas[0] if datas else None,
        "criado_mais_recente": datas[-1] if datas else None,
    }
