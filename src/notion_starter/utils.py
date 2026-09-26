"""Utilitários compartilhados para o notion_starter."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .exceptions import IdNotionInvalidoError


def fatiar_utf16(texto: str, limite: int) -> list[str]:
    """Fatia ``texto`` em pedaços de no máximo ``limite`` unidades UTF-16.

    O Notion conta o comprimento de rich_text em unidades UTF-16: um caractere
    fora do BMP (ex.: emoji) ocupa 2 unidades. Por isso o corte é feito por
    contagem UTF-16, não por ``len()`` (code points), senão texto com emoji
    estouraria o limite da API. Texto vazio devolve lista vazia.
    """

    pedacos: list[str] = []
    atual: list[str] = []
    custo = 0
    for ch in texto:
        # Caracteres acima de U+FFFF usam um par substituto (2 unidades UTF-16).
        peso = 2 if ord(ch) > 0xFFFF else 1
        if custo + peso > limite and atual:
            pedacos.append("".join(atual))
            atual, custo = [], 0
        atual.append(ch)
        custo += peso
    if atual:
        pedacos.append("".join(atual))
    return pedacos


def has_invalid_surrogates(text: str) -> bool:
    """Verifica se uma string contém surrogates Unicode inválidos.

    Surrogates inválidos causam erro quando codificados para UTF-8:
    "utf-8 codec can't encode character '\\ud800' in position X: surrogates not allowed"

    Args:
        text: String para verificar

    Returns:
        True se a string contém surrogates inválidos que quebram encoding UTF-8
    """
    # Verificar se há qualquer caractere no intervalo de surrogates Unicode
    # U+D800-U+DFFF são reserved for UTF-16 surrogates e são inválidos em UTF-8
    for char in text:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            return True

    # Verificação adicional: tentar codificar para UTF-8
    try:
        text.encode('utf-8')
        return False
    except UnicodeEncodeError as e:
        return 'surrogate' in str(e).lower()


def safe_json_dumps(data: Any, **kwargs) -> str:
    """Versão segura de json.dumps que previne erros de surrogate.

    Quando ensure_ascii=False é usado com texto contendo surrogates inválidos,
    a codificação para UTF-8 pode falhar. Esta função detecta e corrige isso.

    Args:
        data: Dados para serializar como JSON
        **kwargs: Argumentos para json.dumps

    Returns:
        String JSON serializada com segurança
    """
    ensure_ascii = kwargs.pop('ensure_ascii', False)

    if not ensure_ascii:
        # Verificar se há surrogates inválidos nos dados de string
        def _check_surrogates(obj):
            if isinstance(obj, str) and has_invalid_surrogates(obj):
                return True
            elif isinstance(obj, dict):
                return any(_check_surrogates(v) for v in obj.values())
            elif isinstance(obj, list):
                return any(_check_surrogates(item) for item in obj)
            return False

        if _check_surrogates(data):
            # Forçar ensure_ascii=True para dados problemáticos
            ensure_ascii = True

    return json.dumps(data, ensure_ascii=ensure_ascii, **kwargs)


def sanitize_text(text: str) -> str:
    """Sanitiza texto removendo ou substituindo surrogates inválidos.

    Args:
        text: Texto para sanitizar

    Returns:
        Texto seguro para serialização JSON e encoding UTF-8
    """
    try:
        # Tentar codificar - se funcionar, está ok
        text.encode('utf-8')
        return text
    except UnicodeEncodeError as e:
        if 'surrogate' in str(e).lower():
            # Substituir surrogates inválidos por caractere de substituição
            return text.encode('utf-8', errors='replace').decode('utf-8')
        # Outros erros de encoding - re-raise
        raise

# -- IDs do Notion -------------------------------------------------------------

_RE_UUID_INTEIRO = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE
)
# ID ao fim de um trecho de URL: 32 hexadecimais colados (forma do link) ou o
# UUID com hífens. O slug do título vem antes, separado por hífen.
_RE_ID_NO_FIM = re.compile(
    r"([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def chave_de_id(identificador: str) -> str:
    """Forma comparável de um ID do Notion: sem hífens e em minúsculas.

    A API aceita o UUID com ou sem hífens; comparar a forma crua diria que
    ``3e691f95-497e-…`` e ``3e691f95497e…`` são páginas diferentes. Não valida
    nada — serve só para comparar.
    """

    return str(identificador).strip().replace("-", "").lower()


def _canonico(hexa: str) -> str:
    limpo = hexa.replace("-", "").lower()
    return f"{limpo[:8]}-{limpo[8:12]}-{limpo[12:16]}-{limpo[16:20]}-{limpo[20:]}"


def _id_no_fim(trecho: str) -> str | None:
    achado = _RE_ID_NO_FIM.search(trecho.strip())
    return _canonico(achado.group(1)) if achado else None


def normalizar_id(valor: str, *, preferir_ancora: bool = False) -> str:
    """Devolve o ID canônico (``8-4-4-4-12``, minúsculo) de um UUID ou link do Notion.

    Aceita o UUID com ou sem hífens (a forma sem hífens é a que aparece no
    campo ``url`` das respostas) e links de ``notion.so``, ``app.notion.com`` e
    ``*.notion.site``. Num link:

    - o ID da página sai do **último trecho do caminho** (``Titulo-<32hex>``);
    - ``?p=<32hex>`` (página aberta em painel) vence o caminho;
    - ``?v=<32hex>`` é o ID de uma **view** de database e é sempre ignorado;
    - ``#<32hex>`` aponta um bloco dentro da página e só vence quando
      ``preferir_ancora`` é verdadeiro (argumentos que esperam um bloco).

    Args:
        valor: UUID ou URL recebido de quem opera.
        preferir_ancora: Usa a âncora ``#<id>`` quando houver.

    Returns:
        O UUID canônico com hífens.

    Raises:
        IdNotionInvalidoError: Se ``valor`` não contém um ID do Notion.
    """

    bruto = str(valor or "").strip()
    if _RE_UUID_INTEIRO.match(bruto):
        return _canonico(bruto)

    partes = urlsplit(bruto)
    if partes.scheme and partes.netloc:
        if preferir_ancora and partes.fragment:
            ancora = _id_no_fim(partes.fragment)
            if ancora:
                return ancora
        painel = parse_qs(partes.query).get("p", [])
        if painel and _RE_UUID_INTEIRO.match(painel[0]):
            return _canonico(painel[0])
        ultimo = partes.path.rstrip("/").rsplit("/", 1)[-1]
        do_caminho = _id_no_fim(ultimo)
        if do_caminho:
            return do_caminho

    raise IdNotionInvalidoError(valor)


def extrair_id(valor: str, *, preferir_ancora: bool = False) -> str:
    """Como :func:`normalizar_id`, mas devolve ``valor`` sem espaços quando não há ID.

    Para a camada de serviço, que também é chamada com identificadores que não
    são UUID (testes, *fakes*): quem não reconhece um ID deixa a validação para
    a API, em vez de recusar antes.
    """

    try:
        return normalizar_id(valor, preferir_ancora=preferir_ancora)
    except IdNotionInvalidoError:
        return str(valor or "").strip()
