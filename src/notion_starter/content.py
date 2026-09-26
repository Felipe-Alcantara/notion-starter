"""Conversão entre Markdown e blocos do Notion.

Par de **escrita** (``markdown_para_blocos``) e **leitura**
(``blocos_para_markdown``) que poupa quem usa a biblioteca de decorar o JSON
verboso de blocos do Notion. Uma IA (ou um humano) escreve Markdown comum e
recebe Markdown de volta ao ler uma página; a montagem dos blocos fica aqui.

São funções pequenas e puras — sem rede, sem estado. O acesso HTTP aos blocos
vive em :class:`notion_starter.client.NotionClient` (``ler_blocos``,
``anexar_blocos``, ``atualizar_bloco``, ``excluir_bloco``); a orquestração
("ler a página como texto", "anexar conteúdo") fica na camada de serviço.

Cobre os blocos de uso cotidiano em notas: títulos (``#``/``##``/``###``),
parágrafos, listas com marcador (``-``) e numeradas (``1.``), tarefas
(``- [ ]`` / ``- [x]``), citações (``>``), código (cercado por ``` ``` ```) e
divisória (``---``). Blocos fora desse conjunto, ao ler, viram texto simples a
partir do *rich text* do bloco, para nunca perder conteúdo silenciosamente.

Exemplo:
    >>> blocos = markdown_para_blocos("# Título\\n\\nUm parágrafo.")
    >>> blocos[0]["type"]
    'heading_1'
    >>> blocos_para_markdown(blocos)
    '# Título\\n\\nUm parágrafo.'
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any

from .constants import (
    MAX_BYTES_POR_REQUISICAO,
    MAX_ELEMENTOS_POR_REQUISICAO,
    MAX_ITENS_ARRAY,
    MAX_NIVEIS_ANINHADOS,
    MAX_RICH_TEXT,
    MAX_URL_LINK,
)
from .exceptions import (
    ConteudoInvalidoError,
    RichTextNaoRegravavelError,
    TrechoAmbiguoError,
    TrechoAtravessaItensError,
    TrechoNaoEncontradoError,
)
from .utils import fatiar_utf16

# Tipos de bloco do Notion que carregam *rich text* num campo de mesmo nome.
_TIPOS_TEXTO = (
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "quote",
    "callout",
    "toggle",
    "code",
)

# Linguagens aceitas pelo Notion em blocos de código. A API rejeita o bloco
# inteiro (HTTP 400) se a linguagem não estiver nesta lista — por isso qualquer
# valor fora dela é normalizado para "plain text".
_LINGUAGENS_NOTION = frozenset(
    {
        "abap", "abc", "agda", "arduino", "ascii art", "assembly", "bash",
        "basic", "bnf", "c", "c#", "c++", "clojure", "coffeescript", "coq",
        "css", "dart", "dhall", "diff", "docker", "ebnf", "elixir", "elm",
        "erlang", "f#", "flow", "fortran", "gherkin", "glsl", "go", "graphql",
        "groovy", "haskell", "hcl", "html", "idris", "java", "javascript",
        "json", "julia", "kotlin", "latex", "less", "lisp", "livescript",
        "llvm ir", "lua", "makefile", "markdown", "markup", "matlab",
        "mathematica", "mermaid", "nix", "notion formula", "objective-c",
        "ocaml", "pascal", "perl", "php", "plain text", "powershell", "prolog",
        "protobuf", "purescript", "python", "r", "racket", "reason", "ruby",
        "rust", "sass", "scala", "scheme", "scss", "shell", "smalltalk",
        "solidity", "sql", "swift", "toml", "typescript", "vb.net", "verilog",
        "vhdl", "visual basic", "webassembly", "xml", "yaml",
    }
)

# Apelidos comuns de linguagem (info string de cerca de código) → nome Notion.
_ALIAS_LINGUAGEM = {
    "py": "python", "py3": "python", "python3": "python",
    "js": "javascript", "node": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "sh": "shell", "zsh": "shell", "console": "shell", "shell-session": "shell",
    "cmd": "shell", "bat": "shell", "ps": "powershell", "ps1": "powershell",
    "yml": "yaml", "md": "markdown", "txt": "plain text", "text": "plain text",
    "": "plain text", "cs": "c#", "csharp": "c#", "cpp": "c++", "cplusplus": "c++",
    "htm": "html", "golang": "go", "dockerfile": "docker", "rs": "rust",
    "kt": "kotlin", "rb": "ruby", "objc": "objective-c",
}


def _normalizar_linguagem(lingua: str) -> str:
    """Mapeia a linguagem de uma cerca de código para um valor aceito pelo Notion.

    Apelidos comuns (``py``, ``js``, ``sh``…) viram o nome canônico; qualquer
    linguagem desconhecida vira ``"plain text"`` para nunca quebrar a escrita.
    """

    chave = (lingua or "").strip().lower()
    if chave in _LINGUAGENS_NOTION:
        return chave
    return _ALIAS_LINGUAGEM.get(chave, "plain text")


def _item_texto(
    content: str,
    *,
    annotations: dict[str, bool] | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    """Monta um item de *rich text* com anotações e link opcionais."""

    texto: dict[str, Any] = {"content": content}
    if link:
        texto["link"] = {"url": link}
    item: dict[str, Any] = {"type": "text", "text": texto}
    if annotations:
        item["annotations"] = dict(annotations)
    return item


def _fatiar_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Fatia um item de *rich text* respeitando o limite de 2000 unidades UTF-16.

    Preserva ``annotations`` e ``link`` em cada fatia, para o Notion concatenar
    os pedaços no mesmo bloco sem perder a formatação nem estourar o limite.
    """

    content = item.get("text", {}).get("content", "")
    if not content:
        return [item]
    fatias = fatiar_utf16(content, MAX_RICH_TEXT)
    if len(fatias) == 1:
        return [item]
    annotations = item.get("annotations")
    link = item.get("text", {}).get("link", {}).get("url")
    return [_item_texto(pedaco, annotations=annotations, link=link) for pedaco in fatias]


def _rich_text(texto: str) -> list[dict[str, Any]]:
    """Monta o *rich text* de um bloco, parseando a formatação inline do Markdown.

    Reconhece negrito, itálico, código inline, ``~~tachado~~`` e ``[texto](url)``,
    produzindo itens com ``annotations``/``link``. Itens acima de 2000 unidades
    UTF-16 são fatiados (o Notion os concatena no mesmo bloco), evitando o HTTP
    400 que a API retorna quando um único item excede o limite.
    """

    if not texto:
        return []
    itens: list[dict[str, Any]] = []
    for item in _parse_inline(texto):
        itens.extend(_fatiar_item(item))
    if len(itens) > MAX_ITENS_ARRAY:
        itens = [
            fatia
            for item in _fundir_adjacentes(_parse_inline(texto))
            for fatia in _fatiar_item(item)
        ]
    return itens


def _mesma_formatacao(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Dois itens de texto com as mesmas anotações e o mesmo link."""

    return (
        a.get("type") == b.get("type") == "text"
        and (a.get("annotations") or {}) == (b.get("annotations") or {})
        and a["text"].get("link") == b["text"].get("link")
    )


def _fundir_adjacentes(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Junta itens vizinhos de formatação idêntica num item só.

    O Notion aceita no máximo 100 itens de *rich text* por bloco; o parser pode
    gerar vizinhos iguais (ex.: um link recusado entre dois trechos simples).
    Juntar não muda nada do que aparece e adia o limite — por isso só é
    aplicado quando o texto passaria de 100 itens. O fatiamento de 2000
    caracteres roda depois.
    """

    fundidos: list[dict[str, Any]] = []
    for item in itens:
        if fundidos and _mesma_formatacao(fundidos[-1], item):
            fundidos[-1]["text"]["content"] += item["text"]["content"]
        else:
            fundidos.append(item)
    return fundidos


def _codigo_inline(texto: str) -> list[dict[str, Any]]:
    """Rich text de um bloco de código: texto cru, sem parse de formatação inline."""

    if not texto:
        return []
    itens: list[dict[str, Any]] = []
    for pedaco in fatiar_utf16(texto, MAX_RICH_TEXT):
        itens.append(_item_texto(pedaco))
    return itens


#: Menções que a referência de *rich text* documenta e que se reenviam pelo ID.
_MENCOES_POR_ID = ("page", "database")


def _mencao_para_requisicao(mencao: dict[str, Any]) -> dict[str, Any]:
    """Reduz uma menção lida da API ao formato aceito numa requisição."""

    tipo = str(mencao.get("type") or "")
    corpo = mencao.get(tipo)
    if not isinstance(corpo, dict):
        raise RichTextNaoRegravavelError(f"mention:{tipo or '?'}")
    if tipo == "user":
        # A resposta traz nome, avatar e e-mail do usuário; a requisição só
        # aceita a referência (o exemplo oficial usa object + id).
        return {"type": "user", "user": {"object": "user", "id": corpo.get("id")}}
    if tipo in _MENCOES_POR_ID:
        return {"type": tipo, tipo: {"id": corpo.get("id")}}
    if tipo in ("date", "template_mention"):
        return {"type": tipo, tipo: dict(corpo)}
    # link_preview é somente leitura; custom_emoji e afins não estão na
    # referência de menções — reenviar seria adivinhar.
    raise RichTextNaoRegravavelError(f"mention:{tipo}")


def item_para_requisicao(item: dict[str, Any]) -> dict[str, Any]:
    """Converte um item de *rich text* **lido** da API no formato de **escrita**.

    A leitura traz campos que a escrita não aceita ou ignora (``plain_text``,
    ``href``, o objeto completo do usuário mencionado). Reenviar o item cru
    funciona para texto, mas dá HTTP 400 numa menção de usuário. Aqui cada
    item vira só o que a requisição precisa, preservando ``annotations`` (cor,
    sublinhado, negrito…) e o link.

    Raises:
        RichTextNaoRegravavelError: Para tipos que não se regravam
            (ex.: menção ``link_preview``).
    """

    tipo = str(item.get("type") or ("text" if "text" in item or "plain_text" in item else ""))
    if tipo == "text":
        texto = item.get("text") if isinstance(item.get("text"), dict) else {}
        corpo: dict[str, Any] = {"content": texto.get("content", item.get("plain_text", ""))}
        link = texto.get("link")
        if isinstance(link, dict) and link.get("url"):
            corpo["link"] = {"url": link["url"]}
        novo: dict[str, Any] = {"type": "text", "text": corpo}
    elif tipo == "equation":
        equacao = item.get("equation") or {}
        novo = {"type": "equation", "equation": {"expression": equacao.get("expression", "")}}
    elif tipo == "mention":
        novo = {"type": "mention", "mention": _mencao_para_requisicao(item.get("mention") or {})}
    else:
        raise RichTextNaoRegravavelError(tipo or "?")
    anotacoes = item.get("annotations")
    if isinstance(anotacoes, dict) and anotacoes:
        novo["annotations"] = dict(anotacoes)
    return novo


def rich_text_para_requisicao(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aplica :func:`item_para_requisicao` a um *rich text* inteiro."""

    return [item_para_requisicao(item) for item in itens if isinstance(item, dict)]


# Marcadores de ênfase, do mais longo para o mais curto (a ordem evita que ``*``
# capture o que pertence a ``**``). Cada um liga uma anotação do Notion.
_ENFASE = (
    ("**", "bold"),
    ("__", "bold"),
    ("~~", "strikethrough"),
    ("*", "italic"),
    ("_", "italic"),
    ("`", "code"),
)


def _parse_inline(texto: str) -> list[dict[str, Any]]:
    """Tokeniza uma linha de Markdown em itens de *rich text*.

    Reconhece código inline (``` `x` ```), links e imagens (``[txt](url)`` /
    ``![alt](url)``) e ênfase aninhada (negrito, itálico, tachado). Trechos sem
    marcação viram itens de texto simples. Marcadores sem par fecham como texto
    literal, para nunca perder conteúdo.
    """

    itens: list[dict[str, Any]] = []
    _parse_inline_em(texto, {}, itens)
    return [item for item in itens if item["text"]["content"]]


def _parse_inline_em(
    texto: str,
    annotations: dict[str, bool],
    itens: list[dict[str, Any]],
) -> None:
    """Acrescenta a ``itens`` os tokens de ``texto`` sob as ``annotations`` ativas."""

    buffer: list[str] = []

    def descarregar() -> None:
        if buffer:
            itens.append(_item_texto("".join(buffer), annotations=annotations or None))
            buffer.clear()

    i = 0
    n = len(texto)
    while i < n:
        # Código inline: tudo entre crases é literal (não parseia o interior).
        if texto[i] == "`":
            fim = texto.find("`", i + 1)
            if fim != -1:
                descarregar()
                itens.append(
                    _item_texto(texto[i + 1 : fim], annotations={**annotations, "code": True})
                )
                i = fim + 1
                continue

        # Link ou imagem: [txt](url) e ![alt](url).
        consumido = _tentar_link(texto, i, annotations, descarregar, itens)
        if consumido:
            i = consumido
            continue

        # Ênfase: **x**, __x__, ~~x~~, *x*, _x_.
        marcado = _tentar_enfase(texto, i, annotations, descarregar, itens)
        if marcado:
            i = marcado
            continue

        buffer.append(texto[i])
        i += 1

    descarregar()


def _tentar_link(
    texto: str,
    i: int,
    annotations: dict[str, bool],
    descarregar: Any,
    itens: list[dict[str, Any]],
) -> int:
    """Tenta consumir ``[txt](url)`` ou ``![alt](url)`` a partir de ``i``.

    Devolve o índice após o token consumido, ou ``0`` se não houver link aqui.
    """

    imagem = texto[i] == "!" and texto[i + 1 : i + 2] == "["
    if not imagem and texto[i] != "[":
        return 0

    abre = i + 2 if imagem else i + 1
    fecha = texto.find("]", abre)
    if fecha == -1 or texto[fecha + 1 : fecha + 2] != "(":
        return 0
    fim_url = texto.find(")", fecha + 2)
    if fim_url == -1:
        return 0

    rotulo = texto[abre:fecha]
    url = texto[fecha + 2 : fim_url].strip()
    valida = _url_valida(url)
    descarregar()
    if imagem:
        # Imagem inline dentro de texto: vira link (se a URL for válida) com o alt.
        link = url if valida else None
        itens.append(_item_texto(rotulo or url, annotations=annotations or None, link=link))
    else:
        _parse_inline_em(rotulo, {**annotations}, itens)
        # Só aplica o link quando a URL é absoluta http(s)/mailto — o Notion
        # rejeita âncoras (#secao) e caminhos relativos; nesses casos fica só o texto.
        if valida:
            _aplicar_link(itens, url, rotulo)
    return fim_url + 1


def _url_valida(url: str) -> bool:
    """Indica se a URL é aceita pelo Notion como link.

    Só http/https/mailto absolutos e com até 2000 caracteres (limite
    documentado para ``text.link.url``); fora disso o texto fica sem link.
    """

    return url.startswith(("http://", "https://", "mailto:")) and len(url) <= MAX_URL_LINK


def _aplicar_link(itens: list[dict[str, Any]], url: str, rotulo: str) -> None:
    """Marca com ``link`` os últimos itens que formam o rótulo do link."""

    restante = len(rotulo)
    for item in reversed(itens):
        if restante <= 0:
            break
        item["text"]["link"] = {"url": url}
        restante -= len(item["text"]["content"])


def _tentar_enfase(
    texto: str,
    i: int,
    annotations: dict[str, bool],
    descarregar: Any,
    itens: list[dict[str, Any]],
) -> int:
    """Tenta consumir um trecho de ênfase a partir de ``i``.

    Devolve o índice após o trecho consumido, ou ``0`` se não houver ênfase aqui.
    """

    for marcador, anotacao in _ENFASE:
        if not texto.startswith(marcador, i):
            continue
        fim = texto.find(marcador, i + len(marcador))
        if fim == -1:
            continue
        interior = texto[i + len(marcador) : fim]
        if not interior:
            continue
        descarregar()
        if anotacao == "code":
            itens.append(_item_texto(interior, annotations={**annotations, "code": True}))
        else:
            _parse_inline_em(interior, {**annotations, anotacao: True}, itens)
        return fim + len(marcador)
    return 0


def _bloco(tipo: str, texto: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Monta um bloco do Notion de um tipo que carrega *rich text*.

    Blocos de código preservam o texto cru (sem parse de formatação inline); os
    demais tipos passam pelo parser de Markdown inline.
    """

    rich = _codigo_inline(texto) if tipo == "code" else _rich_text(texto)
    corpo: dict[str, Any] = {"rich_text": rich}
    if extra:
        corpo.update(extra)
    return {"object": "block", "type": tipo, tipo: corpo}


def _blocos_de_codigo(texto: str, linguagem: str) -> list[dict[str, Any]]:
    """Um ou mais blocos ``code`` para ``texto``.

    Cada item de *rich text* leva até 2000 caracteres e cada bloco até 100
    itens; código acima de ~200 mil caracteres não cabe num bloco só e é
    dividido em blocos de código consecutivos, da mesma linguagem, em vez de
    ser recusado pela API.
    """

    itens = _codigo_inline(texto)
    if len(itens) <= MAX_ITENS_ARRAY:
        return [_bloco("code", texto, {"language": linguagem})]
    return [
        {
            "object": "block",
            "type": "code",
            "code": {"rich_text": itens[inicio : inicio + MAX_ITENS_ARRAY], "language": linguagem},
        }
        for inicio in range(0, len(itens), MAX_ITENS_ARRAY)
    ]


def _texto_de_bloco(bloco: dict[str, Any], *, formatado: bool = True) -> str:
    """Extrai o texto de um bloco, reconstruindo a formatação inline em Markdown.

    Com ``formatado=False`` devolve só o texto puro (útil para código, onde a
    marcação não deve ser reaplicada).
    """

    tipo = bloco.get("type", "")
    corpo = bloco.get(tipo, {})
    itens = corpo.get("rich_text", []) if isinstance(corpo, dict) else []
    render = _item_para_markdown if formatado else _texto_de_item
    return "".join(render(item) for item in itens).strip()


def _texto_de_item(item: dict[str, Any]) -> str:
    """Extrai o texto cru de um item de *rich text*, ignorando ícones decorativos.

    *Custom emojis* (ícones de imagem usados em títulos) vêm como menção com
    ``plain_text`` no formato ``:nome:`` — ruído visual, não conteúdo. São
    descartados para o Markdown ficar legível.
    """

    mention = item.get("mention")
    if isinstance(mention, dict) and mention.get("type") == "custom_emoji":
        return ""
    return item.get("plain_text", item.get("text", {}).get("content", ""))


def _item_para_markdown(item: dict[str, Any]) -> str:
    """Reconstrói a marcação Markdown de um item de *rich text*.

    Reaplica ``**``/``*``/``~~``/``` ` ``` a partir de ``annotations`` e
    ``[texto](url)`` a partir do ``link``, fazendo o par com ``_parse_inline``.
    """

    texto = _texto_de_item(item)
    if not texto:
        return ""
    anot = item.get("annotations", {}) or {}
    if anot.get("code"):
        texto = f"`{texto}`"
    else:
        if anot.get("bold"):
            texto = f"**{texto}**"
        if anot.get("italic"):
            texto = f"*{texto}*"
        if anot.get("strikethrough"):
            texto = f"~~{texto}~~"
    link = item.get("text", {}).get("link") or item.get("href")
    if isinstance(link, dict):
        link = link.get("url")
    if link:
        texto = f"[{texto}]({link})"
    return texto


_RE_IMG_HTML = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*['\"]([^'\"]+)['\"][^>]*>", re.I)
_RE_A_HTML = re.compile(r"<a\b[^>]*?\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.I | re.S)
_RE_H_HTML = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_IMG_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# Imagem opcionalmente embrulhada por um link: [![alt](img)](href).
_RE_BADGE = re.compile(r"\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)")
# Badge (grupos 1-3) OU imagem solta (grupos 4-5), para varrer uma linha.
_RE_IMG_OU_BADGE = re.compile(
    r"\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)|!\[([^\]]*)\]\(([^)]+)\)"
)


def _limpar_html(linha: str) -> str:
    """Converte HTML de layout em Markdown equivalente e remove o restante.

    Mantém o **conteúdo**; descarta só o invólucro. ``<img>`` vira ``![](src)``,
    ``<a href>`` vira ``[texto](href)``, ``<hN>`` vira ``#``..``######``, ``<br>``
    vira quebra; demais tags são removidas e as entidades HTML são decodificadas.
    """

    linha = _RE_H_HTML.sub(lambda m: f"{'#' * int(m.group(1))} {m.group(2).strip()}", linha)
    linha = _RE_A_HTML.sub(lambda m: f"[{m.group(2).strip()}]({m.group(1).strip()})", linha)
    linha = _RE_IMG_HTML.sub(lambda m: f"![]({m.group(1).strip()})", linha)
    linha = re.sub(r"<br\s*/?>", " ", linha, flags=re.I)
    linha = _RE_TAG.sub("", linha)
    return _html.unescape(linha).strip()


def _bloco_imagem(url: str) -> dict[str, Any]:
    """Monta um bloco ``image`` externo, sem legenda.

    O *alt* do Markdown não vira legenda: em badges (shields.io) o alt é
    redundante e, quando a imagem não carrega no Notion, sobra só a legenda
    colorida poluindo a página. Imagens limpas, sem caption.
    """

    return {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url}},
    }


def _extrair_imagens_bloco(linha: str) -> list[dict[str, Any]] | None:
    """Se a linha é só imagens/badges (sem outro texto), devolve blocos ``image``.

    Cobre badges embrulhadas por link (``[![alt](img)](href)``) e imagens soltas
    (``![alt](url)``). Devolve ``None`` quando há texto além das imagens — aí a
    linha segue o fluxo normal (as imagens viram link inline).
    """

    resto = _RE_BADGE.sub(" ", linha)
    resto = _RE_IMG_MD.sub(" ", resto).strip()
    if resto:
        return None  # há texto real além das imagens: não vira bloco de imagem

    blocos: list[dict[str, Any]] = []
    for m in _RE_IMG_OU_BADGE.finditer(linha):
        url = (m.group(2) or m.group(5) or "").strip()
        if _url_valida(url):  # Notion só aceita imagem externa com URL absoluta
            blocos.append(_bloco_imagem(url))
    return blocos or None


def _eh_separador_tabela(linha: str) -> bool:
    """Indica se a linha é o separador de cabeçalho de uma tabela (``---|:--:``)."""

    despojada = linha.strip().strip("|")
    if "-" not in despojada or "|" not in despojada:
        return False
    celulas = [c.strip() for c in despojada.split("|")]
    return all(c and set(c) <= {"-", ":", " "} for c in celulas)


def _celulas_tabela(linha: str) -> list[str]:
    """Divide uma linha de tabela em células, ignorando as bordas ``|``."""

    return [c.strip() for c in linha.strip().strip("|").split("|")]


def _linha_tabela(celulas: list[str], largura: int) -> dict[str, Any]:
    """Monta um bloco ``table_row`` com ``largura`` células de *rich text*."""

    ajustadas = (celulas + [""] * largura)[:largura]
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": [_rich_text(c) for c in ajustadas]},
    }


def _parse_tabela(linhas: list[str], inicio: int) -> tuple[dict[str, Any] | None, int]:
    """Lê uma tabela Markdown a partir de ``inicio``.

    Devolve ``(bloco_table, linhas_consumidas)``. O cabeçalho é a primeira linha,
    a segunda é o separador e as seguintes são as linhas de dados, até a primeira
    linha que não contém ``|``.
    """

    cabecalho = _celulas_tabela(linhas[inicio])
    largura = len(cabecalho)
    if largura == 0:
        return None, 1

    filhos = [_linha_tabela(cabecalho, largura)]
    i = inicio + 2  # pula cabeçalho + separador
    n = len(linhas)
    while i < n and "|" in linhas[i] and linhas[i].strip():
        filhos.append(_linha_tabela(_celulas_tabela(linhas[i]), largura))
        i += 1

    tabela = {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": largura,
            "has_column_header": True,
            "has_row_header": False,
            "children": filhos,
        },
    }
    return tabela, i - inicio


def markdown_para_blocos(markdown: str) -> list[dict[str, Any]]:
    """Converte um texto Markdown em blocos do Notion.

    Além dos blocos textuais (títulos, parágrafos, listas, tarefas, citação,
    código e divisória), reconhece formatação inline (negrito, itálico, código,
    ``[link](url)``), **imagens/badges** (viram blocos ``image``), **tabelas**
    Markdown (viram blocos ``table``) e limpa HTML de layout comum em READMEs
    (``<div>``, ``<center>``, ``<br>``, ``<a>``, ``<img>``, ``<h1-6>``),
    preservando o conteúdo. Nada de Markdown vira texto literal sem necessidade.

    Args:
        markdown: Texto em Markdown.

    Returns:
        A lista de blocos no formato aceito por ``anexar_blocos``.
    """

    blocos: list[dict[str, Any]] = []
    linhas = markdown.splitlines()
    i = 0
    n = len(linhas)
    while i < n:
        bruta = linhas[i]
        despojada = bruta.strip()

        if despojada.startswith("```"):
            lingua = despojada[3:].strip()
            corpo: list[str] = []
            i += 1
            while i < n and not linhas[i].strip().startswith("```"):
                corpo.append(linhas[i])
                i += 1
            i += 1  # pula o fechamento ```
            blocos.extend(_blocos_de_codigo("\n".join(corpo), _normalizar_linguagem(lingua)))
            continue

        # Tabela: linha com | seguida de uma linha separadora (---|---).
        if "|" in despojada and i + 1 < n and _eh_separador_tabela(linhas[i + 1]):
            tabela, consumidas = _parse_tabela(linhas, i)
            if tabela is not None:
                blocos.append(tabela)
                i += consumidas
                continue

        linha = _limpar_html(despojada)
        if not linha.strip():
            i += 1
            continue

        # Citação vazia (linha só com '>'): separa parágrafos de um blockquote
        # no Markdown, mas não tem conteúdo — não vira bloco.
        if not linha.lstrip(">").strip():
            i += 1
            continue

        # Setext: a próxima linha é só ==== (h1) ou ---- (h2).
        if i + 1 < n and _nivel_setext(linhas[i + 1]) and not _classifica_prefixo(linha):
            nivel = _nivel_setext(linhas[i + 1])
            blocos.append(_bloco(f"heading_{nivel}", linha))
            i += 2
            continue

        blocos.extend(_linha_para_blocos(linha))
        i += 1

    return blocos


def _linha_para_blocos(linha: str) -> list[dict[str, Any]]:
    """Mapeia uma linha (já sem HTML) para um ou mais blocos do Notion.

    Devolve uma lista porque uma linha só de imagens/badges vira **um bloco de
    imagem por imagem**; os demais casos devolvem um bloco só.
    """

    imagens = _extrair_imagens_bloco(linha)
    if imagens is not None:
        return imagens
    return [_linha_para_bloco(linha)]


def _linha_para_bloco(linha: str) -> dict[str, Any]:
    """Mapeia uma linha de Markdown já despojada para um único bloco do Notion."""

    if set(linha) <= {"-", "*", "_"} and len(linha) >= 3:
        return {"object": "block", "type": "divider", "divider": {}}
    nivel = _nivel_atx(linha)
    if nivel:
        # O Notion só tem 3 níveis de heading; 4-6 caem em heading_3.
        return _bloco(f"heading_{min(nivel, 3)}", linha[nivel + 1 :])
    if linha.startswith("> "):
        return _bloco("quote", linha[2:])
    if linha[:6].lower() in ("- [ ] ", "- [x] "):
        marcado = linha[3].lower() == "x"
        return _bloco("to_do", linha[6:], {"checked": marcado})
    if linha.startswith(("- ", "* ", "+ ")):
        return _bloco("bulleted_list_item", linha[2:])
    numerada = _prefixo_numerado(linha)
    if numerada is not None:
        return _bloco("numbered_list_item", numerada)
    return _bloco("paragraph", linha)


def _nivel_atx(linha: str) -> int:
    """Nível de um heading ATX (``#``..``######`` seguido de espaço), ou 0."""

    i = 0
    while i < len(linha) and linha[i] == "#":
        i += 1
    if 1 <= i <= 6 and linha[i : i + 1] == " ":
        return i
    return 0


def _classifica_prefixo(linha: str) -> bool:
    """Indica se a linha já é um bloco estruturado (heading, lista, citação…)."""

    return bool(
        _nivel_atx(linha)
        or linha.startswith(("> ", "- ", "* ", "+ "))
        or _prefixo_numerado(linha) is not None
    )


def _nivel_setext(linha: str) -> int:
    """Nível de heading setext (``===`` → 1, ``---`` → 2), ou 0."""

    despojada = linha.strip()
    if len(despojada) >= 2 and set(despojada) == {"="}:
        return 1
    if len(despojada) >= 2 and set(despojada) == {"-"}:
        return 2
    return 0


def _prefixo_numerado(linha: str) -> str | None:
    """Devolve o texto após ``N. `` numa lista numerada, ou ``None``."""

    ponto = linha.find(". ")
    if ponto > 0 and linha[:ponto].isdigit():
        return linha[ponto + 2 :]
    return None


def blocos_para_markdown(blocos: list[dict[str, Any]]) -> str:
    """Converte blocos do Notion de volta em Markdown legível.

    Tipos conhecidos viram a marcação correspondente; tipos desconhecidos que
    tenham *rich text* viram parágrafo, para nunca descartar conteúdo. Blocos
    aninhados (a chave ``_filhos``, presente quando ``ler_blocos`` é recursivo)
    são incluídos logo após o bloco-pai — assim o conteúdo dentro de colunas e
    toggles não some.

    Args:
        blocos: Lista de blocos como retornados por ``ler_blocos``.

    Returns:
        O texto em Markdown, com blocos separados por linha em branco.
    """

    linhas: list[str] = []
    for bloco in blocos:
        linha = _bloco_para_linha(bloco)
        if linha is not None:
            linhas.append(linha)
        # As linhas de uma tabela já são consumidas por _tabela_para_markdown;
        # reprocessá-las como filhos genéricos duplicaria o conteúdo.
        if bloco.get("type") == "table":
            continue
        filhos = bloco.get("_filhos")
        if filhos:
            aninhado = blocos_para_markdown(filhos)
            if aninhado:
                linhas.append(aninhado)
    return "\n\n".join(linhas)


def _titulo_child_database(bloco: dict[str, Any]) -> str:
    """Título de um bloco ``child_database`` (cai para ``"(sem título)"``)."""

    titulo = bloco.get("child_database", {}).get("title", "")
    return titulo or "(sem título)"


def _bloco_para_linha(bloco: dict[str, Any]) -> str | None:
    """Converte um único bloco em sua linha Markdown (``None`` se vazio)."""

    tipo = bloco.get("type", "")
    if tipo == "code":
        texto = _texto_de_bloco(bloco, formatado=False)
        lingua = bloco.get("code", {}).get("language", "")
        return f"```{lingua}\n{texto}\n```"
    if tipo == "image":
        return _imagem_para_markdown(bloco)
    if tipo == "table":
        return _tabela_para_markdown(bloco)
    texto = _texto_de_bloco(bloco)
    if tipo == "divider":
        return "---"
    if tipo == "heading_1":
        return f"# {texto}"
    if tipo == "heading_2":
        return f"## {texto}"
    if tipo == "heading_3":
        return f"### {texto}"
    if tipo == "quote":
        return f"> {texto}"
    if tipo == "bulleted_list_item":
        return f"- {texto}"
    if tipo == "numbered_list_item":
        return f"1. {texto}"
    if tipo == "to_do":
        marca = "x" if bloco.get("to_do", {}).get("checked") else " "
        return f"- [{marca}] {texto}"
    if tipo == "child_database":
        return f"**[database: {_titulo_child_database(bloco)}]**"
    if tipo == "child_page":
        return f"**[página: {bloco.get('child_page', {}).get('title', '') or '(sem título)'}]**"
    if tipo in _TIPOS_TEXTO:
        return texto or None
    return texto or None


def _imagem_para_markdown(bloco: dict[str, Any]) -> str:
    """Reconstrói ``![alt](url)`` a partir de um bloco ``image``."""

    imagem = bloco.get("image", {})
    tipo = imagem.get("type", "external")
    url = imagem.get(tipo, {}).get("url", "")
    alt = "".join(_texto_de_item(i) for i in imagem.get("caption", []))
    return f"![{alt}]({url})"


def _tabela_para_markdown(bloco: dict[str, Any]) -> str:
    """Reconstrói uma tabela Markdown a partir de um bloco ``table``."""

    tabela = bloco.get("table", {})
    largura = tabela.get("table_width", 0)
    filhos = tabela.get("children") or bloco.get("_filhos") or []
    linhas_md: list[str] = []
    for indice, filho in enumerate(filhos):
        celulas = filho.get("table_row", {}).get("cells", [])
        textos = ["".join(_item_para_markdown(i) for i in cel) for cel in celulas]
        textos = (textos + [""] * largura)[:largura]
        linhas_md.append("| " + " | ".join(textos) + " |")
        if indice == 0:
            linhas_md.append("| " + " | ".join(["---"] * largura) + " |")
    return "\n".join(linhas_md)


# -- Limites da API: validação e divisão em lotes -------------------------------------


def _unidades_utf16(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


def _filhos_de(bloco: dict[str, Any]) -> list[dict[str, Any]]:
    """Filhos declarados no corpo do tipo (``bloco[tipo]["children"]``)."""

    corpo = bloco.get(str(bloco.get("type") or ""))
    filhos = corpo.get("children") if isinstance(corpo, dict) else None
    return filhos if isinstance(filhos, list) else []


def contar_elementos(bloco: dict[str, Any]) -> int:
    """Quantos elementos de bloco ``bloco`` soma numa requisição (ele + descendentes)."""

    return 1 + sum(contar_elementos(filho) for filho in _filhos_de(bloco))


def _tamanho_json(dados: Any) -> int:
    # ``requests`` serializa com ensure_ascii: estimar do mesmo jeito é o lado seguro.
    return len(json.dumps(dados, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def _validar_rich_text(itens: Any, onde: str, problemas: list[str]) -> None:
    if not isinstance(itens, list):
        return
    if len(itens) > MAX_ITENS_ARRAY:
        problemas.append(
            f"{onde}: {len(itens)} trechos de texto formatado (máximo {MAX_ITENS_ARRAY}); "
            "simplifique a formatação inline ou divida o texto"
        )
    for item in itens:
        texto = item.get("text") if isinstance(item, dict) else None
        if not isinstance(texto, dict):
            continue
        if _unidades_utf16(str(texto.get("content", ""))) > MAX_RICH_TEXT:
            problemas.append(f"{onde}: trecho com mais de {MAX_RICH_TEXT} caracteres")
        link = texto.get("link")
        url = link.get("url") if isinstance(link, dict) else None
        if isinstance(url, str) and len(url) > MAX_URL_LINK:
            problemas.append(f"{onde}: link com mais de {MAX_URL_LINK} caracteres")


def _validar_bloco(bloco: dict[str, Any], onde: str, nivel: int, problemas: list[str]) -> None:
    tipo = str(bloco.get("type") or "")
    corpo = bloco.get(tipo)
    rotulo = f"{onde} ({tipo})"
    if isinstance(corpo, dict):
        _validar_rich_text(corpo.get("rich_text"), rotulo, problemas)
        _validar_rich_text(corpo.get("caption"), f"{rotulo}, legenda", problemas)
        celulas = corpo.get("cells")
        if isinstance(celulas, list):
            if len(celulas) > MAX_ITENS_ARRAY:
                problemas.append(
                    f"{rotulo}: {len(celulas)} colunas (máximo {MAX_ITENS_ARRAY})"
                )
            for coluna, celula in enumerate(celulas, start=1):
                _validar_rich_text(celula, f"{rotulo}, coluna {coluna}", problemas)
    filhos = _filhos_de(bloco)
    if not filhos:
        return
    if nivel + 1 > MAX_NIVEIS_ANINHADOS:
        problemas.append(
            f"{rotulo}: aninhamento acima de {MAX_NIVEIS_ANINHADOS} níveis numa requisição"
        )
    if len(filhos) > MAX_ITENS_ARRAY:
        rotulo_filhos = "linhas" if tipo == "table" else "filhos"
        problemas.append(
            f"{rotulo}: {len(filhos)} {rotulo_filhos} (máximo {MAX_ITENS_ARRAY}); "
            "divida em partes menores"
        )
    for indice, filho in enumerate(filhos, start=1):
        _validar_bloco(filho, f"{onde}.{indice}", nivel + 1, problemas)


def validar_blocos(blocos: list[dict[str, Any]]) -> None:
    """Confere, **sem rede**, se os blocos cabem nos limites documentados da API.

    Percorre a árvore inteira: cada array de *rich text* (inclusive legendas e
    células de tabela) com até 100 itens, cada trecho com até 2000 caracteres,
    links com até 2000, ``children`` com até 100 elementos e até 2 níveis de
    aninhamento, e cada bloco de topo cabendo sozinho numa requisição (1000
    elementos, 500 KB). O número de blocos de topo não é limite aqui: quem
    envia divide em lotes com :func:`planejar_lotes`.

    Args:
        blocos: Blocos no formato da API (ex.: saída de :func:`markdown_para_blocos`).

    Raises:
        ConteudoInvalidoError: Com a lista de cada violação encontrada.
    """

    problemas: list[str] = []
    for indice, bloco in enumerate(blocos, start=1):
        onde = f"bloco {indice}"
        _validar_bloco(bloco, onde, 0, problemas)
        if contar_elementos(bloco) > MAX_ELEMENTOS_POR_REQUISICAO:
            problemas.append(
                f"{onde}: {contar_elementos(bloco)} elementos (máximo "
                f"{MAX_ELEMENTOS_POR_REQUISICAO} por requisição)"
            )
        if _tamanho_json(bloco) > MAX_BYTES_POR_REQUISICAO:
            problemas.append(f"{onde}: mais de 500 KB sozinho")
    if problemas:
        raise ConteudoInvalidoError(problemas)


def planejar_lotes(blocos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Divide blocos de topo em lotes que cabem, cada um, numa requisição.

    Cada lote fecha antes de passar de 100 blocos de topo, de 1000 elementos
    de bloco (contando os descendentes em ``children``, como as linhas de uma
    tabela) ou de ~500 KB de JSON — os três limites documentados. Dez
    tabelas de 100 linhas, por exemplo, já não cabem num lote só.

    Args:
        blocos: Blocos já validados por :func:`validar_blocos`.

    Returns:
        Os lotes, na ordem original.
    """

    # Folga para o invólucro ``{"children": [...]}`` e o ``position``.
    teto_bytes = MAX_BYTES_POR_REQUISICAO - 4_096
    lotes: list[list[dict[str, Any]]] = []
    atual: list[dict[str, Any]] = []
    elementos = 0
    tamanho = 0
    for bloco in blocos:
        peso = contar_elementos(bloco)
        bytes_bloco = _tamanho_json(bloco) + 1
        cabe = (
            len(atual) < MAX_ITENS_ARRAY
            and elementos + peso <= MAX_ELEMENTOS_POR_REQUISICAO
            and tamanho + bytes_bloco <= teto_bytes
        )
        if atual and not cabe:
            lotes.append(atual)
            atual, elementos, tamanho = [], 0, 0
        atual.append(bloco)
        elementos += peso
        tamanho += bytes_bloco
    if atual:
        lotes.append(atual)
    return lotes


# -- Edição de rich text sem passar por Markdown ---------------------------------------


def _texto_visivel(item: dict[str, Any]) -> str:
    """O texto que o item mostra na página (inclusive de menção e equação)."""

    if item.get("plain_text") is not None:
        return str(item.get("plain_text") or "")
    if item.get("type") == "equation":
        return str((item.get("equation") or {}).get("expression", ""))
    texto = item.get("text")
    return str(texto.get("content", "")) if isinstance(texto, dict) else ""


def texto_de_rich_text(itens: list[dict[str, Any]]) -> str:
    """O texto puro de um *rich text*, como aparece na página."""

    return "".join(_texto_visivel(item) for item in itens if isinstance(item, dict))


def rich_text_de_codigo(texto: str) -> list[dict[str, Any]]:
    """*Rich text* de um bloco de código: texto cru, fatiado em 2000 caracteres."""

    return _codigo_inline(texto)


def perdas_de_formatacao(itens: list[dict[str, Any]]) -> list[str]:
    """O que reescrever este *rich text* a partir de Markdown perderia.

    O par Markdown desta lib representa negrito, itálico, tachado, código e
    link. Menção (página, data, usuário, emoji…) vira texto ou link comum;
    equação vira texto; sublinhado e cor (de texto ou de fundo) somem; ênfase
    dentro de código também. Cada perda vem descrita com o trecho afetado.
    """

    perdas: list[str] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        trecho = _texto_visivel(item)
        tipo = item.get("type")
        if tipo == "mention":
            mencao = item.get("mention") or {}
            perdas.append(f"menção de {mencao.get('type', '?')} '{trecho}'")
        elif tipo == "equation":
            perdas.append(f"equação '{trecho}'")
        anot = item.get("annotations") or {}
        if anot.get("underline"):
            perdas.append(f"sublinhado em '{trecho}'")
        cor = anot.get("color")
        if cor and cor != "default":
            perdas.append(f"cor '{cor}' em '{trecho}'")
        if anot.get("code") and any(anot.get(k) for k in ("bold", "italic", "strikethrough")):
            perdas.append(f"ênfase dentro de código em '{trecho}'")
    return perdas


def trocar_trecho_rich_text(
    itens: list[dict[str, Any]],
    antigo: str,
    novo: str,
    *,
    todas: bool = False,
    block_id: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Troca ``antigo`` por ``novo`` **dentro** dos itens de texto, sem tocar no resto.

    É a edição que preserva o que o Markdown não representa: as anotações
    (cor, sublinhado…) e o link de cada item ficam como estavam, e menções e
    equações são reenviadas intactas (no formato de requisição, ver
    :func:`item_para_requisicao`). Itens que passem de 2000 caracteres depois
    da troca são fatiados com a mesma formatação.

    Args:
        itens: O *rich text* lido do bloco.
        antigo: Trecho a procurar (não vazio).
        novo: Texto que entra no lugar.
        todas: Troca todas as ocorrências; sem isso, exige exatamente uma.
        block_id: Só para as mensagens de erro.

    Returns:
        ``(rich_text_novo, ocorrências_trocadas)``.

    Raises:
        ValueError: ``antigo`` vazio.
        TrechoNaoEncontradoError: O trecho não aparece.
        TrechoAtravessaItensError: Aparece cruzando itens ou dentro de
            menção/equação.
        TrechoAmbiguoError: Aparece mais de uma vez sem ``todas``.
        RichTextNaoRegravavelError: O bloco tem item que não se regrava.
        ConteudoInvalidoError: O resultado passaria de 100 itens.
    """

    if not antigo:
        raise ValueError("Informe o trecho a trocar.")
    completo = texto_de_rich_text(itens)
    total = completo.count(antigo)
    if total == 0:
        raise TrechoNaoEncontradoError(block_id, antigo, completo)
    por_item = [
        str(item["text"].get("content", "")).count(antigo)
        if item.get("type", "text") == "text" and isinstance(item.get("text"), dict)
        else 0
        for item in itens
    ]
    dentro = sum(por_item)
    if dentro < total:
        raise TrechoAtravessaItensError(block_id, antigo)
    if dentro > 1 and not todas:
        raise TrechoAmbiguoError(block_id, antigo, dentro)

    resultado: list[dict[str, Any]] = []
    for item, ocorrencias in zip(itens, por_item, strict=True):
        convertido = item_para_requisicao(item)
        if not ocorrencias:
            resultado.append(convertido)
            continue
        convertido["text"]["content"] = convertido["text"]["content"].replace(antigo, novo)
        if convertido["text"]["content"]:
            resultado.extend(_fatiar_item(convertido))
    if len(resultado) > MAX_ITENS_ARRAY:
        raise ConteudoInvalidoError(
            [f"o texto ficaria com {len(resultado)} trechos (máximo {MAX_ITENS_ARRAY})"]
        )
    return resultado, dentro
