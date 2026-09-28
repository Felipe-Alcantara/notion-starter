"""Helpers para ler valores de propriedade do Notion.

Par de **leitura** dos helpers de **escrita** em :mod:`properties`. Convertem o
JSON verboso de uma propriedade do Notion de volta em valores Python simples,
para que quem chama não precise decorar o formato de cada tipo nem proteger,
toda vez, contra campos vazios (``select`` sem opção, ``date`` em branco…).

São funções pequenas e puras — sem rede, sem estado. Cada uma aceita o valor de
propriedade como vem da API (o dicionário com a chave ``type``) e devolve um
valor simples, retornando vazio (``""``, ``None`` ou ``[]``) quando a
propriedade não está preenchida.

Exemplo:
    >>> from notion_starter import readers as r
    >>> r.ler_title({"type": "title", "title": [{"plain_text": "Ada"}]})
    'Ada'
    >>> r.ler_select({"type": "select", "select": None})  # vazio -> None
    >>> r.extrair_valores(pagina)  # {"Nome": "Ada", "Status": "Ativo", ...}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

NotionPropertyValue = dict[str, Any]


def _texto_rico(itens: list[dict[str, Any]]) -> str:
    """Concatena o texto de uma lista de *rich text* (``title``/``rich_text``).

    Usa ``plain_text`` quando presente (como vem da API) e cai para
    ``text.content`` (como aparece em payloads montados à mão).
    """

    return "".join(
        item.get("plain_text", item.get("text", {}).get("content", "")) for item in itens
    )


def ler_title(prop: NotionPropertyValue | None) -> str:
    """Lê uma propriedade ``title`` como texto simples (``""`` se vazia)."""

    return _texto_rico((prop or {}).get("title", []))


def ler_rich_text(prop: NotionPropertyValue | None) -> str:
    """Lê uma propriedade ``rich_text`` como texto simples (``""`` se vazia)."""

    return _texto_rico((prop or {}).get("rich_text", []))


def ler_select(prop: NotionPropertyValue | None) -> str | None:
    """Lê o nome da opção de um ``select`` (``None`` se não houver opção)."""

    valor = (prop or {}).get("select")
    return valor.get("name") if isinstance(valor, dict) else None


def ler_status(prop: NotionPropertyValue | None) -> str | None:
    """Lê o nome do ``status`` (``None`` se não definido)."""

    valor = (prop or {}).get("status")
    return valor.get("name") if isinstance(valor, dict) else None


def ler_multi_select(prop: NotionPropertyValue | None) -> list[str]:
    """Lê os nomes das opções de um ``multi_select`` (``[]`` se vazio)."""

    itens = (prop or {}).get("multi_select") or []
    return [item.get("name", "") for item in itens]


def ler_date(prop: NotionPropertyValue | None) -> str | None:
    """Lê a data de início (ISO) de uma propriedade ``date`` (``None`` se vazia).

    O fim do intervalo, quando existe, permanece disponível no JSON bruto da
    página; aqui devolvemos o ``start``, que é o caso de uso comum (prazo).
    """

    valor = (prop or {}).get("date")
    return valor.get("start") if isinstance(valor, dict) else None


def ler_email(prop: NotionPropertyValue | None) -> str | None:
    """Lê uma propriedade ``email`` (``None`` se vazia)."""

    return (prop or {}).get("email")


def ler_phone_number(prop: NotionPropertyValue | None) -> str | None:
    """Lê uma propriedade ``phone_number`` (``None`` se vazia)."""

    return (prop or {}).get("phone_number")


def ler_url(prop: NotionPropertyValue | None) -> str | None:
    """Lê uma propriedade ``url`` (``None`` se vazia)."""

    return (prop or {}).get("url")


def ler_number(prop: NotionPropertyValue | None) -> float | int | None:
    """Lê uma propriedade ``number`` (``None`` se vazia)."""

    return (prop or {}).get("number")


def ler_checkbox(prop: NotionPropertyValue | None) -> bool:
    """Lê uma propriedade ``checkbox`` como booleano (``False`` se ausente)."""

    return bool((prop or {}).get("checkbox", False))


def ler_relation(prop: NotionPropertyValue | None) -> list[str]:
    """Lê os IDs das páginas relacionadas de um ``relation`` (``[]`` se vazio)."""

    itens = (prop or {}).get("relation") or []
    return [item.get("id", "") for item in itens]


def ler_people(prop: NotionPropertyValue | None) -> list[str]:
    """Lê os IDs das pessoas de um ``people`` (``[]`` se vazio)."""

    itens = (prop or {}).get("people") or []
    return [item.get("id", "") for item in itens]


def ler_created_time(prop: NotionPropertyValue | None) -> str | None:
    """Lê a data de criação (ISO) de uma coluna ``created_time``."""

    return (prop or {}).get("created_time")


def ler_last_edited_time(prop: NotionPropertyValue | None) -> str | None:
    """Lê a data da última edição (ISO) de uma coluna ``last_edited_time``."""

    return (prop or {}).get("last_edited_time")


def _id_de_usuario(valor: Any) -> str | None:
    return valor.get("id") if isinstance(valor, dict) else None


def ler_created_by(prop: NotionPropertyValue | None) -> str | None:
    """Lê o ID de quem criou a página (coluna ``created_by``)."""

    return _id_de_usuario((prop or {}).get("created_by"))


def ler_last_edited_by(prop: NotionPropertyValue | None) -> str | None:
    """Lê o ID de quem editou por último (coluna ``last_edited_by``)."""

    return _id_de_usuario((prop or {}).get("last_edited_by"))


def ler_unique_id(prop: NotionPropertyValue | None) -> str | None:
    """Lê um ``unique_id`` como texto: ``"PRE-12"`` com prefixo, ``"12"`` sem."""

    valor = (prop or {}).get("unique_id")
    if not isinstance(valor, dict) or valor.get("number") is None:
        return None
    prefixo = valor.get("prefix")
    return f"{prefixo}-{valor['number']}" if prefixo else str(valor["number"])


#: Despacho ``type`` da propriedade -> função de leitura. Espelha os tipos que
#: :mod:`properties` sabe escrever, mais ``relation``/``people`` e os carimbos
#: que o Notion calcula (datas e autores de criação/edição, ``unique_id``).
_LEITORES_POR_TIPO: dict[str, Callable[[NotionPropertyValue | None], Any]] = {
    "title": ler_title,
    "rich_text": ler_rich_text,
    "select": ler_select,
    "status": ler_status,
    "multi_select": ler_multi_select,
    "date": ler_date,
    "email": ler_email,
    "phone_number": ler_phone_number,
    "url": ler_url,
    "number": ler_number,
    "checkbox": ler_checkbox,
    "relation": ler_relation,
    "people": ler_people,
    "created_time": ler_created_time,
    "last_edited_time": ler_last_edited_time,
    "created_by": ler_created_by,
    "last_edited_by": ler_last_edited_by,
    "unique_id": ler_unique_id,
}


def ler_propriedade(prop: NotionPropertyValue | None) -> Any:
    """Lê uma propriedade qualquer, despachando pelo seu campo ``type``.

    Args:
        prop: O valor de propriedade como vem da API (com a chave ``type``).

    Returns:
        O valor simples correspondente ao tipo, ou ``None`` quando o tipo ainda
        não é suportado (o JSON bruto continua acessível na página de origem).
    """

    if not isinstance(prop, dict):
        return None
    leitor = _LEITORES_POR_TIPO.get(prop.get("type", ""))
    return leitor(prop) if leitor is not None else None


def extrair_valores(pagina: dict[str, Any]) -> dict[str, Any]:
    """Reduz uma página do Notion a um mapa ``nome_da_coluna -> valor simples``.

    Atalho de leitura para front, IA e integrações: em vez de navegar o JSON
    aninhado de cada propriedade, recebe-se um dicionário plano e legível.

    Args:
        pagina: Item retornado por :meth:`NotionClient.consultar_database` ou
            por uma leitura de página (precisa ter a chave ``properties``).

    Returns:
        Um mapa do nome de cada coluna para o seu valor simples. Tipos ainda não
        suportados aparecem com valor ``None``.
    """

    props = (pagina or {}).get("properties", {})
    return {nome: ler_propriedade(prop) for nome, prop in props.items()}
