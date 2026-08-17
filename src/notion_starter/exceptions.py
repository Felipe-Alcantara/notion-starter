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


class EscritaAbaixoDeDatabaseError(NotionSyncError):
    """Tentativa de escrever bloco solto numa página que contém uma database.

    É o erro mais comum de quem recebe um link do Notion sem olhar o que tem
    dentro: a página parece um documento, mas o conteúdo de verdade mora nas
    **linhas** da database que está dentro dela. Escrever ali cria um parágrafo
    perdido embaixo da tabela — que ninguém lê, não aparece em nenhuma view e
    não vira dado.

    A exceção carrega as databases encontradas para a mensagem poder dizer
    exatamente para onde ir, em vez de só recusar.

    Attributes:
        page_id: Página em que a escrita foi tentada.
        databases: ``(database_id, título)`` de cada database dentro dela.
    """

    def __init__(self, page_id: str, databases: list[tuple[str, str]]) -> None:
        self.page_id = page_id
        self.databases = databases
        listagem = "\n".join(
            f"  - {titulo or '(sem título)'} → {database_id}"
            for database_id, titulo in databases
        )
        plural = "databases" if len(databases) > 1 else "database"
        super().__init__(
            f"A página {page_id} CONTÉM {plural}:\n{listagem}\n\n"
            "Escrever aqui cria um bloco solto ABAIXO da tabela — quase nunca é o "
            "que se quer, e o texto não vira linha nem aparece nas views.\n\n"
            "O que fazer no lugar:\n"
            "  1. Liste as linhas:            notion-tasks linhas <database_id>\n"
            "  2. Ache a linha certa e leia:  notion-tasks conteudo <linha_id>\n"
            "  3. Escreva NA LINHA:           notion-tasks editar-linha <linha_id> "
            '--set "Coluna=valor"\n'
            "                                 notion-tasks escrever <linha_id> "
            '"# Texto"\n'
            "  (linha nova: notion-tasks criar \"Título\" --set ... --conteudo ...)\n\n"
            "Se você realmente quer um bloco solto na página, repita com "
            "--mesmo-com-database."
        )
