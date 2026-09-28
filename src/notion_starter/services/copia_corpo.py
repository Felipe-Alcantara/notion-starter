"""Caso de uso: copiar o corpo de uma página para outra **bloco a bloco**.

Passar por Markdown perde o que o Markdown não representa: tabela com
cabeçalho, checklist, cor, callout, colunas, menções. Aqui cada bloco lido vira
o payload que recria o mesmo bloco. Três fatos medidos em 2026-09-27 moldam a
conversão:

* a leitura devolve campos opcionais como ``null`` (ex.: ``paragraph.icon``) e a
  escrita recusa ``null`` onde espera objeto ("should be an object or
  ``undefined``") — as chaves ``None`` saem;
* um lote de ``children`` é **atômico**: um bloco recusado derruba o lote
  inteiro. Por isso só se copia o que está numa **lista branca** de tipos
  graváveis; o resto é pulado com o motivo (``ignorados``);
* uma requisição aceita no máximo dois níveis de ``children``. Filhos mais
  fundos são anexados depois, no bloco já criado.

Numa falha no meio, os blocos de topo já criados no destino são apagados de
novo (vão para a lixeira) e sobe
:class:`~notion_starter.exceptions.EscritaParcialError` — repetir o comando não
duplica conteúdo.
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from notion_starter import NotionClient
from notion_starter.constants import (
    MAX_BYTES_POR_REQUISICAO,
    MAX_ELEMENTOS_POR_REQUISICAO,
    MAX_ITENS_ARRAY,
    MAX_NIVEIS_ANINHADOS,
)
from notion_starter.content import (
    contar_elementos,
    item_para_requisicao,
    planejar_lotes,
)
from notion_starter.exceptions import (
    EscritaAbaixoDeDatabaseError,
    EscritaParcialError,
    NotionConnectionError,
    NotionHTTPError,
    NotionSyncError,
    RichTextNaoRegravavelError,
)
from notion_starter.utils import chave_de_id

#: Tipos que a cópia sabe regravar. Lista branca: tipo novo ou desconhecido é
#: pulado com motivo, em vez de derrubar o lote inteiro com um 400.
TIPOS_COPIAVEIS = frozenset(
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
        "code",
        "divider",
        "equation",
        "table",
        "table_row",
        "column_list",
        "column",
        "bookmark",
        "embed",
        "image",
        "video",
        "file",
        "pdf",
        "audio",
        "table_of_contents",
        "breadcrumb",
        "link_to_page",
        "synced_block",
    }
)

#: Por que os tipos conhecidos fora da lista branca não são copiados.
MOTIVOS_NAO_COPIAVEIS: dict[str, str] = {
    "child_page": "subpágina não se cria como bloco; mova-a com 'mover-pagina'",
    "child_database": "database não se cria como bloco; mova-o com 'mover-database'",
    "link_preview": "a API só lê link_preview",
    "unsupported": "a API não expõe este tipo de bloco",
    "template": "o bloco 'template' foi descontinuado pela API",
}

#: Blocos que o Notion só aceita **com** os filhos na mesma requisição.
_EXIGEM_FILHOS = frozenset({"table", "column_list", "column"})

_TIPOS_DE_ARQUIVO = frozenset({"image", "video", "file", "pdf", "audio"})

#: Campos de *rich text* dentro do corpo de um bloco.
_CAMPOS_RICH_TEXT = ("rich_text", "caption")


@dataclass(frozen=True)
class BlocoIgnorado:
    """Bloco da origem que não foi copiado.

    Attributes:
        id: ID do bloco na origem.
        tipo: ``type`` do bloco.
        motivo: Por que ele ficou de fora (e o que fazer, quando há o que fazer).
    """

    id: str
    tipo: str
    motivo: str

    def para_dict(self) -> dict[str, str]:
        """Forma serializável (JSON)."""

        return {"id": self.id, "tipo": self.tipo, "motivo": self.motivo}


@dataclass(frozen=True)
class ResultadoCopia:
    """O que :func:`copiar_corpo` fez (ou faria, no ``dry_run``).

    Attributes:
        origem: Página lida.
        destino: Página que recebeu os blocos (no fim do corpo).
        blocos_de_topo: Blocos criados no primeiro nível do destino.
        por_tipo: Contagem por tipo de **todos** os blocos copiados (todos os níveis).
        ignorados: Blocos da origem que ficaram de fora, com o motivo.
        degradados: Blocos em que uma menção não regravável virou texto comum
            ou um ícone de arquivo foi retirado.
        escritas: Requisições de escrita feitas (``anexar_blocos``).
        pulado: ``True`` quando ``so_se_vazio`` achou o destino com conteúdo.
        dry_run: Nada foi escrito.
        conferencia: Com ``conferir=True``, as contagens relidas do destino.
    """

    origem: str
    destino: str
    blocos_de_topo: int = 0
    por_tipo: dict[str, int] = field(default_factory=dict)
    ignorados: tuple[BlocoIgnorado, ...] = ()
    degradados: tuple[str, ...] = ()
    escritas: int = 0
    pulado: bool = False
    dry_run: bool = False
    conferencia: dict[str, Any] | None = None

    @property
    def blocos_total(self) -> int:
        """Todos os blocos copiados, em todos os níveis."""

        return sum(self.por_tipo.values())

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {
            "origem": self.origem,
            "destino": self.destino,
            "blocos_de_topo": self.blocos_de_topo,
            "blocos_total": self.blocos_total,
            "por_tipo": dict(self.por_tipo),
            "ignorados": [b.para_dict() for b in self.ignorados],
            "degradados": list(self.degradados),
            "escritas": self.escritas,
            "pulado": self.pulado,
            "dry_run": self.dry_run,
            "conferencia": self.conferencia,
        }


@dataclass
class _No:
    """Um bloco pronto para gravar, com os filhos ainda separados."""

    tipo: str
    payload: dict[str, Any]
    filhos: list[_No]
    origem_id: str

    @property
    def exige_filhos(self) -> bool:
        return self.tipo in _EXIGEM_FILHOS


@dataclass
class _Plano:
    """Como um nó foi montado numa requisição: filhos embutidos ou para depois."""

    no: _No
    embutidos: list[_Plano] | None = None
    resto: list[_No] = field(default_factory=list)

    @property
    def pendente(self) -> bool:
        if not self.no.filhos:
            return False
        if self.embutidos is None or self.resto:
            return True
        return any(sub.pendente for sub in self.embutidos)


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


def _sem_nulos(valor: Any) -> Any:
    """Remove, recursivamente, as chaves com ``None`` de dicionários."""

    if isinstance(valor, dict):
        return {k: _sem_nulos(v) for k, v in valor.items() if v is not None}
    if isinstance(valor, list):
        return [_sem_nulos(item) for item in valor]
    return valor


def _texto_simples(item: dict[str, Any]) -> dict[str, Any]:
    """Um item de *rich text* que não se regrava vira texto comum (com link, se houver)."""

    corpo: dict[str, Any] = {"content": str(item.get("plain_text") or "")}
    if isinstance(item.get("href"), str) and item["href"].startswith(("http://", "https://")):
        corpo["link"] = {"url": item["href"]}
    novo: dict[str, Any] = {"type": "text", "text": corpo}
    if isinstance(item.get("annotations"), dict):
        novo["annotations"] = dict(item["annotations"])
    return novo


def _rich_text_gravavel(itens: Any) -> tuple[list[dict[str, Any]], bool]:
    """Converte um *rich text* lido em gravável; diz se algo virou texto comum."""

    if not isinstance(itens, list):
        return [], False
    convertidos: list[dict[str, Any]] = []
    degradou = False
    for item in itens:
        if not isinstance(item, dict):
            continue
        try:
            convertidos.append(item_para_requisicao(item))
        except RichTextNaoRegravavelError:
            convertidos.append(_texto_simples(item))
            degradou = True
    return convertidos, degradou


def _corpo_de_arquivo(tipo: str, dados: dict[str, Any]) -> dict[str, Any] | None:
    """Imagem/vídeo/arquivo: só o link externo se recria; hospedado no Notion, não."""

    if dados.get("type") != "external":
        return None
    corpo: dict[str, Any] = {"type": "external", "external": dict(dados.get("external") or {})}
    if dados.get("caption"):
        corpo["caption"] = dados["caption"]
    if tipo == "file" and dados.get("name"):
        corpo["name"] = dados["name"]
    return corpo


def _converter(bloco: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
    """Payload gravável (sem ``children``) de um bloco lido.

    Returns:
        ``(payload | None, motivo_se_ignorado, degradou)``.
    """

    tipo = str(bloco.get("type") or "")
    if tipo not in TIPOS_COPIAVEIS:
        motivo = MOTIVOS_NAO_COPIAVEIS.get(tipo, f"tipo '{tipo}' fora da lista de copiáveis")
        return None, motivo, False

    dados = deepcopy(bloco.get(tipo)) if isinstance(bloco.get(tipo), dict) else {}
    dados.pop("children", None)
    degradou = False

    if tipo in _TIPOS_DE_ARQUIVO:
        corpo = _corpo_de_arquivo(tipo, dados)
        if corpo is None:
            return None, (
                "arquivo hospedado no Notion: o link expira e não recria o bloco; "
                "anexe o arquivo de novo no destino"
            ), False
        dados = corpo

    if tipo == "synced_block":
        origem_sync = dados.get("synced_from")
        # Original: ``synced_from`` precisa ir como null explícito. Cópia de
        # um sincronizado: vira outra referência ao mesmo original.
        dados = {"synced_from": origem_sync} if isinstance(origem_sync, dict) else {}

    for campo in _CAMPOS_RICH_TEXT:
        if campo in dados:
            dados[campo], perdeu = _rich_text_gravavel(dados[campo])
            degradou = degradou or perdeu
    if tipo == "table_row":
        celulas = []
        for celula in dados.get("cells") or []:
            convertida, perdeu = _rich_text_gravavel(celula)
            celulas.append(convertida)
            degradou = degradou or perdeu
        dados["cells"] = celulas

    icone = dados.get("icon")
    if isinstance(icone, dict) and icone.get("type") not in ("emoji", "external"):
        dados.pop("icon")
        degradou = True

    dados = _sem_nulos(dados)
    if tipo == "synced_block" and "synced_from" not in dados:
        dados["synced_from"] = None
    return {"object": "block", "type": tipo, tipo: dados}, "", degradou


def _preparar(
    blocos: list[dict[str, Any]],
    ignorados: list[BlocoIgnorado],
    degradados: list[str],
) -> list[_No]:
    """Converte a árvore lida em nós graváveis, anotando o que fica de fora."""

    nos: list[_No] = []
    for bloco in blocos:
        if not isinstance(bloco, dict):
            continue
        bloco_id = str(bloco.get("id") or "")
        payload, motivo, degradou = _converter(bloco)
        tipo = str(bloco.get("type") or "")
        if payload is None:
            ignorados.append(BlocoIgnorado(bloco_id, tipo, motivo))
            continue
        if degradou:
            degradados.append(bloco_id)
        duplicata = tipo == "synced_block" and payload[tipo].get("synced_from")
        filhos = [] if duplicata else _preparar(bloco.get("_filhos") or [], ignorados, degradados)
        if tipo == "column" and not filhos:
            # Coluna sem nenhum filho copiável: a API recusa coluna vazia.
            filhos = [_No("paragraph", {"object": "block", "type": "paragraph",
                                        "paragraph": {"rich_text": []}}, [], "")]
        nos.append(_No(tipo, payload, filhos, bloco_id))
    return nos


def _cabe(no: _No, niveis: int) -> bool:
    """O nó pode entrar numa requisição com ``niveis`` níveis de filhos livres?"""

    if not no.exige_filhos:
        return True
    if niveis <= 0:
        return False
    return all(_cabe(filho, niveis - 1) for filho in no.filhos[:MAX_ITENS_ARRAY])


def _montar(no: _No, niveis: int) -> tuple[dict[str, Any], _Plano]:
    """Payload do nó com os filhos que cabem embutidos; o resto fica no plano."""

    payload = deepcopy(no.payload)
    plano = _Plano(no)
    if not no.filhos or niveis <= 0:
        return payload, plano
    candidatos = no.filhos[:MAX_ITENS_ARRAY]
    if len(no.filhos) > MAX_ITENS_ARRAY and not no.exige_filhos:
        return payload, plano
    if not all(_cabe(filho, niveis - 1) for filho in candidatos):
        return payload, plano
    montados = [_montar(filho, niveis - 1) for filho in candidatos]
    com_filhos = deepcopy(payload)
    com_filhos[no.tipo]["children"] = [m[0] for m in montados]
    # Mesma estimativa de ``content.planejar_lotes`` (``requests`` serializa
    # com ensure_ascii), com folga para o invólucro da requisição.
    tamanho = len(json.dumps(com_filhos, ensure_ascii=True, separators=(",", ":")))
    grande = (
        contar_elementos(com_filhos) > MAX_ELEMENTOS_POR_REQUISICAO
        or tamanho > MAX_BYTES_POR_REQUISICAO - 4_096
    )
    if grande and not no.exige_filhos:
        return payload, plano
    plano.embutidos = [m[1] for m in montados]
    plano.resto = no.filhos[MAX_ITENS_ARRAY:]
    return com_filhos, plano


class _Gravador:
    """Grava a árvore no destino, nível a nível, contando as escritas."""

    def __init__(self, cliente: NotionClient) -> None:
        self.cliente = cliente
        self.escritas = 0

    def gravar(
        self,
        pai_id: str,
        nos: list[_No],
        criados_topo: list[tuple[str, str]] | None = None,
    ) -> None:
        montados = [_montar(no, MAX_NIVEIS_ANINHADOS) for no in nos]
        planos = iter(m[1] for m in montados)
        for lote in planejar_lotes([m[0] for m in montados]):
            resposta = self.cliente.anexar_blocos(pai_id, lote)
            self.escritas += 1
            resultados = resposta.get("results") if isinstance(resposta, dict) else None
            criados = [r for r in (resultados or []) if isinstance(r, dict)][: len(lote)]
            planos_do_lote = [next(planos) for _ in lote]
            if criados_topo is not None:
                criados_topo.extend(
                    (str(c.get("id") or ""), str(c.get("type") or "")) for c in criados
                )
            if len(criados) < len(lote):
                raise _LoteIncompleto(len(lote), len(criados))
            for plano, criado in zip(planos_do_lote, criados, strict=True):
                self._completar(plano, str(criado.get("id") or ""))

    def _completar(self, plano: _Plano, criado_id: str) -> None:
        if not plano.pendente:
            return
        if plano.embutidos is None:
            self.gravar(criado_id, plano.no.filhos)
            return
        if plano.resto:
            self.gravar(criado_id, plano.resto)
        if any(sub.pendente for sub in plano.embutidos):
            filhos = self.cliente.ler_blocos(criado_id, buscar_todos=True)
            for sub, filho in zip(plano.embutidos, filhos, strict=False):
                self._completar(sub, str(filho.get("id") or ""))


class _LoteIncompleto(NotionSyncError):
    """A API criou menos blocos do que foram enviados."""

    def __init__(self, enviados: int, criados: int) -> None:
        super().__init__(f"enviados {enviados} blocos, mas a API criou {criados}")


def _contar(nos: list[_No], contagem: Counter[str]) -> None:
    for no in nos:
        contagem[no.tipo] += 1
        _contar(no.filhos, contagem)


def _contar_lidos(blocos: list[dict[str, Any]], contagem: Counter[str]) -> None:
    for bloco in blocos:
        contagem[str(bloco.get("type") or "")] += 1
        _contar_lidos(bloco.get("_filhos") or [], contagem)


def _desfazer(
    cliente: NotionClient, criados: list[tuple[str, str]]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Apaga de novo os blocos de topo criados (os filhos vão junto)."""

    desfeitos: list[str] = []
    ficaram: list[tuple[str, str]] = []
    for bloco_id, tipo in reversed(criados):
        try:
            cliente.excluir_bloco(bloco_id)
            desfeitos.append(bloco_id)
        except NotionSyncError:
            ficaram.append((bloco_id, tipo))
    ficaram.reverse()
    return desfeitos, ficaram


def copiar_corpo(
    origem_id: str,
    destino_id: str,
    *,
    so_se_vazio: bool = False,
    mesmo_com_database: bool = False,
    dry_run: bool = False,
    conferir: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoCopia:
    """Copia o corpo de ``origem_id`` para o **fim** do corpo de ``destino_id``.

    Args:
        origem_id: Página (ou bloco) de onde ler.
        destino_id: Página (ou bloco) que recebe a cópia.
        so_se_vazio: Não escreve nada se o destino já tiver algum bloco
            (torna a cópia idempotente para quem roda de novo).
        mesmo_com_database: Aceita escrever num destino que contém database
            (sem isso, recusa como :func:`~notion_starter.services.conteudo.escrever_conteudo`).
        dry_run: Lê e planeja, sem escrever.
        conferir: Relê o destino antes e depois e compara as contagens por tipo.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        O :class:`ResultadoCopia`.

    Raises:
        ValueError: IDs vazios ou origem igual ao destino.
        EscritaAbaixoDeDatabaseError: Destino com database e sem
            ``mesmo_com_database``.
        EscritaParcialError: Uma escrita falhou no meio; o que foi criado no
            topo do destino é apagado de novo e listado.
    """

    origem_id = (origem_id or "").strip()
    destino_id = (destino_id or "").strip()
    if not origem_id or not destino_id:
        raise ValueError("origem_id e destino_id são obrigatórios.")
    if chave_de_id(origem_id) == chave_de_id(destino_id):
        raise ValueError("Origem e destino são a mesma página: a cópia duplicaria o corpo.")

    cli = cliente or _cliente_padrao()
    topo_destino = cli.ler_blocos(destino_id, buscar_todos=True)
    if so_se_vazio and topo_destino:
        return ResultadoCopia(origem=origem_id, destino=destino_id, pulado=True, dry_run=dry_run)
    databases = [
        (str(b.get("id") or ""), str((b.get("child_database") or {}).get("title") or ""))
        for b in topo_destino
        if b.get("type") == "child_database"
    ]
    if databases and not mesmo_com_database:
        raise EscritaAbaixoDeDatabaseError(destino_id, databases)

    lidos = cli.ler_blocos(origem_id, buscar_todos=True, recursivo=True)
    ignorados: list[BlocoIgnorado] = []
    degradados: list[str] = []
    nos = _preparar(lidos, ignorados, degradados)
    contagem: Counter[str] = Counter()
    _contar(nos, contagem)
    base = {
        "origem": origem_id,
        "destino": destino_id,
        "por_tipo": dict(sorted(contagem.items())),
        "ignorados": tuple(ignorados),
        "degradados": tuple(degradados),
    }
    if dry_run or not nos:
        return ResultadoCopia(blocos_de_topo=len(nos) if dry_run else 0, dry_run=dry_run, **base)

    antes: Counter[str] = Counter()
    if conferir:
        _contar_lidos(cli.ler_blocos(destino_id, buscar_todos=True, recursivo=True), antes)

    gravador = _Gravador(cli)
    criados_topo: list[tuple[str, str]] = []
    try:
        gravador.gravar(destino_id, nos, criados_topo)
    except NotionSyncError as erro:
        incerto = isinstance(erro, (NotionConnectionError, _LoteIncompleto)) or (
            isinstance(erro, NotionHTTPError) and erro.status_code >= 500
        )
        desfeitos, ficaram = _desfazer(cli, criados_topo)
        raise EscritaParcialError(
            page_id=destino_id,
            total=len(nos),
            criados=ficaram,
            desfeitos=desfeitos,
            lote_incerto=incerto,
            substituicao=False,
            causa=erro,
        ) from erro

    conferencia: dict[str, Any] | None = None
    if conferir:
        depois: Counter[str] = Counter()
        _contar_lidos(cli.ler_blocos(destino_id, buscar_todos=True, recursivo=True), depois)
        novos = {tipo: n for tipo, n in (depois - antes).items() if n}
        conferencia = {
            "esperado": dict(sorted(contagem.items())),
            "encontrado": dict(sorted(novos.items())),
            "confere": novos == dict(contagem),
        }
    return ResultadoCopia(
        blocos_de_topo=len(criados_topo),
        escritas=gravador.escritas,
        conferencia=conferencia,
        **base,
    )
