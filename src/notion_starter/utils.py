"""Utilitários compartilhados para o notion_starter."""

from __future__ import annotations

import json
from typing import Any


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