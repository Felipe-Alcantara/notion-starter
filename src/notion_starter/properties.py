"""Helpers para montar valores de propriedade do Notion.

Estas funções pequenas e puras convertem valores Python comuns nos payloads
verbosos de propriedade que a API do Notion espera, para que quem chama não
precise lembrar o formato exato de JSON de cada tipo.

Exemplo:
    >>> from notion_starter import properties as p
    >>> pagina = {
    ...     "Nome": p.title("Ada Lovelace"),
    ...     "Email": p.email("ada@example.com"),
    ...     "Perfil": p.select("Engenharia"),
    ...     "Cadastro": p.date("2026-06-24"),
    ... }
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .constants import MAX_RICH_TEXT
from .utils import fatiar_utf16

NotionPropertyValue = dict[str, Any]
NotionProperties = dict[str, NotionPropertyValue]


def _itens_texto(valor: str) -> list[dict[str, Any]]:
    """Fatia ``valor`` em itens de texto de até 2000 unidades UTF-16.

    Título e rich_text têm o mesmo teto por item; texto maior vira vários itens,
    que o Notion concatena no mesmo campo. Texto vazio produz um item vazio, para
    manter o comportamento simples de quem passa ``""``.
    """

    fatias = fatiar_utf16(valor, MAX_RICH_TEXT) or [""]
    return [{"text": {"content": pedaco}} for pedaco in fatias]


def title(valor: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``title`` (fatiando texto longo)."""

    return {"title": _itens_texto(valor)}


def rich_text(valor: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``rich_text`` (fatiando texto longo)."""

    return {"rich_text": _itens_texto(valor)}


def email(valor: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``email``."""

    return {"email": valor}


def phone_number(valor: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``phone_number``."""

    return {"phone_number": valor}


def url(valor: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``url``."""

    return {"url": valor}


def number(valor: float | int) -> NotionPropertyValue:
    """Monta um valor de propriedade ``number``."""

    return {"number": valor}


def checkbox(valor: bool) -> NotionPropertyValue:
    """Monta um valor de propriedade ``checkbox``."""

    return {"checkbox": valor}


def select(nome: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``select``."""

    return {"select": {"name": nome}}


def status(nome: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``status``."""

    return {"status": {"name": nome}}


def multi_select(nomes: list[str]) -> NotionPropertyValue:
    """Monta um valor de propriedade ``multi_select``."""

    return {"multi_select": [{"name": nome} for nome in nomes]}


def date(
    inicio: str | _dt.date | _dt.datetime,
    fim: str | _dt.date | _dt.datetime | None = None,
) -> NotionPropertyValue:
    """Monta um valor de propriedade ``date``.

    Args:
        inicio: Data inicial. ``date``/``datetime`` são serializados em
            ISO 8601.
        fim: Data final opcional, para intervalos.

    Returns:
        Um valor de propriedade ``date``.
    """

    payload: dict[str, Any] = {"start": _para_iso(inicio)}
    if fim is not None:
        payload["end"] = _para_iso(fim)
    return {"date": payload}


def relation(ids: list[str]) -> NotionPropertyValue:
    """Monta um valor de propriedade ``relation`` (lista de IDs de páginas)."""

    return {"relation": [{"id": id_} for id_ in ids]}


def _para_iso(valor: str | _dt.date | _dt.datetime) -> str:
    """Serializa um valor de data em uma string ISO 8601."""

    if isinstance(valor, (_dt.date, _dt.datetime)):
        return valor.isoformat()
    return valor
