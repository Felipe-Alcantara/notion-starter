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

from typing import Any

from notion_starter import (
    NotionClient,
    blocos_para_markdown,
    markdown_para_blocos,
)

# Tamanho do trecho de texto mostrado ao listar blocos. O bastante para
# reconhecer o bloco (e casar com o que se lê na página) sem poluir a saída.
_LARGURA_PREVIEW = 100

# O Notion aceita no máximo 100 blocos filhos por requisição de append. O limite
# de 2000 caracteres por item de rich_text já é tratado na lib (fatiamento em
# ``content.py``); aqui cuidamos do limite de blocos por requisição.
_MAX_BLOCOS_POR_REQUISICAO = 100


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


def listar_blocos(
    page_id: str,
    *,
    cliente: NotionClient | None = None,
) -> list[dict[str, str]]:
    """Lista os blocos de topo de uma página com **ID**, tipo e um preview.

    É o par que faltava para ``editar-bloco``/``apagar-bloco``: ``conteudo`` lê o
    corpo como Markdown, mas descarta os IDs — sem eles não dá para editar nem
    apagar um bloco específico. Esta função devolve cada bloco de topo já com o
    ``id`` pronto para essas operações. Lê só um nível (os blocos que se apagam/
    editam diretamente); o conteúdo dentro de colunas/toggles não é expandido.

    Args:
        page_id: ID da página (ou bloco) cujos filhos serão listados.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Lista de ``{"id", "tipo", "preview"}`` — uma entrada por bloco de topo,
        na ordem em que aparecem na página.
    """

    blocos = (cliente or _cliente_padrao()).ler_blocos(page_id, buscar_todos=True)
    return [
        {
            "id": bloco.get("id", ""),
            "tipo": bloco.get("type", ""),
            "preview": _preview_bloco(bloco),
        }
        for bloco in blocos
    ]


def escrever_conteudo(
    page_id: str,
    markdown: str,
    *,
    substituir: bool = False,
    cliente: NotionClient | None = None,
) -> int:
    """Anexa conteúdo (em Markdown) ao **final** de uma página.

    Por padrão **anexa**: o conteúdo já existente é preservado e os novos blocos
    entram depois dele. Com ``substituir=True``, o corpo atual é apagado antes de
    escrever — a página fica exatamente com o Markdown informado (útil para
    corrigir/reescrever sem ir empilhando blocos a cada tentativa). O Markdown é
    validado **antes** de apagar, então uma entrada vazia nunca zera a página.

    O envio é feito em lotes de até 100 blocos (limite do Notion por requisição)
    e, quando a API informa os blocos criados, confirma-se que a quantidade
    criada bate com a enviada — assim uma escrita parcial não passa despercebida.

    Args:
        page_id: ID da página (ou bloco) que receberá o conteúdo.
        markdown: Texto em Markdown a anexar.
        substituir: Quando verdadeiro, apaga o corpo atual antes de escrever.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A quantidade de blocos anexados.

    Raises:
        ValueError: Se ``markdown`` não gerar nenhum bloco.
        RuntimeError: Se a API criar menos blocos do que os enviados.
    """

    blocos = markdown_para_blocos(markdown)
    if not blocos:
        raise ValueError("O conteúdo está vazio — nada a escrever.")

    cliente = cliente or _cliente_padrao()
    if substituir:
        # Validar (acima) antes de apagar: entrada inválida nunca zera a página.
        limpar_conteudo(page_id, cliente=cliente)
    criados = 0
    for inicio in range(0, len(blocos), _MAX_BLOCOS_POR_REQUISICAO):
        lote = blocos[inicio : inicio + _MAX_BLOCOS_POR_REQUISICAO]
        resposta = cliente.anexar_blocos(page_id, lote)
        criados += len(resposta.get("results", []) or []) if isinstance(resposta, dict) else 0

    # Verificação pós-PATCH: se a API reportou os blocos criados, confirme que
    # não houve escrita parcial. Clientes que não retornam ``results`` (ex.: em
    # testes) informam 0 e a checagem é ignorada.
    if criados and criados != len(blocos):
        raise RuntimeError(
            f"Escrita parcial: enviados {len(blocos)} blocos, mas a API criou {criados}."
        )
    return len(blocos)


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
    """

    pagina_pai_id = (pagina_pai_id or "").strip()
    titulo = (titulo or "").strip()
    if not pagina_pai_id:
        raise ValueError("pagina_pai_id é obrigatório.")
    if not titulo:
        raise ValueError("titulo é obrigatório.")

    blocos = markdown_para_blocos(markdown) if markdown else None
    cliente = cliente or _cliente_padrao()
    return cliente.criar_subpagina(pagina_pai_id, titulo, blocos=blocos)


def editar_bloco(
    block_id: str,
    markdown: str,
    *,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Substitui o texto de um bloco existente por uma linha de Markdown.

    A API do Notion edita um bloco de cada vez; por isso o ``markdown`` aqui
    representa **um** bloco (a primeira linha não vazia). Para reescrever várias
    linhas, apague e escreva de novo.

    Args:
        block_id: ID do bloco a editar.
        markdown: Nova linha de conteúdo, em Markdown.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A resposta JSON do bloco atualizado.

    Raises:
        ValueError: Se ``markdown`` não gerar nenhum bloco.
    """

    blocos = markdown_para_blocos(markdown)
    if not blocos:
        raise ValueError("O conteúdo está vazio — nada a editar.")
    novo = blocos[0]
    tipo = novo["type"]
    return (cliente or _cliente_padrao()).atualizar_bloco(block_id, {tipo: novo[tipo]})


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


def limpar_conteudo(
    page_id: str,
    *,
    cliente: NotionClient | None = None,
) -> int:
    """Apaga **todos** os blocos de topo de uma página. Destrutivo — confirme antes.

    Zera o corpo da página num passo só, em vez de exigir apagar bloco a bloco
    pelo ID. É o que destrava corrigir uma página que virou bagunça: limpar e
    reescrever, sem ficar empilhando conteúdo. Como o Notion arquiva (não deleta
    de vez), os blocos ficam recuperáveis pela lixeira.

    Args:
        page_id: ID da página (ou bloco) cujo corpo será apagado.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        A quantidade de blocos apagados.
    """

    cli = cliente or _cliente_padrao()
    apagados = 0
    for bloco in cli.ler_blocos(page_id, buscar_todos=True):
        block_id = bloco.get("id")
        if block_id:
            cli.excluir_bloco(block_id)
            apagados += 1
    return apagados


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
    cliente: NotionClient | None = None,
) -> list[dict[str, str]]:
    """Lista as linhas (páginas) de um database, resolvendo *data sources*.

    Um database não tem "conteúdo" em blocos: o que ele guarda são linhas. Esta
    função as devolve já normalizadas. Suporta o modelo novo do Notion
    (multi-fonte): resolve os *data sources* do database e consulta cada um.

    Args:
        database_id: ID do database.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Lista de ``{"id", "titulo", "url"}`` — uma linha por página do database.
        Vazia quando o database não tem *data source* acessível à integração
        (compartilhe-o com a integração no Notion para liberar a leitura).
    """

    cli = cliente or _cliente_padrao()
    linhas: list[dict[str, str]] = []
    for fonte in cli.listar_data_sources(database_id):
        fonte_id = fonte.get("id")
        if not fonte_id:
            continue
        for pagina in cli.consultar_data_source(fonte_id, buscar_todos=True):
            linhas.append(
                {
                    "id": pagina.get("id", ""),
                    "titulo": _titulo_de_item(pagina),
                    "url": pagina.get("url", ""),
                }
            )
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
