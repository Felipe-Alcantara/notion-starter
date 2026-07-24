"""Caso de uso: reordenar um bloco existente dentro da mesma página.

A API do Notion não tem endpoint para mover um bloco já criado — a única forma
é ler seu conteúdo, apagar o original e recriar na posição desejada (`position:
after_block`, ver :meth:`NotionClient.anexar_blocos`). Isso é seguro para
blocos de **conteúdo puro** (heading, paragraph, divider, bulleted_list_item,
…), mas tem duas restrições sérias para páginas/databases filhos:

- **`child_database` nunca pode ser recriado por este caminho.**
  `PATCH /blocks/{id}/children` cria blocos de conteúdo — não sabe recriar um
  database com schema; o único jeito de criar um database é
  `POST /databases`, um endpoint totalmente diferente. Reordenar um
  `child_database` por aqui **apaga o original e falha ao recriar**,
  perdendo o database (embora de forma reversível — o Notion arquiva, não
  destrói; ver a lixeira do workspace). Por isso :func:`reordenar_bloco`
  **recusa `child_database` sempre**, sem flag de escape.
- **`child_page` pode ser recriado**, mas com **ID novo** — apagar e recriar
  gera uma página nova, quebrando qualquer link, backlink ou referência
  externa salva para o ID antigo (a Notion API não oferece um jeito de
  preservar o ID nesse caso; o endpoint de "mover página" só cobre re-parent,
  não reordenação de blocos-filhos). Por isso exige
  ``forcar_tipos_arriscados=True`` explicitamente.

Mesmo nos casos permitidos, sempre grava um backup do bloco original em disco
antes de apagar, para permitir reconstrução manual se algo sair errado.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_starter import NotionClient

#: Tipos de bloco cuja identidade (ID) é dispensável ao recriar — reordenar é seguro.
_TIPOS_SEGUROS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
        "divider",
        "code",
    }
)

#: `child_page` pode ser recriado (com ID novo — quebra referências externas),
#: mas exige confirmação explícita via forcar_tipos_arriscados.
_TIPOS_ARRISCADOS = frozenset({"child_page"})

#: `child_database` nunca pode ser recriado por anexar_blocos — o único jeito
#: de criar um database é o endpoint POST /databases, não PATCH .../children.
#: Recusado sempre, mesmo com forcar_tipos_arriscados=True.
_TIPOS_IMPOSSIVEIS = frozenset({"child_database"})


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


@dataclass
class ResultadoReordenacao:
    """Resultado de :func:`reordenar_bloco`."""

    bloco_id_antigo: str
    bloco_id_novo: str
    tipo: str
    backup_path: str
    id_mudou: bool


class BlocoArriscadoError(ValueError):
    """Levantado ao tentar reordenar `child_page` sem confirmar o risco de ID novo."""


class BlocoImpossivelError(ValueError):
    """Levantado ao tentar reordenar `child_database` — nunca suportado, nem forçado."""


def _bloco_por_id(cliente: NotionClient, pagina_id: str, bloco_id: str) -> dict[str, Any]:
    for bloco in cliente.ler_blocos(pagina_id, buscar_todos=True):
        if bloco.get("id") == bloco_id:
            return bloco
    raise ValueError(f"Bloco {bloco_id} não encontrado como filho direto de {pagina_id}.")


def _salvar_backup(bloco: dict[str, Any], *, diretorio: Path) -> Path:
    diretorio.mkdir(parents=True, exist_ok=True)
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    caminho = diretorio / f"bloco-{bloco.get('id', 'sem-id')}-{carimbo}.json"
    caminho.write_text(json.dumps(bloco, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def reordenar_bloco(
    pagina_id: str,
    bloco_id: str,
    *,
    apos_bloco_id: str | None = None,
    inicio: bool = False,
    forcar_tipos_arriscados: bool = False,
    diretorio_backup: Path | str = Path(".notion-backups"),
    cliente: NotionClient | None = None,
) -> ResultadoReordenacao:
    """Reordena um bloco existente dentro da mesma página pai.

    Implementado como apagar + recriar na posição pedida, já que a API do
    Notion não move blocos existentes. Sempre grava um backup em JSON do bloco
    original antes de apagar (``diretorio_backup``), para permitir reconstrução
    manual em caso de falha no meio do processo.

    Args:
        pagina_id: ID da página (ou bloco) que contém ``bloco_id`` como filho direto.
        bloco_id: ID do bloco a mover.
        apos_bloco_id: Move o bloco para logo após este bloco irmão. Exclusivo
            com ``inicio``.
        inicio: Quando verdadeiro, move o bloco para o início da lista de
            filhos. Exclusivo com ``apos_bloco_id``.
        forcar_tipos_arriscados: **Necessário** para mover um `child_page` —
            apagar e recriar gera um **ID novo**, quebrando links/backlinks/
            referências salvas para o ID antigo. Sem esta flag, `child_page`
            levanta :class:`BlocoArriscadoError`. Não afeta `child_database`,
            que é recusado sempre — ver :class:`BlocoImpossivelError`.
        diretorio_backup: Pasta onde o backup do bloco é salvo antes de apagar.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        :class:`ResultadoReordenacao` com o ID antigo, o novo (pode ser
        diferente!), o caminho do backup e se o ID mudou.

    Raises:
        ValueError: Se nem ``apos_bloco_id`` nem ``inicio`` forem informados
            (ou ambos ao mesmo tempo), ou se o bloco não for encontrado.
        BlocoArriscadoError: Ao mover `child_page` sem
            ``forcar_tipos_arriscados=True``.
        BlocoImpossivelError: Ao tentar mover um `child_database` — a API do
            Notion não permite recriar um database por este caminho, em
            nenhuma circunstância. Recrie manualmente com
            ``criar_database``/``importar_planilha``.
    """

    if bool(apos_bloco_id) == bool(inicio):
        raise ValueError("Informe exatamente um entre apos_bloco_id e inicio.")

    cli = cliente or _cliente_padrao()
    bloco = _bloco_por_id(cli, pagina_id, bloco_id)
    tipo = str(bloco.get("type") or "")

    if tipo in _TIPOS_IMPOSSIVEIS:
        raise BlocoImpossivelError(
            f"'{tipo}' não pode ser reordenado: a API do Notion não recria um database "
            "com PATCH .../children (só POST /databases). Apagar o original perderia o "
            "schema e as linhas. Recrie manualmente na posição certa com criar-database "
            "+ importar-planilha."
        )

    if tipo in _TIPOS_ARRISCADOS and not forcar_tipos_arriscados:
        raise BlocoArriscadoError(
            f"'{tipo}' é uma página filha — apagar e recriar para reordenar "
            "gera um ID novo e quebra links/backlinks para o ID atual. Recrie manualmente "
            "ou repita com forcar_tipos_arriscados=True se aceita esse risco."
        )

    backup_path = _salvar_backup(bloco, diretorio=Path(diretorio_backup))

    conteudo = {k: v for k, v in bloco.items() if k not in {"id", "created_time",
                "last_edited_time", "created_by", "last_edited_by", "has_children",
                "archived", "in_trash", "parent", "object"}}

    cli.excluir_bloco(bloco_id)
    posicao = {} if inicio else {"apos_bloco_id": apos_bloco_id}
    resposta = cli.anexar_blocos(pagina_id, [conteudo], **posicao)
    criados = resposta.get("results") or []
    novo_id = str(criados[0].get("id")) if criados else ""

    return ResultadoReordenacao(
        bloco_id_antigo=bloco_id,
        bloco_id_novo=novo_id or bloco_id,
        tipo=tipo,
        backup_path=str(backup_path),
        id_mudou=bool(novo_id) and novo_id != bloco_id,
    )
