"""notion_starter — um cliente Python pequeno e tipado para a API do Notion.

API pública:
    NotionClient: o cliente HTTP (cria/consulta databases, páginas e blocos).
    properties / readers: par de escrita e leitura de valores de propriedade.
    markdown_para_blocos / blocos_para_markdown: par de escrita e leitura do
        conteúdo (blocos) de uma página como Markdown.
    extrair_valores: reduz uma página do Notion a um mapa coluna -> valor simples.
    comparar_schema / SchemaComparison: valida um database contra um schema.
    construir_inventario / Inventario: mapeia o workspace (árvore, duplicatas, órfãos).
    configure_logging: logging opcional em console/arquivo.
    Exceções: NotionSyncError e suas subclasses.
"""

from __future__ import annotations

from . import properties, readers
from .client import NotionClient
from .content import blocos_para_markdown, markdown_para_blocos
from .exceptions import (
    NotionAPIError,
    NotionConfigurationError,
    NotionConnectionError,
    NotionHTTPError,
    NotionInvalidResponseError,
    NotionSchemaError,
    NotionSyncError,
)
from .inventory import (
    GrupoSchema,
    Inventario,
    ItemInventario,
    NoArvore,
    agrupar_por_assinatura,
    agrupar_por_schema,
    assinatura_perfil,
    assinatura_schema,
    construir_inventario,
    extrair_perfil_database,
    normalizar_item,
)
from .logging import configure_logging, get_logger
from .readers import extrair_valores, ler_propriedade
from .schema import (
    Schema,
    SchemaComparison,
    comparar_schema,
    extrair_tipos_propriedades,
)
from .tasks import CamposTarefa, Tarefa, TaskList, tarefa_de_pagina

__version__ = "0.1.0"

__all__ = [
    "NotionClient",
    "properties",
    "readers",
    "extrair_valores",
    "ler_propriedade",
    "markdown_para_blocos",
    "blocos_para_markdown",
    "Schema",
    "SchemaComparison",
    "comparar_schema",
    "extrair_tipos_propriedades",
    "Inventario",
    "ItemInventario",
    "NoArvore",
    "GrupoSchema",
    "construir_inventario",
    "normalizar_item",
    "assinatura_schema",
    "assinatura_perfil",
    "extrair_perfil_database",
    "agrupar_por_schema",
    "agrupar_por_assinatura",
    "TaskList",
    "Tarefa",
    "CamposTarefa",
    "tarefa_de_pagina",
    "configure_logging",
    "get_logger",
    "NotionSyncError",
    "NotionAPIError",
    "NotionConfigurationError",
    "NotionConnectionError",
    "NotionHTTPError",
    "NotionInvalidResponseError",
    "NotionSchemaError",
    "__version__",
]
