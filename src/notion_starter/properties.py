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


def arquivo_enviado(upload_id: str, nome: str) -> NotionPropertyValue:
    """Monta um valor de propriedade ``files`` a partir de um upload direto.

    Recebe o ``file_upload`` id devolvido por
    :meth:`notion_starter.NotionClient.enviar_arquivo` e o embrulha no formato
    que a API espera para anexar o arquivo à propriedade de uma linha.

    Args:
        upload_id: ``id`` do ``file_upload`` já enviado.
        nome: Nome exibido do arquivo.
    """

    return {
        "files": [
            {"type": "file_upload", "file_upload": {"id": upload_id}, "name": nome[:100]}
        ]
    }


def relation(ids: list[str]) -> NotionPropertyValue:
    """Monta um valor de propriedade ``relation`` (lista de IDs de páginas)."""

    return {"relation": [{"id": id_} for id_ in ids]}


#: Tipos aceitos por :func:`schema_propriedade` e o fragmento de schema de cada um.
TIPOS_SCHEMA: dict[str, dict[str, Any]] = {
    "titulo": {"title": {}},
    "texto": {"rich_text": {}},
    "numero": {"number": {}},
    "data": {"date": {}},
    "select": {"select": {}},
    "multi_select": {"multi_select": {}},
    "checkbox": {"checkbox": {}},
    "email": {"email": {}},
    "url": {"url": {}},
    "telefone": {"phone_number": {}},
    "pessoas": {"people": {}},
    "arquivos": {"files": {}},
}

#: Tipo de schema que exige um database alvo em :func:`schema_propriedade`.
TIPO_RELACAO = "relacao"


def schema_propriedade(tipo: str, *, relacionar_com: str | None = None) -> dict[str, Any]:
    """Monta o fragmento de **schema** de uma propriedade a partir de um tipo.

    Diferente das demais funções deste módulo (que montam *valores* de
    propriedade para uma linha), esta monta a *definição* da coluna usada em
    :meth:`notion_starter.NotionClient.criar_database` — a partir de nomes de
    tipo em português (``titulo``, ``texto``, ``numero``, ``data``…).

    O tipo ``relacao`` é o único que precisa de um alvo: ``relacionar_com``
    recebe o ID do database ao qual a coluna aponta. A relação é criada como
    ``dual_property`` (bidirecional), então o Notion também cria a coluna
    espelho no database alvo.

    Args:
        tipo: Um dos tipos em :data:`TIPOS_SCHEMA` ou :data:`TIPO_RELACAO`.
        relacionar_com: ID do database alvo. Obrigatório para ``relacao`` e
            recusado para os demais tipos.

    Raises:
        ValueError: Se o tipo não for reconhecido ou se ``relacionar_com`` for
            usado de forma incompatível com o tipo.
    """

    tipo_normalizado = tipo.strip().lower()
    alvo = (relacionar_com or "").strip()

    if tipo_normalizado == TIPO_RELACAO:
        if not alvo:
            raise ValueError(
                "O tipo 'relacao' exige 'relacionar_com' com o ID do database alvo."
            )
        return {"relation": {"database_id": alvo, "type": "dual_property", "dual_property": {}}}

    if alvo:
        raise ValueError(
            f"'relacionar_com' só se aplica ao tipo 'relacao', não a '{tipo_normalizado}'."
        )

    fragmento = TIPOS_SCHEMA.get(tipo_normalizado)
    if fragmento is None:
        raise ValueError(
            f"Tipo de propriedade '{tipo}' inválido. "
            f"Tipos aceitos: {', '.join(sorted([*TIPOS_SCHEMA, TIPO_RELACAO]))}."
        )
    return {chave: dict(valor) for chave, valor in fragmento.items()}


def _para_iso(valor: str | _dt.date | _dt.datetime) -> str:
    """Serializa um valor de data em uma string ISO 8601."""

    if isinstance(valor, (_dt.date, _dt.datetime)):
        return valor.isoformat()
    return valor


#: Tipos calculados ou gerenciados pelo Notion: não aceitam escrita pela API.
TIPOS_SOMENTE_LEITURA = frozenset(
    {
        "formula",
        "rollup",
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "unique_id",
        "button",
        "verification",
    }
)


def _numero_de_texto(texto: str) -> float | int:
    try:
        return int(texto)
    except ValueError:
        return float(texto)


def _lista_de_texto(texto: str) -> list[str]:
    return [parte.strip() for parte in texto.split(",") if parte.strip()]


def valor_de_texto(tipo: str, texto: str) -> NotionPropertyValue:
    """Converte um valor escrito como texto no payload de propriedade do ``tipo``.

    É a regra do ``editar-linha`` da CLI (``Nome=valor``), trazida para a
    biblioteca para os serviços que recebem valores em texto — manifestos,
    planilhas — escreverem colunas sem cada um reinventar o formato:

    - ``multi_select``, ``relation`` e ``people`` recebem itens separados por
      vírgula; ``date`` aceita intervalo ``inicio..fim``;
    - ``checkbox`` é verdadeiro para ``true``/``1``/``sim``/``yes``/``x``/``✓``;
    - texto vazio limpa a propriedade quando o tipo permite.

    Args:
        tipo: ``type`` da coluna, como o schema ou a página informam.
        texto: Valor em texto.

    Returns:
        O payload da propriedade (ex.: ``{"select": {"name": "Ideia"}}``).

    Raises:
        ValueError: Tipo calculado, tipo sem conversão, número inválido ou
            ``status`` vazio.
    """

    texto = texto.strip()
    vazio = texto == ""
    if tipo in TIPOS_SOMENTE_LEITURA:
        raise ValueError(f"Colunas do tipo '{tipo}' são calculadas pelo Notion e não se editam.")
    if tipo == "title":
        return {"title": []} if vazio else title(texto)
    if tipo == "rich_text":
        return {"rich_text": []} if vazio else rich_text(texto)
    if tipo == "number":
        if vazio:
            return {"number": None}
        try:
            return number(_numero_de_texto(texto))
        except ValueError as exc:
            raise ValueError(f"'{texto}' não é um número válido.") from exc
    if tipo == "checkbox":
        return checkbox(texto.casefold() in {"true", "1", "sim", "yes", "x", "✓"})
    if tipo == "select":
        return {"select": None} if vazio else select(texto)
    if tipo == "status":
        if vazio:
            raise ValueError("Uma propriedade 'status' não pode ficar vazia.")
        return status(texto)
    if tipo == "multi_select":
        return multi_select(_lista_de_texto(texto))
    if tipo == "relation":
        return relation(_lista_de_texto(texto))
    if tipo == "people":
        return {"people": [{"id": id_} for id_ in _lista_de_texto(texto)]}
    if tipo == "date":
        if vazio:
            return {"date": None}
        inicio, _, fim = texto.partition("..")
        return date(inicio.strip(), fim.strip() or None)
    if tipo == "email":
        return {"email": texto or None}
    if tipo == "phone_number":
        return {"phone_number": texto or None}
    if tipo == "url":
        return {"url": texto or None}
    raise ValueError(f"Tipo '{tipo}' ainda não tem conversão a partir de texto.")
