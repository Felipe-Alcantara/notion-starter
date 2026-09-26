"""Casos de uso de conteúdo — ler e escrever o corpo das páginas do Notion.

Onde ``services.tarefas`` cuida das **propriedades** das tarefas, esta camada
cuida do **conteúdo** (os blocos: parágrafos, listas, código…) de qualquer
página visível à integração. É o que dá a uma IA acesso ao texto das notas, não
só às colunas.

Como as demais camadas de serviço, **não conhece HTTP** (isso é da ``api``/CLI/
MCP) nem o **formato cru de blocos** (isso é do ``notion_starter.content``). O
:class:`NotionClient` é resolvido da configuração do servidor por padrão, mas
pode ser **injetado** — mantendo estas funções testáveis sem token nem rede.

Operações destrutivas (``excluir_bloco``) existem por escolha de escopo: a IA
tem acesso total. Quem expõe (CLI/MCP) é responsável por confirmar antes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, TypedDict

from notion_starter import (
    NotionClient,
    blocos_para_markdown,
    markdown_para_blocos,
)
from notion_starter.content import (
    contar_elementos,
    perdas_de_formatacao,
    planejar_lotes,
    rich_text_de_codigo,
    trocar_trecho_rich_text,
    validar_blocos,
)
from notion_starter.exceptions import (
    BlocoSemTextoError,
    EdicaoMultiblocoError,
    EscritaAbaixoDeDatabaseError,
    EscritaParcialError,
    ExclusaoArriscadaError,
    LimpezaIncompletaError,
    NotionConnectionError,
    NotionHTTPError,
    NotionSyncError,
    PerdaDeFormatacaoError,
    TrocaDeTipoError,
)

# Tamanho do trecho de texto mostrado ao listar blocos. O bastante para
# reconhecer o bloco (e casar com o que se lê na página) sem poluir a saída.
_LARGURA_PREVIEW = 100

#: Tipos que ``markdown_para_blocos`` recria **do mesmo tipo** a partir do que
#: ``conteudo`` mostra — a lista branca da limpeza. Tudo o que estiver fora
#: dela é preservado por padrão ao limpar/substituir: ``equation``,
#: ``link_to_page``, ``table_of_contents``, ``breadcrumb``… não aparecem no
#: Markdown lido (quem reescreve nem sabe que existiam); ``toggle`` e
#: ``callout`` aparecem, mas voltariam como parágrafo, sem ícone, cor nem a
#: estrutura. ``image`` e ``table`` o Markdown até produz, mas URL assinada
#: expira e a tabela perde cabeçalho de linha e cores — continuam preservados.
TIPOS_RECRIAVEIS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "quote",
        "code",
        "divider",
    }
)

#: Tipos preservados cujo texto **aparece** em ``conteudo``: reescrever esse
#: texto depois de um ``--substituir`` o deixa duplicado (o bloco original
#: continua na página).
_TIPOS_PRESERVADOS_VISIVEIS = frozenset({"toggle", "callout"})

#: Exemplos documentais dos blocos que a lib **não sabe recriar** — a regra de
#: verdade é a lista branca :data:`TIPOS_RECRIAVEIS`. Apagar um deles
#: numa reescrita é perda de verdade, não inconveniência:
#:
#: - ``image``/``file``/``video``/``pdf``/``audio``: a URL do Notion é assinada e
#:   expira; depois de arquivado o bloco, o arquivo não volta por Markdown.
#: - ``child_page``/``child_database``: apagar leva junto a subpágina ou o
#:   **database inteiro** que morava dentro daquela página.
#: - ``embed``/``bookmark``/``link_preview``/``synced_block``/``table``/
#:   ``column_list``: sobrevivem ao arquivamento, mas ``blocos_para_markdown``
#:   não os reconstrói — reescrever apagaria sem repor.
#:
#: - ``equation``/``link_to_page``/``table_of_contents``/``breadcrumb``: nem
#:   aparecem no Markdown lido.
#:
#: Por isso a reescrita os **preserva por padrão**; apagá-los exige um pedido
#: explícito de quem chama.
TIPOS_NAO_RECRIAVEIS = frozenset(
    {
        "image",
        "file",
        "video",
        "pdf",
        "audio",
        "embed",
        "bookmark",
        "link_preview",
        "child_page",
        "child_database",
        "synced_block",
        "table",
        "column_list",
        "equation",
        "link_to_page",
        "table_of_contents",
        "breadcrumb",
        "toggle",
        "callout",
    }
)


@dataclass(frozen=True)
class BlocoCriado:
    """Um bloco de topo criado por uma escrita."""

    id: str
    tipo: str


@dataclass
class ResultadoRestauracao:
    """O que :func:`restaurar_blocos` conseguiu tirar da lixeira.

    Attributes:
        restaurados: IDs que voltaram para a página (no **fim** dela — é onde a
            API os recoloca).
        falhas: ``(id, motivo)`` de cada ID que não voltou.
    """

    restaurados: list[str] = field(default_factory=list)
    falhas: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ResultadoLimpeza:
    """O que uma limpeza de corpo apagou e o que decidiu não apagar.

    Attributes:
        apagados: Quantidade de blocos arquivados.
        preservados: ``(id, tipo)`` de cada bloco de topo mantido por não ser
            recriável a partir de Markdown (ou por conter algo que não é).
        apagados_ids: ``(id, tipo)`` de cada bloco arquivado, na ordem — é o
            que permite restaurar (:func:`restaurar_blocos`).
        motivos: ``id -> motivo`` de cada bloco preservado.
    """

    apagados: int = 0
    preservados: list[tuple[str, str]] = field(default_factory=list)
    apagados_ids: list[tuple[str, str]] = field(default_factory=list)
    motivos: dict[str, str] = field(default_factory=dict)

    def __int__(self) -> int:
        """Compatibilidade: o retorno antigo era só a contagem de apagados."""

        return self.apagados

    def __eq__(self, outro: object) -> bool:
        """Compara com outro resultado ou direto com a contagem de apagados."""

        if isinstance(outro, ResultadoLimpeza):
            return (self.apagados, self.preservados) == (outro.apagados, outro.preservados)
        if isinstance(outro, int):
            return self.apagados == outro
        return NotImplemented

    @property
    def tipos_preservados(self) -> list[str]:
        """Tipos distintos preservados, em ordem, para mensagem ao usuário."""

        vistos: list[str] = []
        for _, tipo in self.preservados:
            if tipo not in vistos:
                vistos.append(tipo)
        return vistos


@dataclass
class ResultadoEscrita:
    """O que uma escrita anexou e, quando substituiu, o que a limpeza fez.

    Attributes:
        anexados: Blocos escritos na página.
        limpeza: Resultado da limpeza quando ``substituir=True``; ``None`` numa
            escrita que só anexou.
        criados: ID e tipo de cada bloco de **topo** criado, na ordem. Vazio
            quando a API não informa os IDs (não quer dizer "nada criado").
            Filhos (linhas de tabela) não entram: a API devolve só o primeiro
            nível.
    """

    anexados: int = 0
    limpeza: ResultadoLimpeza | None = None
    criados: list[BlocoCriado] = field(default_factory=list)

    def __int__(self) -> int:
        """Compatibilidade: o retorno antigo era só a contagem de anexados."""

        return self.anexados

    def __eq__(self, outro: object) -> bool:
        """Compara com outro resultado ou direto com a contagem de anexados."""

        if isinstance(outro, ResultadoEscrita):
            return (self.anexados, self.limpeza) == (outro.anexados, outro.limpeza)
        if isinstance(outro, int):
            return self.anexados == outro
        return NotImplemented

    @property
    def preservados(self) -> list[tuple[str, str]]:
        """Blocos que a substituição manteve por não serem recriáveis."""

        return self.limpeza.preservados if self.limpeza else []


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` a partir da configuração do servidor.

    Import tardio de propósito: evita acoplar a camada de casos de uso ao Django
    no import — a config só é tocada quando nenhum cliente é injetado (uso real).
    """

    from integrations.notion import criar_cliente

    return criar_cliente()


def ler_conteudo(
    page_id: str,
    *,
    cliente: NotionClient | None = None,
) -> str:
    """Lê o conteúdo de uma página como Markdown.

    Args:
        page_id: ID da página (ou bloco) cujo conteúdo será lido.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        O conteúdo da página em Markdown (``""`` se a página não tiver corpo).
        Lê em profundidade: desce em colunas, toggles e blocos sincronizados,
        para que o conteúdo aninhado não fique de fora.
    """

    blocos = (cliente or _cliente_padrao()).ler_blocos(
        page_id, buscar_todos=True, recursivo=True
    )
    return blocos_para_markdown(blocos)


def ler_pagina_ou_database(
    page_id: str,
    *,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Lê um ID que pode ser página (corpo) ou database (linhas).

    Um database não tem corpo em blocos — seu "conteúdo" são as linhas. Em vez de
    cada borda (CLI/MCP) repetir esse fallback, este caso de uso o centraliza:
    tenta ler o corpo; se vier vazio mas houver linhas, sinaliza que é um
    database e já as devolve.

    **Propriedades vêm antes do corpo**: uma página do Notion é uma coisa só —
    as propriedades (colunas, quando ela é linha de um database) MAIS o corpo
    (blocos). Há páginas com mais informação nas propriedades do que no corpo,
    então a leitura completa devolve as duas partes, com ``propriedades``
    primeiro no resultado.

    Args:
        page_id: ID da página ou database.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        ``{"tipo": "pagina", "propriedades": {...}, "markdown": ...}`` para
        páginas — ``propriedades`` é o mapa coluna → valor simples (vazio para
        páginas soltas, fora de database); ``{"tipo": "database", "markdown":
        "", "linhas": [...]}`` quando o ID é um database com linhas. Páginas
        sem corpo voltam como ``"pagina"`` com markdown vazio.
    """

    from notion_starter.readers import extrair_valores

    cli = cliente or _cliente_padrao()
    propriedades: dict[str, Any] = {}
    try:
        valores = extrair_valores(cli.obter_pagina(page_id))
        # Só valores preenchidos: coluna vazia não é informação na leitura.
        propriedades = {k: v for k, v in valores.items() if v not in (None, "", [])}
    except Exception:
        # O ID pode ser um database (o endpoint de página responde 404) — o
        # fallback abaixo resolve; propriedades ficam vazias.
        propriedades = {}

    markdown = ler_conteudo(page_id, cliente=cli)
    if markdown or propriedades:
        return {
            "id": page_id,
            "tipo": "pagina",
            "propriedades": propriedades,
            "markdown": markdown,
        }

    linhas = listar_linhas(page_id, cliente=cli)
    if linhas:
        return {"id": page_id, "tipo": "database", "markdown": "", "linhas": linhas}
    return {"id": page_id, "tipo": "pagina", "propriedades": {}, "markdown": ""}


def _preview_bloco(bloco: dict[str, Any]) -> str:
    """Resume um bloco numa linha curta, para identificá-lo ao listar.

    Reaproveita ``blocos_para_markdown`` (a mesma leitura de ``conteudo``) e
    colapsa quebras/espaços numa linha só, truncando com reticências. Assim o
    texto do preview casa com o que a pessoa/IA leu na página.
    """

    md = blocos_para_markdown([bloco])
    linha = " ".join(md.split())
    if len(linha) > _LARGURA_PREVIEW:
        return linha[: _LARGURA_PREVIEW - 1].rstrip() + "…"
    return linha


class BlocoListado(TypedDict, total=False):
    """Um bloco de topo como :func:`listar_blocos` o descreve.

    ``id``, ``tipo`` e ``preview`` vêm sempre; os carimbos e ``tem_filhos``
    só com ``metadados=True``; ``markdown`` só com ``completo=True``.
    """

    id: str
    tipo: str
    preview: str
    tem_filhos: bool
    criado_em: str | None
    editado_em: str | None
    criado_por: str | None
    editado_por: str | None
    na_lixeira: bool
    markdown: str


def _id_de_usuario(valor: Any) -> str | None:
    return str(valor.get("id")) if isinstance(valor, dict) and valor.get("id") else None


class MetadadosBloco(TypedDict):
    """Carimbos de um bloco, como :func:`listar_blocos`/:func:`ler_bloco` os expõem."""

    tem_filhos: bool
    criado_em: str | None
    editado_em: str | None
    criado_por: str | None
    editado_por: str | None
    na_lixeira: bool


def _metadados(bloco: dict[str, Any]) -> MetadadosBloco:
    """Carimbos que a API já devolve em cada bloco — sem chamada extra.

    Os horários vêm como a API os dá; observado no workspace real que eles
    chegam arredondados ao minuto (a documentação não fala em precisão), então
    não servem para ordenar eventos do mesmo minuto. ``tem_filhos`` também é
    verdadeiro para ``child_page``/``child_database``.
    """

    return {
        "tem_filhos": bool(bloco.get("has_children")),
        "criado_em": bloco.get("created_time"),
        "editado_em": bloco.get("last_edited_time"),
        "criado_por": _id_de_usuario(bloco.get("created_by")),
        "editado_por": _id_de_usuario(bloco.get("last_edited_by")),
        "na_lixeira": bool(bloco.get("in_trash")),
    }


def listar_blocos(
    page_id: str,
    *,
    metadados: bool = False,
    completo: bool = False,
    cliente: NotionClient | None = None,
) -> list[BlocoListado]:
    """Lista os blocos de topo de uma página com **ID**, tipo e um preview.

    É o par que faltava para ``editar-bloco``/``apagar-bloco``: ``conteudo`` lê o
    corpo como Markdown, mas descarta os IDs — sem eles não dá para editar nem
    apagar um bloco específico. Esta função devolve cada bloco de topo já com o
    ``id`` pronto para essas operações. Lê só um nível (os blocos que se apagam/
    editam diretamente); o conteúdo dentro de colunas/toggles não é expandido.

    Args:
        page_id: ID da página (ou bloco) cujos filhos serão listados.
        metadados: Acrescenta ``tem_filhos``, ``criado_em``, ``editado_em``,
            ``criado_por``, ``editado_por`` e ``na_lixeira`` — já vêm na mesma
            resposta, sem chamada extra.
        completo: Acrescenta ``markdown`` com o texto **inteiro** do bloco (o
            ``preview`` é cortado em 100 caracteres).
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Uma entrada por bloco de topo, na ordem em que aparecem na página.
        Sem as flags, exatamente ``{"id", "tipo", "preview"}`` como sempre.
    """

    blocos = (cliente or _cliente_padrao()).ler_blocos(page_id, buscar_todos=True)
    listados: list[BlocoListado] = []
    for bloco in blocos:
        item: BlocoListado = {
            "id": bloco.get("id", ""),
            "tipo": bloco.get("type", ""),
            "preview": _preview_bloco(bloco),
        }
        if metadados:
            extras = _metadados(bloco)
            item["tem_filhos"] = extras["tem_filhos"]
            item["criado_em"] = extras["criado_em"]
            item["editado_em"] = extras["editado_em"]
            item["criado_por"] = extras["criado_por"]
            item["editado_por"] = extras["editado_por"]
            item["na_lixeira"] = extras["na_lixeira"]
        if completo:
            item["markdown"] = blocos_para_markdown([bloco])
        listados.append(item)
    return listados


class PaiDoBloco(TypedDict):
    """Onde o bloco mora: o ``parent`` da API, sem fixar a lista de tipos."""

    tipo: str
    id: str | None


class BlocoLido(TypedDict):
    """Um bloco lido por :func:`ler_bloco`."""

    id: str
    tipo: str
    markdown: str
    tem_filhos: bool
    pai: PaiDoBloco
    criado_em: str | None
    editado_em: str | None
    criado_por: str | None
    editado_por: str | None
    na_lixeira: bool


def _ler_subarvore(cliente: NotionClient, bloco_id: str) -> list[dict[str, Any]]:
    """Filhos de um bloco com ``_filhos`` aninhados, sem descer em subpágina/database."""

    filhos = cliente.ler_blocos(bloco_id, buscar_todos=True)
    for filho in filhos:
        tipo = filho.get("type")
        if filho.get("has_children") and filho.get("id") and tipo not in (
            "child_page",
            "child_database",
        ):
            filho["_filhos"] = _ler_subarvore(cliente, str(filho["id"]))
    return filhos


def ler_bloco(
    block_id: str,
    *,
    cliente: NotionClient | None = None,
) -> BlocoLido:
    """Lê **um** bloco pelo ID, com o Markdown inteiro e os metadados.

    Serve a quem só tem o ID (um bloco aninhado, um link com ``#bloco``, ou a
    conferência antes de ``editar_bloco``). Quando o bloco tem filhos, eles
    entram no Markdown — exceto em ``child_page``/``child_database``, cujo
    conteúdo é uma página/linhas à parte (leia com ``ler_pagina_ou_database``).

    Args:
        block_id: ID do bloco.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`BlocoLido`.
    """

    cli = cliente or _cliente_padrao()
    bloco = cli.obter_bloco(block_id)
    tipo = str(bloco.get("type", ""))
    if bloco.get("has_children") and tipo not in ("child_page", "child_database"):
        bloco["_filhos"] = _ler_subarvore(cli, block_id)
    pai = bloco.get("parent") if isinstance(bloco.get("parent"), dict) else {}
    tipo_pai = str(pai.get("type", ""))
    id_pai = pai.get(tipo_pai)
    extras = _metadados(bloco)
    return {
        "id": str(bloco.get("id") or block_id),
        "tipo": tipo,
        "markdown": blocos_para_markdown([bloco]),
        "tem_filhos": extras["tem_filhos"],
        "pai": {"tipo": tipo_pai, "id": id_pai if isinstance(id_pai, str) else None},
        "criado_em": extras["criado_em"],
        "editado_em": extras["editado_em"],
        "criado_por": extras["criado_por"],
        "editado_por": extras["editado_por"],
        "na_lixeira": extras["na_lixeira"],
    }


def _recriavel_isolado(bloco: dict[str, Any]) -> bool:
    """O bloco, **sozinho**, volta igual a partir do Markdown que ``conteudo`` mostra?"""

    tipo = str(bloco.get("type", ""))
    if tipo not in TIPOS_RECRIAVEIS:
        return False
    corpo = bloco.get(tipo)
    # Heading toggleável guarda filhos escondidos: o Markdown vira heading comum.
    return not (isinstance(corpo, dict) and corpo.get("is_toggleable"))


def _motivo_preservacao(bloco: dict[str, Any]) -> str:
    tipo = str(bloco.get("type", ""))
    if tipo in _TIPOS_PRESERVADOS_VISIVEIS or (
        tipo.startswith("heading_") and tipo in TIPOS_RECRIAVEIS
    ):
        return (
            f"'{tipo}' não se recria a partir de Markdown; o texto dele aparece em "
            "'conteudo' e continua na página — não o reescreva, ou ele fica duplicado"
        )
    return f"'{tipo}' não se recria a partir de Markdown"


@dataclass
class _Achados:
    """O que a varredura de uma subárvore encontrou."""

    databases: list[tuple[str, str]] = field(default_factory=list)
    nao_recriavel: str | None = None


def _varrer_subarvore(cliente: NotionClient, bloco_id: str) -> _Achados:
    """Percorre os descendentes de um bloco, um GET por nível, em sequência.

    Não desce em ``child_page`` nem em ``child_database`` (uma subpágina tem a
    própria árvore; as linhas de um database não são blocos): eles contam como
    achados e param ali. Registra todo ``child_database`` e o primeiro tipo que
    não se recria a partir de Markdown.
    """

    achados = _Achados()
    fila: deque[str] = deque([bloco_id])
    while fila:
        for filho in cliente.ler_blocos(fila.popleft(), buscar_todos=True):
            tipo = str(filho.get("type", ""))
            if tipo == "child_database":
                titulo = str((filho.get("child_database") or {}).get("title", ""))
                achados.databases.append((str(filho.get("id", "")), titulo))
            if achados.nao_recriavel is None and not _recriavel_isolado(filho):
                achados.nao_recriavel = tipo
            if tipo in ("child_page", "child_database"):
                continue
            if filho.get("has_children") and filho.get("id"):
                fila.append(str(filho["id"]))
    return achados


@dataclass
class _PlanoLimpeza:
    apagar: list[tuple[str, str]] = field(default_factory=list)
    preservados: list[tuple[str, str]] = field(default_factory=list)
    motivos: dict[str, str] = field(default_factory=dict)


def _analisar_pagina(
    cliente: NotionClient,
    page_id: str,
    *,
    procurar_databases: bool,
    planejar_limpeza: bool,
    incluir_nao_recriaveis: bool = False,
) -> tuple[list[tuple[str, str]], _PlanoLimpeza]:
    """Uma leitura da página serve à guarda de database e ao plano de limpeza.

    A proteção olhava só o topo: um toggle com um database, uma subpágina ou
    uma imagem dentro era apagado com tudo. Aqui cada bloco de topo com filhos
    tem a subárvore varrida (quando isso muda alguma decisão), e um bloco
    recriável que **contém** algo não recriável é preservado inteiro.
    """

    databases: list[tuple[str, str]] = []
    plano = _PlanoLimpeza()
    for bloco in cliente.ler_blocos(page_id, buscar_todos=True):
        bloco_id = str(bloco.get("id") or "")
        tipo = str(bloco.get("type", ""))
        if tipo == "child_database":
            titulo = str((bloco.get("child_database") or {}).get("title", ""))
            databases.append((bloco_id, titulo))
        recriavel = _recriavel_isolado(bloco)
        precisa_descer = (
            bool(bloco.get("has_children"))
            and bool(bloco_id)
            and tipo not in ("child_page", "child_database")
            and (
                procurar_databases
                or (planejar_limpeza and recriavel and not incluir_nao_recriaveis)
            )
        )
        achados = _varrer_subarvore(cliente, bloco_id) if precisa_descer else None
        if achados:
            databases.extend(achados.databases)
        if not planejar_limpeza or not bloco_id:
            continue
        if incluir_nao_recriaveis:
            plano.apagar.append((bloco_id, tipo))
        elif not recriavel:
            plano.preservados.append((bloco_id, tipo))
            plano.motivos[bloco_id] = _motivo_preservacao(bloco)
        elif achados and achados.nao_recriavel:
            plano.preservados.append((bloco_id, tipo))
            plano.motivos[bloco_id] = (
                f"contém '{achados.nao_recriavel}', que não se recria a partir de "
                "Markdown; o bloco foi mantido inteiro (com o texto antigo dentro)"
            )
        else:
            plano.apagar.append((bloco_id, tipo))
    return databases, plano


def _executar_limpeza(cliente: NotionClient, plano: _PlanoLimpeza) -> ResultadoLimpeza:
    resultado = ResultadoLimpeza(
        preservados=list(plano.preservados), motivos=dict(plano.motivos)
    )
    for indice, (bloco_id, tipo) in enumerate(plano.apagar):
        try:
            cliente.excluir_bloco(bloco_id)
        except NotionSyncError as erro:
            raise LimpezaIncompletaError(
                apagados=resultado.apagados_ids,
                pendentes=plano.apagar[indice:],
                causa=erro,
            ) from erro
        resultado.apagados += 1
        resultado.apagados_ids.append((bloco_id, tipo))
    return resultado


def databases_da_pagina(
    page_id: str,
    *,
    profundo: bool = False,
    cliente: NotionClient | None = None,
) -> list[tuple[str, str]]:
    """Lista as databases que moram **dentro** de uma página.

    Serve para responder, antes de escrever, a pergunta que decide tudo: *o
    conteúdo desta página é texto, ou são as linhas de uma tabela?* Um link do
    Notion não deixa isso claro — a página que contém uma database parece um
    documento comum até você abrir.

    Args:
        page_id: ID da página a inspecionar.
        profundo: Também procura databases **aninhadas** (dentro de colunas,
            toggles, callouts, blocos sincronizados…) — o arranjo comum na
            interface. Custa um GET por bloco com filhos; sem ele, só o topo.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        ``(database_id, título)`` de cada ``child_database`` encontrado, na
        ordem de leitura. Lista vazia quando a página é só conteúdo.
    """

    cli = cliente or _cliente_padrao()
    if profundo:
        databases, _ = _analisar_pagina(
            cli, page_id, procurar_databases=True, planejar_limpeza=False
        )
        return databases
    encontradas: list[tuple[str, str]] = []
    for bloco in cli.ler_blocos(page_id, buscar_todos=True):
        if bloco.get("type") != "child_database":
            continue
        filho = bloco.get("child_database") or {}
        encontradas.append((str(bloco.get("id", "")), str(filho.get("title", ""))))
    return encontradas


def _blocos_criados(
    resultados: list[dict[str, Any]], lote: list[dict[str, Any]]
) -> list[BlocoCriado]:
    """Casa os ``results`` com o lote enviado (o tipo sai do que foi enviado)."""

    criados: list[BlocoCriado] = []
    for resultado, enviado in zip(resultados, lote, strict=False):
        bloco_id = str(resultado.get("id") or "") if isinstance(resultado, dict) else ""
        if bloco_id:
            criados.append(BlocoCriado(id=bloco_id, tipo=str(enviado.get("type", ""))))
    return criados


def _desfazer(
    cliente: NotionClient, criados: list[BlocoCriado]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Apaga os blocos novos já criados; devolve (desfeitos, que ficaram)."""

    desfeitos: list[str] = []
    ficaram: list[tuple[str, str]] = []
    for bloco in reversed(criados):
        try:
            cliente.excluir_bloco(bloco.id)
            desfeitos.append(bloco.id)
        except NotionSyncError:
            ficaram.append((bloco.id, bloco.tipo))
    ficaram.reverse()
    return desfeitos, ficaram


def _anexar_em_lotes(
    cliente: NotionClient,
    page_id: str,
    lotes: list[list[dict[str, Any]]],
    *,
    apos_bloco_id: str | None,
    inicio: bool,
    substituicao: bool,
) -> list[BlocoCriado]:
    """Envia os lotes em sequência, encadeando a posição; desfaz tudo se um falhar.

    Com posição, o lote seguinte entra depois do **último bloco criado** pelo
    anterior — os primeiros ``len(lote)`` itens de ``results``, porque com
    ``position`` a API devolve também os irmãos seguintes (medido).
    """

    total = sum(len(lote) for lote in lotes)
    criados: list[BlocoCriado] = []
    ancora = apos_bloco_id
    no_inicio = inicio

    def falha(
        erro: BaseException | None, incerto: bool, detalhe: str = ""
    ) -> EscritaParcialError:
        desfeitos, ficaram = _desfazer(cliente, criados)
        return EscritaParcialError(
            page_id=page_id,
            total=total,
            criados=ficaram,
            desfeitos=desfeitos,
            lote_incerto=incerto,
            substituicao=substituicao,
            causa=erro,
            detalhe=detalhe,
        )

    for numero, lote in enumerate(lotes):
        posicao: dict[str, Any] = {}
        if no_inicio:
            posicao["no_inicio"] = True
        elif ancora:
            posicao["apos_bloco_id"] = ancora
        try:
            resposta = cliente.anexar_blocos(page_id, lote, **posicao)
        except NotionSyncError as erro:
            incerto = isinstance(erro, NotionConnectionError) or (
                isinstance(erro, NotionHTTPError) and erro.status_code >= 500
            )
            raise falha(erro, incerto) from erro
        resultados = resposta.get("results") if isinstance(resposta, dict) else None
        resultados = [r for r in (resultados or []) if isinstance(r, dict)]
        novos = resultados[: len(lote)]
        criados.extend(_blocos_criados(novos, lote))
        if resultados and len(novos) < len(lote):
            raise falha(None, True, f"enviados {len(lote)} blocos, mas a API criou {len(novos)}")
        if numero + 1 < len(lotes) and (no_inicio or ancora):
            ultimo = str(novos[-1].get("id") or "") if novos else ""
            if not ultimo:
                raise falha(
                    None,
                    False,
                    "a API não devolveu o ID do último bloco criado, sem o qual o lote "
                    "seguinte não tem onde ser encaixado",
                )
            ancora, no_inicio = ultimo, False
    return criados


def escrever_conteudo(
    page_id: str,
    markdown: str,
    *,
    substituir: bool = False,
    apagar_nao_recriaveis: bool = False,
    mesmo_com_database: bool = False,
    apos_bloco_id: str | None = None,
    inicio: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoEscrita:
    """Escreve conteúdo (em Markdown) numa página — por padrão, no **final**.

    Por padrão **anexa**: o conteúdo já existente é preservado e os novos blocos
    entram depois dele. ``apos_bloco_id`` insere logo depois de um bloco irmão e
    ``inicio`` insere no começo da página. Com ``substituir=True`` a página fica
    com o Markdown informado no lugar do corpo recriável.

    **Nada é apagado antes de o conteúdo novo estar escrito.** A ordem é:

    1. converter e **validar** o Markdown contra os limites documentados da API
       (:func:`~notion_starter.content.validar_blocos`) — entrada vazia ou que
       a API recusaria levanta erro sem tocar na página;
    2. ler a página uma vez (guarda de database e, ao substituir, o plano do que
       apagar, com os IDs guardados **antes** de escrever);
    3. anexar em lotes que respeitam 100 blocos, 1000 elementos e 500 KB por
       requisição; se um lote falhar, os blocos novos já criados são apagados de
       novo e nada do conteúdo antigo foi tocado (:class:`EscritaParcialError`);
    4. só então, ao substituir, apagar os blocos antigos planejados. Como o
       conteúdo novo entra no fim, a ordem final é a mesma de antes: o que foi
       preservado, depois o texto novo.

    Ao substituir, só é apagado o que o Markdown recria do mesmo tipo
    (:data:`TIPOS_RECRIAVEIS`); o resto — imagem, arquivo, embed, subpágina,
    ``child_database``, equação, toggle, callout… e qualquer bloco que
    **contenha** um deles — é preservado por padrão (ver :func:`limpar_conteudo`).

    Args:
        page_id: ID da página (ou bloco) que receberá o conteúdo.
        markdown: Texto em Markdown.
        substituir: Troca o corpo recriável pelo conteúdo novo.
        apagar_nao_recriaveis: Junto com ``substituir``, apaga **também** os
            blocos não recriáveis. Só passe ``True`` com pedido explícito.
        mesmo_com_database: Permite escrever numa página que contém database
            (em qualquer nível). Só passe ``True`` quando a intenção for mesmo
            um bloco solto na página, e não uma linha da tabela.
        apos_bloco_id: Insere logo depois deste bloco, filho direto de
            ``page_id``. A API recusa âncora de outra página (400 "is not
            parented by"). Exclusivo com ``inicio`` e com ``substituir``.
        inicio: Insere no começo da página. Exclusivo com ``apos_bloco_id`` e
            com ``substituir``.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`ResultadoEscrita` com a contagem, os IDs criados e, ao
        substituir, o que foi apagado/preservado. Compara e converte para
        ``int`` como a contagem de anexados, mantendo quem usava só o número.

    Raises:
        ValueError: Markdown vazio, ou posição combinada com ``substituir``/
            ``apos_bloco_id`` junto com ``inicio``.
        ConteudoInvalidoError: O conteúdo passa de um limite da API.
        EscritaAbaixoDeDatabaseError: A página contém database e
            ``mesmo_com_database`` é falso.
        EscritaParcialError: Um lote falhou; os criados foram desfeitos (ver
            os atributos). Deriva de ``RuntimeError``, como antes.
        LimpezaIncompletaError: O conteúdo novo foi escrito, mas apagar o
            antigo parou no meio (lista o que foi e o que ficou).

    Note:
        **Página que contém database é recusada por padrão.** É o erro mais caro
        de reverter de quem recebe um link do Notion sem abrir: o texto vai
        parar solto embaixo da tabela, onde não vira linha, não aparece em view
        nenhuma e ninguém encontra depois. Quando o alvo é uma database, o
        trabalho é **nas linhas** — e a mensagem do erro traz o caminho pronto.
    """

    if apos_bloco_id and inicio:
        raise ValueError("Use apos_bloco_id ou inicio, não os dois ao mesmo tempo.")
    if substituir and (apos_bloco_id or inicio):
        raise ValueError(
            "apos_bloco_id/inicio não combinam com substituir: substituir troca o corpo "
            "inteiro e poderia apagar a própria âncora."
        )
    blocos = markdown_para_blocos(markdown)
    if not blocos:
        raise ValueError("O conteúdo está vazio — nada a escrever.")
    validar_blocos(blocos)
    lotes = planejar_lotes(blocos)

    cliente = cliente or _cliente_padrao()

    # Antes de qualquer escrita: esta página é um documento ou a casa de uma
    # tabela? Checar aqui (e não só na borda) faz a proteção valer para CLI,
    # MCP e qualquer script que use o serviço.
    plano = _PlanoLimpeza()
    if not mesmo_com_database or substituir:
        dentro, plano = _analisar_pagina(
            cliente,
            page_id,
            procurar_databases=not mesmo_com_database,
            planejar_limpeza=substituir,
            incluir_nao_recriaveis=apagar_nao_recriaveis,
        )
        if dentro and not mesmo_com_database:
            raise EscritaAbaixoDeDatabaseError(page_id, dentro)

    criados = _anexar_em_lotes(
        cliente,
        page_id,
        lotes,
        apos_bloco_id=apos_bloco_id,
        inicio=inicio,
        substituicao=substituir,
    )

    limpeza: ResultadoLimpeza | None = None
    if substituir:
        try:
            limpeza = _executar_limpeza(cliente, plano)
        except LimpezaIncompletaError as erro:
            raise LimpezaIncompletaError(
                apagados=erro.apagados,
                pendentes=erro.pendentes,
                causa=erro.causa,
                blocos_novos=[bloco.id for bloco in criados],
            ) from erro.causa
    return ResultadoEscrita(anexados=len(blocos), limpeza=limpeza, criados=criados)


def criar_subpagina(
    pagina_pai_id: str,
    titulo: str,
    *,
    markdown: str | None = None,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Cria uma página filha simples dentro de outra página.

    Diferente de uma linha de database, esta é uma página **solta**, pendurada
    diretamente na página-pai — o mesmo padrão usado para organizar READMEs de
    repositório e as subpáginas de acompanhamento de projeto (Estado atual,
    Trabalho em andamento, Problemas encontrados, Decisões e registros — ver
    ``DESIGN-WORKSPACE-NOTION.md`` no hub Automações do Notion).

    Args:
        pagina_pai_id: ID da página que receberá a subpágina.
        titulo: Título da subpágina.
        markdown: Conteúdo opcional (em Markdown) já preenchido na criação.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A resposta crua da API do Notion para a subpágina criada.

    Raises:
        ValueError: Se ``pagina_pai_id`` ou ``titulo`` forem vazios.
        ConteudoInvalidoError: Se o Markdown passar de um limite da API.
    """

    pagina_pai_id = (pagina_pai_id or "").strip()
    titulo = (titulo or "").strip()
    if not pagina_pai_id:
        raise ValueError("pagina_pai_id é obrigatório.")
    if not titulo:
        raise ValueError("titulo é obrigatório.")

    blocos = markdown_para_blocos(markdown) if markdown else None
    if blocos:
        # Antes do POST: um 400 de limite depois dele deixaria a página criada
        # pela metade.
        validar_blocos(blocos)
    cliente = cliente or _cliente_padrao()
    return cliente.criar_subpagina(pagina_pai_id, titulo, blocos=blocos)


def editar_bloco(
    block_id: str,
    markdown: str,
    *,
    conferir_atual: bool = False,
    aceitar_perda_de_formatacao: bool = False,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Substitui o texto de **um** bloco existente por Markdown.

    A API edita um bloco de cada vez, então o ``markdown`` precisa gerar
    exatamente um bloco: várias linhas eram truncadas em silêncio para a
    primeira, e agora são recusadas (:class:`EdicaoMultiblocoError`) sem
    nenhuma chamada à API. Um bloco de código cercado por crases, mesmo com
    várias linhas, é um bloco só.

    Com ``conferir_atual=True`` o bloco é lido antes (``GET /blocks/{id}``) e:

    - texto **sem prefixo** de bloco mantém o tipo atual (um heading, callout,
      toggle ou to-do continua sendo o que era; sem isso, o texto puro virava
      ``paragraph`` e a API respondia 400 "Block type mismatch");
    - prefixo de **outro** tipo é recusado (:class:`TrocaDeTipoError`) — a API
      não troca o tipo de um bloco;
    - num bloco de código, o texto inteiro é o código (sem parse de Markdown);
    - se o texto atual tiver o que Markdown não representa (menção, equação,
      sublinhado, cor), a edição é recusada com a lista do que seria perdido
      (:class:`PerdaDeFormatacaoError`), a menos que
      ``aceitar_perda_de_formatacao`` seja verdadeiro. Para mudar só um
      trecho preservando o resto, use :func:`trocar_trecho`.

    Sem ``conferir_atual`` (padrão, compatível com quem já chama) não há
    leitura: o tipo sai do Markdown, como antes.

    Args:
        block_id: ID do bloco a editar.
        markdown: O novo conteúdo do bloco, em Markdown (um bloco).
        conferir_atual: Lê o bloco antes e aplica as proteções acima.
        aceitar_perda_de_formatacao: Com ``conferir_atual``, grava mesmo que
            menções/cores/sublinhado se percam.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A resposta JSON do bloco atualizado.

    Raises:
        ValueError: Se ``markdown`` não gerar nenhum bloco.
        EdicaoMultiblocoError: O Markdown gerou mais de um bloco.
        BlocoSemTextoError: (``conferir_atual``) O bloco não tem texto.
        TrocaDeTipoError: (``conferir_atual``) O Markdown pede outro tipo.
        PerdaDeFormatacaoError: (``conferir_atual``) A edição perderia
            menção, equação, sublinhado ou cor.
    """

    blocos = markdown_para_blocos(markdown)
    if not blocos:
        raise ValueError("O conteúdo está vazio — nada a editar.")
    # Filhos (item recuado) contam: o PATCH de um bloco não aceita children.
    quantidade = sum(contar_elementos(bloco) for bloco in blocos)
    cli = cliente or _cliente_padrao()
    if not conferir_atual:
        if quantidade != 1:
            raise EdicaoMultiblocoError(quantidade)
        novo = blocos[0]
        tipo = novo["type"]
        return cli.atualizar_bloco(block_id, {tipo: novo[tipo]})

    atual = cli.obter_bloco(block_id)
    tipo_atual = str(atual.get("type", ""))
    corpo_atual = atual.get(tipo_atual)
    if not isinstance(corpo_atual, dict) or "rich_text" not in corpo_atual:
        raise BlocoSemTextoError(block_id, tipo_atual)

    corpo: dict[str, Any]
    if tipo_atual == "code":
        cercado = len(blocos) == 1 and blocos[0]["type"] == "code"
        texto = markdown.strip("\n")
        corpo = {
            "rich_text": blocos[0]["code"]["rich_text"] if cercado else rich_text_de_codigo(texto)
        }
    else:
        if quantidade != 1:
            raise EdicaoMultiblocoError(quantidade)
        novo = blocos[0]
        tipo_pedido = str(novo["type"])
        # Texto puro vira "paragraph" no Markdown: sem prefixo, vale o tipo atual.
        if tipo_pedido != "paragraph" and tipo_pedido != tipo_atual:
            raise TrocaDeTipoError(block_id, tipo_atual, tipo_pedido)
        corpo = {"rich_text": novo[tipo_pedido]["rich_text"]}
        if tipo_pedido == "to_do":
            corpo["checked"] = novo["to_do"]["checked"]

    if not aceitar_perda_de_formatacao:
        perdas = perdas_de_formatacao(corpo_atual.get("rich_text") or [])
        if perdas:
            raise PerdaDeFormatacaoError(block_id, perdas)
    return cli.atualizar_bloco(block_id, {tipo_atual: corpo})


@dataclass
class ResultadoTroca:
    """O que :func:`trocar_trecho` gravou.

    Attributes:
        id: ID do bloco.
        tipo: Tipo do bloco (não muda).
        ocorrencias: Quantas ocorrências foram trocadas.
        markdown: O bloco como ficou, lido da resposta do PATCH.
        editado_em: ``last_edited_time`` da resposta (a API arredonda ao minuto,
            observado — não serve para ordenar edições do mesmo minuto).
    """

    id: str
    tipo: str
    ocorrencias: int
    markdown: str
    editado_em: str


def trocar_trecho(
    block_id: str,
    antigo: str,
    novo: str,
    *,
    todas: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoTroca:
    """Troca um trecho do texto de um bloco **sem reescrever** o resto.

    Lê o bloco, troca ``antigo`` por ``novo`` só dentro dos pedaços de texto
    e grava o *rich text* inteiro de volta (a API substitui o campo todo),
    com cada anotação, link, menção e equação como estavam. É o caminho para
    corrigir um horário num título colorido ou um nome num parágrafo com
    menção de data, que a edição por Markdown destruiria. Os demais campos do
    bloco (cor, ``checked``, linguagem) não são enviados e ficam intactos.

    Args:
        block_id: ID do bloco.
        antigo: Trecho a procurar.
        novo: Texto que entra no lugar.
        todas: Troca todas as ocorrências; sem isso, exige exatamente uma.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`ResultadoTroca`.

    Raises:
        BlocoSemTextoError: O bloco não tem texto.
        TrechoNaoEncontradoError, TrechoAmbiguoError, TrechoAtravessaItensError:
            Ver :func:`~notion_starter.content.trocar_trecho_rich_text`.
        RichTextNaoRegravavelError: O bloco tem item que a API não aceita de
            volta (ex.: menção de prévia de link).
    """

    cli = cliente or _cliente_padrao()
    atual = cli.obter_bloco(block_id)
    tipo = str(atual.get("type", ""))
    corpo = atual.get(tipo)
    if not isinstance(corpo, dict) or "rich_text" not in corpo:
        raise BlocoSemTextoError(block_id, tipo)
    novos, ocorrencias = trocar_trecho_rich_text(
        corpo.get("rich_text") or [], antigo, novo, todas=todas, block_id=block_id
    )
    resposta = cli.atualizar_bloco(block_id, {tipo: {"rich_text": novos}})
    lido = resposta if isinstance(resposta, dict) and resposta.get("type") else {}
    return ResultadoTroca(
        id=block_id,
        tipo=tipo,
        ocorrencias=ocorrencias,
        markdown=blocos_para_markdown([lido]) if lido else "",
        editado_em=str(lido.get("last_edited_time") or ""),
    )


def excluir_bloco(
    block_id: str,
    *,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Exclui (arquiva) um bloco. Operação destrutiva — confirme antes de chamar.

    Args:
        block_id: ID do bloco a excluir.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A resposta JSON do bloco arquivado.
    """

    return (cliente or _cliente_padrao()).excluir_bloco(block_id)


#: Tipos cujo DELETE leva **uma árvore inteira** para a lixeira.
_TIPOS_DE_EXCLUSAO_ARRISCADA = frozenset({"child_page", "child_database"})


@dataclass
class ResultadoExclusao:
    """O que :func:`apagar_bloco_verificado` mandou para a lixeira.

    Attributes:
        id: ID do bloco.
        tipo: Tipo do bloco.
        resumo: Título (subpágina/database) ou preview do texto.
        tem_filhos: Se havia filhos (foram junto para a lixeira).
    """

    id: str
    tipo: str
    resumo: str
    tem_filhos: bool


def apagar_bloco_verificado(
    block_id: str,
    *,
    forcar_tipos_arriscados: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoExclusao:
    """Lê o bloco, recusa subpágina/database sem pedido explícito e só então apaga.

    ``excluir_bloco`` apaga o que receber: medido no workspace real, apagar
    por engano o ID de uma subpágina mandou para a lixeira 11 subpáginas, 2
    databases e 28 linhas, e a resposta era igual à de apagar um parágrafo.
    Aqui o alvo é conferido antes (``GET /blocks/{id}``) e o resultado diz o
    que foi apagado. Para desfazer, use :func:`restaurar_blocos` com o ID.

    Args:
        block_id: ID do bloco.
        forcar_tipos_arriscados: Necessário para apagar ``child_page`` ou
            ``child_database`` — leva tudo o que está dentro.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`ResultadoExclusao`.

    Raises:
        ExclusaoArriscadaError: Subpágina/database sem ``forcar_tipos_arriscados``.
    """

    cli = cliente or _cliente_padrao()
    bloco = cli.obter_bloco(block_id)
    tipo = str(bloco.get("type", ""))
    titulo = str((bloco.get(tipo) or {}).get("title", "")) if tipo in (
        _TIPOS_DE_EXCLUSAO_ARRISCADA
    ) else ""
    if tipo in _TIPOS_DE_EXCLUSAO_ARRISCADA and not forcar_tipos_arriscados:
        raise ExclusaoArriscadaError(block_id, tipo, titulo)
    cli.excluir_bloco(block_id)
    return ResultadoExclusao(
        id=str(bloco.get("id") or block_id),
        tipo=tipo,
        resumo=titulo or _preview_bloco(bloco),
        tem_filhos=bool(bloco.get("has_children")),
    )


def limpar_conteudo(
    page_id: str,
    *,
    incluir_nao_recriaveis: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoLimpeza:
    """Apaga os blocos de topo recriáveis de uma página. Destrutivo — confirme antes.

    Zera o corpo da página num passo só, em vez de exigir apagar bloco a bloco
    pelo ID. É o que destrava corrigir uma página que virou bagunça: limpar e
    reescrever, sem ficar empilhando conteúdo.

    **Por padrão só apaga o que o Markdown recria** (lista branca
    :data:`TIPOS_RECRIAVEIS`) e preserva o resto: imagem, arquivo, embed,
    subpágina, ``child_database`` (apagar leva o database inteiro), equação,
    ``link_to_page``, sumário, toggle, callout… — e também um bloco recriável
    que **contenha** algo assim (um item de lista com uma imagem dentro, por
    exemplo), porque apagar o pai leva os filhos para a lixeira. Cada
    preservação vem com o motivo em :attr:`ResultadoLimpeza.motivos`.

    O Notion arquiva (não destrói): cada bloco apagado volta com
    :func:`restaurar_blocos` — por isso o resultado traz os IDs: é com eles que
    a API restaura.

    Args:
        page_id: ID da página (ou bloco) cujo corpo será apagado.
        incluir_nao_recriaveis: Apaga **também** os blocos não recriáveis. Só
            passe ``True`` a partir de um pedido explícito de quem opera.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`ResultadoLimpeza` com o que foi apagado (contagem e IDs) e o
        que foi mantido. Ele compara e converte para ``int`` como a contagem de
        apagados, então quem só usava o número continua funcionando.

    Raises:
        LimpezaIncompletaError: Uma exclusão falhou no meio; a exceção lista o
            que já foi para a lixeira e o que ficou.
    """

    cli = cliente or _cliente_padrao()
    _, plano = _analisar_pagina(
        cli,
        page_id,
        procurar_databases=False,
        planejar_limpeza=True,
        incluir_nao_recriaveis=incluir_nao_recriaveis,
    )
    return _executar_limpeza(cli, plano)


def restaurar_blocos(
    block_ids: list[str],
    *,
    cliente: NotionClient | None = None,
) -> ResultadoRestauracao:
    """Tira blocos da lixeira — o desfazer de :func:`limpar_conteudo`/:func:`excluir_bloco`.

    Cada bloco volta com o mesmo ID e os filhos, mas no **fim** da lista de
    filhos do pai (medido: a API não o devolve à posição original). Um ID que
    falhar não interrompe os demais.

    Args:
        block_ids: IDs a restaurar (ex.: ``ResultadoLimpeza.apagados_ids``).
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um :class:`ResultadoRestauracao`.
    """

    cli = cliente or _cliente_padrao()
    resultado = ResultadoRestauracao()
    for bloco_id in block_ids:
        try:
            cli.restaurar_bloco(bloco_id)
        except NotionSyncError as erro:
            resultado.falhas.append((bloco_id, str(erro)))
            continue
        resultado.restaurados.append(bloco_id)
    return resultado


def buscar(
    query: str | None = None,
    *,
    cliente: NotionClient | None = None,
) -> list[dict[str, str]]:
    """Pesquisa páginas e databases visíveis à integração.

    Args:
        query: Texto para casar com o título. ``None`` lista tudo o que é visível.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Lista de ``{"id", "tipo", "titulo", "url"}`` — uma linha por item.
    """

    itens = (cliente or _cliente_padrao()).buscar(query=query, buscar_todos=True)
    return [
        {
            "id": item.get("id", ""),
            "tipo": item.get("object", ""),
            "titulo": _titulo_de_item(item),
            "url": item.get("url", ""),
        }
        for item in itens
    ]


def listar_linhas(
    database_id: str,
    *,
    propriedades: bool = False,
    cliente: NotionClient | None = None,
) -> list[dict[str, Any]]:
    """Lista as linhas (páginas) de um database, resolvendo *data sources*.

    Um database não tem "conteúdo" em blocos: o que ele guarda são linhas. Esta
    função as devolve já normalizadas. Suporta o modelo novo do Notion
    (multi-fonte): resolve os *data sources* do database e consulta cada um.

    Args:
        database_id: ID do database.
        propriedades: Quando ``True``, cada linha ganha a chave extra
            ``"propriedades"`` com todas as colunas da página já reduzidas a
            ``nome -> valor simples`` (mesmo leitor usado por
            :func:`ler_conteudo`, via :func:`~notion_starter.readers.extrair_valores`)
            — cobre analisar um database inteiro sem uma chamada de
            ``conteudo``/``obter_pagina`` por linha. ``False`` (padrão) mantém
            a resposta enxuta de sempre.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Lista de ``{"id", "titulo", "url"}`` — uma linha por página do
        database, com ``"propriedades"`` a mais quando pedido. Vazia quando o
        database não tem *data source* acessível à integração (compartilhe-o
        com a integração no Notion para liberar a leitura).
    """

    cli = cliente or _cliente_padrao()
    if propriedades:
        from notion_starter.readers import extrair_valores

    linhas: list[dict[str, Any]] = []
    for fonte in cli.listar_data_sources(database_id):
        fonte_id = fonte.get("id")
        if not fonte_id:
            continue
        for pagina in cli.consultar_data_source(fonte_id, buscar_todos=True):
            linha: dict[str, Any] = {
                "id": pagina.get("id", ""),
                "titulo": _titulo_de_item(pagina),
                "url": pagina.get("url", ""),
            }
            if propriedades:
                linha["propriedades"] = extrair_valores(pagina)
            linhas.append(linha)
    return linhas


def _titulo_de_item(item: dict[str, Any]) -> str:
    """Extrai um título legível de uma página ou database do ``/search``.

    Páginas guardam o título na propriedade do tipo ``title``; databases, no
    campo ``title`` de topo. Cai para ``"(sem título)"`` quando vazio.
    """

    if item.get("object") == "database":
        partes = item.get("title", [])
    else:
        partes = []
        for prop in item.get("properties", {}).values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                partes = prop.get("title", [])
                break
    titulo = "".join(p.get("plain_text", "") for p in partes).strip()
    return titulo or "(sem título)"
