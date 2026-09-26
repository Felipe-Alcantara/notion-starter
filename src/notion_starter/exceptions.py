"""Exceções de domínio do ``notion_starter``."""

from __future__ import annotations


class NotionSyncError(Exception):
    """Classe base para todas as falhas do ``notion_starter``."""


class NotionAPIError(NotionSyncError):
    """Classe base para erros originados na comunicação com a API do Notion."""


class NotionConfigurationError(NotionSyncError):
    """Configuração local necessária para chamar a API do Notion está ausente ou inválida."""


class IdNotionInvalidoError(NotionSyncError, ValueError):
    """O valor recebido não contém um ID do Notion (32 hexadecimais).

    Deriva também de ``ValueError`` para as bordas que já tratam entrada
    inválida por esse tipo continuarem funcionando.

    Attributes:
        valor: O texto recebido.
    """

    def __init__(self, valor: str) -> None:
        self.valor = valor
        super().__init__(
            f"'{valor}' não contém um ID do Notion (32 hexadecimais). Copie o link "
            "da página ou use 'buscar <termo>' para achar o ID."
        )


class RichTextNaoRegravavelError(NotionSyncError, ValueError):
    """Um item de *rich text* lido da API não pode ser reenviado numa requisição.

    A resposta traz tipos que só existem na leitura — a menção de prévia de
    link (``link_preview``) é documentada como somente leitura, e ``custom_emoji``
    nem aparece entre as menções da referência de *rich text*. Reenviar o bloco
    com um deles daria HTTP 400 (ou, pior, gravaria sem ele); a operação é
    recusada antes, dizendo o que bloqueou.

    Attributes:
        tipo: O tipo do item (ou da menção) que não pode ser gravado.
    """

    def __init__(self, tipo: str) -> None:
        self.tipo = tipo
        super().__init__(
            f"O texto tem um item do tipo '{tipo}', que a API do Notion devolve na "
            "leitura mas não aceita numa escrita; regravar o bloco o perderia."
        )


class ConteudoInvalidoError(NotionSyncError, ValueError):
    """O conteúdo a escrever passa de um limite documentado da API do Notion.

    Levantada **antes de qualquer escrita** (e, numa substituição, antes de
    apagar qualquer coisa): enviar daria HTTP 400 depois que o trabalho já
    começou. Limites em https://developers.notion.com/reference/request-limits.

    Attributes:
        problemas: Uma descrição por violação encontrada (bloco e limite).
    """

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = list(problemas)
        amostra = "; ".join(self.problemas[:5])
        resto = len(self.problemas) - 5
        if resto > 0:
            amostra += f"; e mais {resto}"
        super().__init__(
            "O conteúdo passa dos limites da API do Notion e não foi enviado (nada foi "
            f"alterado na página): {amostra}."
        )


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
