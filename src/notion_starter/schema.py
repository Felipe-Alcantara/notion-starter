"""Compara um database Notion remoto com um schema esperado."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import NotionSchemaError

#: Um schema é um mapeamento de nome de coluna para o tipo de propriedade
#: Notion esperado, ex.: ``{"Nome": "title", "Email": "email", "Cadastro": "date"}``.
Schema = dict[str, str]


@dataclass
class SchemaComparison:
    """Resultado da comparação de um database com um schema esperado.

    Attributes:
        ok: Colunas presentes com o tipo esperado, como ``(nome, tipo)``.
        faltando: Colunas esperadas ausentes no database, como ``(nome, tipo)``.
        tipo_errado: Colunas com tipo inesperado, como
            ``(nome, esperado, encontrado)``.
    """

    ok: list[tuple[str, str]] = field(default_factory=list)
    faltando: list[tuple[str, str]] = field(default_factory=list)
    tipo_errado: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def compativel(self) -> bool:
        """Se o database satisfaz o schema esperado."""

        return not self.faltando and not self.tipo_errado

    def levantar_se_incompativel(self) -> None:
        """Levanta :class:`NotionSchemaError` se o database for incompatível.

        Raises:
            NotionSchemaError: Se alguma coluna estiver faltando ou com tipo errado.
        """

        if self.compativel:
            return
        raise NotionSchemaError(
            faltando=[nome for nome, _ in self.faltando],
            tipo_errado=self.tipo_errado,
        )


def extrair_tipos_propriedades(database: dict[str, Any]) -> dict[str, str]:
    """Mapeia nome de coluna para tipo de propriedade a partir de ``get_database``.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.

    Returns:
        Um mapeamento de nome de coluna para o ``type`` da propriedade Notion.
    """

    propriedades = database.get("properties", {})
    return {nome: info.get("type", "?") for nome, info in propriedades.items()}


def comparar_schema(database: dict[str, Any], esperado: Schema) -> SchemaComparison:
    """Compara a resposta de um database com um schema esperado.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.
        esperado: Mapeamento de nome de coluna para tipo de propriedade esperado.

    Returns:
        Um :class:`SchemaComparison` descrevendo as diferenças.
    """

    atual = extrair_tipos_propriedades(database)
    comparacao = SchemaComparison()

    for coluna, tipo_esperado in esperado.items():
        if coluna not in atual:
            comparacao.faltando.append((coluna, tipo_esperado))
            continue
        tipo_atual = atual[coluna]
        if tipo_atual == tipo_esperado:
            comparacao.ok.append((coluna, tipo_atual))
        else:
            comparacao.tipo_errado.append((coluna, tipo_esperado, tipo_atual))

    return comparacao
