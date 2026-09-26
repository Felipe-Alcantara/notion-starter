"""Caso de uso: reordenar um bloco existente dentro da mesma página.

A API do Notion não tem endpoint para mover um bloco já criado — a única forma
é criar uma **cópia** na posição desejada e apagar o original
(``PATCH /blocks/{id}/children`` com ``position``, ver
:meth:`NotionClient.anexar_blocos`). Isso só é seguro para blocos de
**conteúdo puro**, e mesmo assim numa ordem que nunca deixe a página sem o
bloco:

1. **validar tudo antes de escrever** — o tipo precisa estar em
   :data:`_TIPOS_SEGUROS` (lista branca; ``table``, ``column_list``,
   ``synced_block``, ``image``… não passam), o bloco não pode ter filhos e o
   texto precisa ser regravável;
2. gravar o backup em JSON (fora do diretório corrente, ver
   :mod:`notion_starter.services.backups`);
3. **anexar a cópia** na posição pedida (``start`` ou ``after_block``) e
   conferir o ID que a API devolveu;
4. **só então apagar o original**.

Se a cópia falhar, nada foi apagado. Se a exclusão falhar depois, sobra uma
duplicata (recuperável) — e :class:`ReordenacaoIncompletaError` diz qual é o ID
novo e onde está o backup.

Tipos recusados sempre:

- ``child_database``: a API só cria database por ``POST /databases``;
- ``child_page``: a API só cria página por ``POST /pages`` — o append recusa
  ``child_page`` (medido: HTTP 400), então "forçar" apenas mandava a
  subpágina inteira para a lixeira. Reordenar uma subpágina não é possível pela
  API; faça na interface do Notion.

Blocos com filhos (toggle, item de lista com subitens, heading toggleável…) são
recusados: a cópia sairia sem os filhos e o original levaria os filhos para a
lixeira junto com ele.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from notion_starter import NotionClient
from notion_starter.content import rich_text_para_requisicao
from notion_starter.exceptions import (
    NotionConnectionError,
    NotionSyncError,
    RichTextNaoRegravavelError,
)
from notion_starter.services.backups import salvar_backup_json
from notion_starter.utils import chave_de_id, extrair_id

#: Tipos que se recriam por ``PATCH .../children`` sem perda — a lista branca.
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

#: Campos **graváveis** de cada tipo seguro. A cópia é montada só com eles, e
#: não com "o bloco lido menos os metadados": a leitura traz campos que a
#: escrita recusa — medido, um ``paragraph`` vem com ``"icon": null`` e a API
#: responde 400 ("paragraph.icon should be an object or `undefined`").
_CAMPOS_GRAVAVEIS: dict[str, tuple[str, ...]] = {
    "paragraph": ("rich_text", "color", "icon"),
    "heading_1": ("rich_text", "color", "is_toggleable"),
    "heading_2": ("rich_text", "color", "is_toggleable"),
    "heading_3": ("rich_text", "color", "is_toggleable"),
    "bulleted_list_item": ("rich_text", "color"),
    "numbered_list_item": ("rich_text", "color"),
    "to_do": ("rich_text", "checked", "color"),
    "toggle": ("rich_text", "color"),
    "quote": ("rich_text", "color"),
    "callout": ("rich_text", "icon", "color"),
    "divider": (),
    "code": ("rich_text", "caption", "language"),
}

#: Campos que são *rich text* e precisam ir no formato de requisição.
_CAMPOS_RICH_TEXT = frozenset({"rich_text", "caption"})

#: Recusados sempre, com ou sem ``forcar_tipos_arriscados``.
_TIPOS_IMPOSSIVEIS = frozenset({"child_database", "child_page"})


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


@dataclass
class ResultadoReordenacao:
    """Resultado de :func:`reordenar_bloco`.

    Attributes:
        bloco_id_antigo: ID do bloco original (agora na lixeira).
        bloco_id_novo: ID da cópia criada na posição pedida.
        tipo: Tipo do bloco.
        backup_path: Caminho **absoluto** do backup em JSON.
        id_mudou: Se o ID mudou (sempre, numa reordenação que aconteceu).
    """

    bloco_id_antigo: str
    bloco_id_novo: str
    tipo: str
    backup_path: str
    id_mudou: bool


class ReordenacaoRecusadaError(NotionSyncError, ValueError):
    """Base das recusas **antes de qualquer escrita** — nada foi alterado.

    Deriva também de ``ValueError``: as bordas que já tratavam essas recusas
    como entrada inválida (código 2 na CLI) continuam funcionando.
    """


class BlocoArriscadoError(ReordenacaoRecusadaError):
    """Mantida por compatibilidade: não é mais levantada.

    Era a recusa de ``child_page`` sem ``forcar_tipos_arriscados``. Como a API
    não recria ``child_page`` por append, ele passou a ser recusado sempre, com
    :class:`BlocoImpossivelError`.
    """


class BlocoImpossivelError(ReordenacaoRecusadaError):
    """``child_database``/``child_page``: a API não os recria por append — nunca suportado."""


class BlocoNaoReordenavelError(ReordenacaoRecusadaError):
    """Tipo fora da lista branca, ou conteúdo que não se regrava sem perda.

    Attributes:
        tipo: Tipo do bloco recusado.
    """

    def __init__(self, tipo: str, motivo: str) -> None:
        self.tipo = tipo
        super().__init__(motivo)


class BlocoComFilhosError(ReordenacaoRecusadaError):
    """O bloco tem filhos: a cópia sairia sem eles e o original os levaria para a lixeira.

    Attributes:
        bloco_id: ID do bloco recusado.
        tipo: Tipo do bloco.
    """

    def __init__(self, bloco_id: str, tipo: str) -> None:
        self.bloco_id = bloco_id
        self.tipo = tipo
        super().__init__(
            f"O bloco {bloco_id} ('{tipo}') tem blocos filhos. Reordenar recria o bloco "
            "sem os filhos e manda o original — com os filhos — para a lixeira, então "
            "é recusado. Mova os filhos para fora dele antes, ou reorganize pela "
            "interface do Notion."
        )


class ReordenacaoIncompletaError(NotionSyncError):
    """Uma etapa de escrita falhou no meio da reordenação.

    Como a cópia é criada **antes** de apagar o original, o original nunca se
    perde por uma falha aqui: ou a cópia falhou (página intacta), ou a exclusão
    falhou (sobra uma duplicata a apagar).

    Attributes:
        etapa: ``"anexar"`` (a cópia não foi confirmada) ou ``"excluir"`` (a
            cópia existe, o original também).
        bloco_id_antigo: ID do original — continua na página.
        bloco_id_novo: ID da cópia quando ela foi criada; ``None`` se não foi.
        backup_path: Caminho absoluto do backup em JSON.
        copia_incerta: A resposta do anexar se perdeu (rede): pode ter sido
            criada uma cópia sem que o ID chegasse aqui.
        causa: A exceção original.
    """

    def __init__(
        self,
        *,
        etapa: Literal["anexar", "excluir"],
        bloco_id_antigo: str,
        bloco_id_novo: str | None,
        backup_path: str,
        copia_incerta: bool,
        causa: BaseException | None,
    ) -> None:
        self.etapa = etapa
        self.bloco_id_antigo = bloco_id_antigo
        self.bloco_id_novo = bloco_id_novo
        self.backup_path = backup_path
        self.original_intacto = True
        self.copia_incerta = copia_incerta
        self.causa = causa
        detalhe = f" Causa: {causa}" if causa is not None else ""
        if etapa == "anexar":
            situacao = (
                f"A cópia do bloco {bloco_id_antigo} não foi confirmada; o original NÃO "
                "foi apagado e continua no lugar."
            )
            if copia_incerta:
                situacao += (
                    " A resposta se perdeu na rede: pode ter sido criada uma cópia — "
                    "confira com 'blocos <pagina_id>' antes de repetir."
                )
        else:
            situacao = (
                f"A cópia {bloco_id_novo} foi criada na posição pedida, mas apagar o "
                f"original {bloco_id_antigo} falhou: a página tem os dois. Apague o "
                "original para concluir."
            )
        super().__init__(f"{situacao} Backup: {backup_path}.{detalhe}")


def _bloco_por_id(cliente: NotionClient, pagina_id: str, bloco_id: str) -> dict[str, Any]:
    chave = chave_de_id(bloco_id)
    for bloco in cliente.ler_blocos(pagina_id, buscar_todos=True):
        if chave_de_id(str(bloco.get("id", ""))) == chave:
            return bloco
    raise ValueError(f"Bloco {bloco_id} não encontrado como filho direto de {pagina_id}.")


def _validar_reordenavel(bloco: dict[str, Any], bloco_id: str) -> str:
    """Recusa, antes de qualquer escrita, o que não se recria sem perda."""

    tipo = str(bloco.get("type") or "")
    if tipo == "child_database":
        raise BlocoImpossivelError(
            f"'{tipo}' não pode ser reordenado: a API do Notion não recria um database "
            "com PATCH .../children (só POST /databases). Apagar o original perderia o "
            "schema e as linhas. Recrie manualmente na posição certa com criar-database "
            "+ importar-planilha."
        )
    if tipo == "child_page":
        raise BlocoImpossivelError(
            f"'{tipo}' não pode ser reordenado: a API do Notion só cria página por "
            "POST /pages e recusa child_page no append — apagar e recriar mandaria a "
            "subpágina inteira para a lixeira. A API não oferece reordenar subpáginas "
            "(mover-pagina só troca o pai); faça isso na interface do Notion."
        )
    if tipo not in _TIPOS_SEGUROS:
        raise BlocoNaoReordenavelError(
            tipo,
            f"'{tipo or '(sem tipo)'}' não está entre os tipos que se recriam sem perda "
            f"({', '.join(sorted(_TIPOS_SEGUROS))}). Reordenar apagaria o original sem "
            "conseguir recriá-lo; mova pela interface do Notion.",
        )
    if bloco.get("has_children"):
        raise BlocoComFilhosError(bloco_id, tipo)
    icone = (bloco.get(tipo) or {}).get("icon")
    if isinstance(icone, dict) and icone.get("type") == "file":
        raise BlocoNaoReordenavelError(
            tipo,
            "O ícone deste bloco é um arquivo hospedado no Notion, cuja URL expira; a "
            "cópia não conseguiria reenviá-lo. Reordene pela interface do Notion.",
        )
    return tipo


def _payload_recriavel(bloco: dict[str, Any]) -> dict[str, Any]:
    """Monta a cópia do bloco só com os campos graváveis do tipo (lista branca).

    Campos ``None`` são descartados (a API recusa ``null`` onde espera objeto)
    e o *rich text* vai no formato de requisição. O corpo vazio do ``divider``
    é mantido.

    Raises:
        BlocoNaoReordenavelError: Se o texto tiver um item que não se regrava.
    """

    tipo = str(bloco.get("type") or "")
    lido = bloco.get(tipo) or {}
    corpo: dict[str, Any] = {}
    for campo in _CAMPOS_GRAVAVEIS[tipo]:
        valor = lido.get(campo)
        if valor is None:
            continue
        if campo in _CAMPOS_RICH_TEXT:
            try:
                valor = rich_text_para_requisicao(valor)
            except RichTextNaoRegravavelError as erro:
                raise BlocoNaoReordenavelError(tipo, str(erro)) from erro
        corpo[campo] = valor
    return {"object": "block", "type": tipo, tipo: corpo}


def reordenar_bloco(
    pagina_id: str,
    bloco_id: str,
    *,
    apos_bloco_id: str | None = None,
    inicio: bool = False,
    forcar_tipos_arriscados: bool = False,
    diretorio_backup: Path | str | None = None,
    cliente: NotionClient | None = None,
) -> ResultadoReordenacao:
    """Reordena um bloco existente dentro da mesma página pai.

    Implementado como **copiar e depois apagar** (a API do Notion não move
    blocos): valida, grava o backup, cria a cópia na posição pedida, confere o
    ID devolvido e só então apaga o original. IDs aceitam as formas com e sem
    hífens e links do Notion.

    Args:
        pagina_id: ID da página (ou bloco) que contém ``bloco_id`` como filho direto.
        bloco_id: ID do bloco a mover.
        apos_bloco_id: Move o bloco para logo após este bloco irmão. Exclusivo
            com ``inicio``.
        inicio: Move o bloco para o início da lista de filhos
            (``position: start``). Exclusivo com ``apos_bloco_id``.
        forcar_tipos_arriscados: Mantido por compatibilidade, **sem efeito**:
            ``child_page`` passou a ser recusado sempre (ver o docstring do
            módulo).
        diretorio_backup: Pasta do backup; ``None`` usa a pasta de estado do
            usuário (:func:`~notion_starter.services.backups.diretorio_backup_padrao`),
            nunca o diretório corrente.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        :class:`ResultadoReordenacao` com o ID antigo, o novo e o caminho
        absoluto do backup.

    Raises:
        ValueError: Se nem ``apos_bloco_id`` nem ``inicio`` forem informados
            (ou ambos), se ``apos_bloco_id`` for o próprio bloco, ou se o bloco
            não for encontrado.
        BlocoImpossivelError: ``child_database``/``child_page``.
        BlocoNaoReordenavelError: Tipo fora da lista branca, ícone hospedado ou
            texto com item que não se regrava.
        BlocoComFilhosError: O bloco tem filhos.
        ReordenacaoIncompletaError: Uma escrita falhou no meio; o original
            continua na página (ver os atributos para o estado exato).
    """

    del forcar_tipos_arriscados  # sem efeito desde que child_page é recusado sempre
    if bool(apos_bloco_id) == bool(inicio):
        raise ValueError("Informe exatamente um entre apos_bloco_id e inicio.")

    pagina_id = extrair_id(pagina_id)
    bloco_id = extrair_id(bloco_id, preferir_ancora=True)
    ancora = extrair_id(apos_bloco_id, preferir_ancora=True) if apos_bloco_id else None
    if ancora is not None and chave_de_id(ancora) == chave_de_id(bloco_id):
        raise ValueError("apos_bloco_id é o próprio bloco — não há o que mover.")

    cli = cliente or _cliente_padrao()
    bloco = _bloco_por_id(cli, pagina_id, bloco_id)
    tipo = _validar_reordenavel(bloco, bloco_id)
    copia = _payload_recriavel(bloco)

    backup_path = str(
        salvar_backup_json(bloco, prefixo=f"bloco-{bloco_id}", diretorio=diretorio_backup)
    )

    posicao: dict[str, Any] = {"no_inicio": True} if inicio else {"apos_bloco_id": ancora}
    try:
        resposta = cli.anexar_blocos(pagina_id, [copia], **posicao)
    except NotionSyncError as erro:
        raise ReordenacaoIncompletaError(
            etapa="anexar",
            bloco_id_antigo=bloco_id,
            bloco_id_novo=None,
            backup_path=backup_path,
            copia_incerta=isinstance(erro, NotionConnectionError),
            causa=erro,
        ) from erro

    # Com posição, ``results`` traz a cópia seguida dos irmãos: o primeiro é o novo.
    criados = (resposta.get("results") or []) if isinstance(resposta, dict) else []
    novo_id = str(criados[0].get("id") or "") if criados else ""
    if not novo_id:
        raise ReordenacaoIncompletaError(
            etapa="anexar",
            bloco_id_antigo=bloco_id,
            bloco_id_novo=None,
            backup_path=backup_path,
            copia_incerta=True,
            causa=None,
        )

    try:
        cli.excluir_bloco(bloco_id)
    except NotionSyncError as erro:
        raise ReordenacaoIncompletaError(
            etapa="excluir",
            bloco_id_antigo=bloco_id,
            bloco_id_novo=novo_id,
            backup_path=backup_path,
            copia_incerta=False,
            causa=erro,
        ) from erro

    return ResultadoReordenacao(
        bloco_id_antigo=bloco_id,
        bloco_id_novo=novo_id,
        tipo=tipo,
        backup_path=backup_path,
        id_mudou=novo_id != bloco_id,
    )
