"""Exceções de domínio do ``notion_starter``."""

from __future__ import annotations


class NotionSyncError(Exception):
    """Classe base para todas as falhas do ``notion_starter``."""


class NotionAPIError(NotionSyncError):
    """Classe base para erros originados na comunicação com a API do Notion."""


class NotionConfigurationError(NotionSyncError):
    """Configuração local necessária para chamar a API do Notion está ausente ou inválida."""


class NotionHTTPError(NotionAPIError):
    """Resposta HTTP de erro retornada pela API do Notion.

    Args:
        status_code: Código HTTP retornado.
        body: Corpo da resposta, truncado em até 500 caracteres.
    """

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body[:500]
        super().__init__(f"Notion HTTP {status_code}: {self.body}")


class NotionConnectionError(NotionAPIError):
    """Falha de rede, timeout ou DNS ao chamar a API do Notion."""


class NotionInvalidResponseError(NotionAPIError):
    """A API do Notion retornou uma resposta inválida ou não JSON."""


class NotionSchemaError(NotionSyncError):
    """Schema de um database Notion incompatível com o esperado.

    Args:
        faltando: Colunas ausentes no database.
        tipo_errado: Colunas com tipo incorreto, no formato
            ``(nome, esperado, encontrado)``.
    """

    def __init__(
        self,
        faltando: list[str] | None = None,
        tipo_errado: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self.faltando = faltando or []
        self.tipo_errado = tipo_errado or []
        detalhes: list[str] = []
        if self.faltando:
            detalhes.append(f"faltando: {self.faltando}")
        if self.tipo_errado:
            detalhes.append(f"tipo errado: {self.tipo_errado}")
        super().__init__(f"Schema incompatível — {'; '.join(detalhes)}")
