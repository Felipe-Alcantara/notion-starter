"""Exceções de domínio do ``notion_starter``."""

from __future__ import annotations

import json
from typing import Any


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


class EscritaParcialError(NotionSyncError, RuntimeError):
    """Uma escrita em lotes falhou depois de começar.

    O serviço tenta **desfazer** o que já tinha criado (apaga os blocos novos
    cujos IDs conhece), para que repetir o comando não duplique conteúdo. O que
    não pôde ser desfeito fica listado. Deriva também de ``RuntimeError``, o
    tipo que a escrita parcial levantava antes.

    Attributes:
        page_id: Página (ou bloco) que recebia a escrita.
        total: Blocos de topo que seriam escritos.
        criados: ``(id, tipo)`` dos blocos novos que **continuam** na página.
        desfeitos: IDs dos blocos novos que foram apagados de novo.
        lote_incerto: A falha foi de rede ou 5xx num lote: ele pode ter sido
            gravado sem que os IDs chegassem aqui — confira antes de repetir.
        substituicao: Era uma substituição: nada do conteúdo antigo foi apagado.
        causa: A exceção original, quando houver.
    """

    def __init__(
        self,
        *,
        page_id: str,
        total: int,
        criados: list[tuple[str, str]],
        desfeitos: list[str],
        lote_incerto: bool,
        substituicao: bool,
        causa: BaseException | None,
        detalhe: str = "",
    ) -> None:
        self.page_id = page_id
        self.total = total
        self.criados = list(criados)
        self.desfeitos = list(desfeitos)
        self.lote_incerto = lote_incerto
        self.substituicao = substituicao
        self.causa = causa
        partes = [f"Escrita parcial em {page_id}: a escrita de {total} blocos falhou"]
        motivo = detalhe or (str(causa) if causa is not None else "")
        if motivo:
            partes[0] += f" ({motivo})"
        partes[0] += "."
        if self.desfeitos:
            partes.append(
                f"Os {len(self.desfeitos)} blocos já criados foram removidos de novo."
            )
        if self.criados:
            ids = ", ".join(bloco_id for bloco_id, _ in self.criados)
            partes.append(f"Ficaram na página {len(self.criados)} blocos novos: {ids}.")
        if lote_incerto:
            partes.append(
                f"O último lote pode ter sido gravado mesmo assim (a resposta se perdeu): "
                f"confira com 'blocos {page_id}' antes de repetir."
            )
        if substituicao:
            partes.append("Nada do conteúdo antigo foi apagado.")
        super().__init__(" ".join(partes))


class LimpezaIncompletaError(NotionSyncError):
    """Apagar os blocos de uma página falhou no meio.

    Carrega o que já foi para a lixeira (com os IDs, que é o que permite
    restaurar — ``restaurar_bloco``) e o que ficou. Numa substituição, a
    limpeza roda **depois** de escrever o conteúdo novo, então ``blocos_novos``
    lista o que já foi escrito.

    Attributes:
        apagados: ``(id, tipo)`` de cada bloco já arquivado.
        pendentes: ``(id, tipo)`` de cada bloco que ainda devia ser apagado.
        blocos_novos: IDs do conteúdo novo já escrito (substituição).
        causa: A exceção original.
    """

    def __init__(
        self,
        *,
        apagados: list[tuple[str, str]],
        pendentes: list[tuple[str, str]],
        causa: BaseException | None,
        blocos_novos: list[str] | None = None,
    ) -> None:
        self.apagados = list(apagados)
        self.pendentes = list(pendentes)
        self.blocos_novos = list(blocos_novos or [])
        self.causa = causa
        apagados_txt = ", ".join(bloco_id for bloco_id, _ in self.apagados) or "nenhum"
        pendentes_txt = ", ".join(bloco_id for bloco_id, _ in self.pendentes) or "nenhum"
        mensagem = (
            f"A limpeza parou no meio ({causa}). Já na lixeira: {apagados_txt}. Ainda na "
            f"página: {pendentes_txt}. Para desfazer, restaure os IDs apagados com "
            "restaurar_bloco (voltam no fim da página); para concluir, repita a operação."
        )
        if self.blocos_novos:
            mensagem += f" O conteúdo novo já foi escrito ({len(self.blocos_novos)} blocos)."
        super().__init__(mensagem)


class EdicaoDeBlocoError(NotionSyncError, ValueError):
    """Base das recusas de edição de um bloco — levantadas **antes** do PATCH.

    Deriva também de ``ValueError`` para as bordas que já tratavam entrada
    inválida por esse tipo (código 2 na CLI, erro de ferramenta no MCP).
    """


class EdicaoMultiblocoError(EdicaoDeBlocoError):
    """O Markdown gerou mais de um bloco, mas a edição troca **um** bloco.

    Attributes:
        quantidade: Quantos blocos o Markdown gerou.
    """

    def __init__(self, quantidade: int) -> None:
        self.quantidade = quantidade
        super().__init__(
            f"editar_bloco edita UM bloco, mas o Markdown gerou {quantidade} blocos; nada "
            "foi alterado. Mande uma linha só, ou edite este bloco e insira os demais "
            "depois dele com escrever_conteudo(..., apos_bloco_id=<id deste bloco>)."
        )


class BlocoSemTextoError(EdicaoDeBlocoError):
    """O bloco não tem ``rich_text`` para editar (imagem, divisória, subpágina…).

    Attributes:
        tipo: Tipo do bloco.
    """

    def __init__(self, block_id: str, tipo: str) -> None:
        self.tipo = tipo
        dica = (
            " Para renomear subpágina ou database, edite o título da página/database."
            if tipo in ("child_page", "child_database")
            else ""
        )
        super().__init__(
            f"O bloco {block_id} é do tipo '{tipo}', que não tem texto editável.{dica}"
        )


class TrocaDeTipoError(EdicaoDeBlocoError):
    """O Markdown pede outro tipo de bloco; a API não troca o tipo de um bloco existente.

    Attributes:
        tipo_atual: Tipo do bloco no Notion.
        tipo_pedido: Tipo que o Markdown descreve.
    """

    def __init__(self, block_id: str, tipo_atual: str, tipo_pedido: str) -> None:
        self.tipo_atual = tipo_atual
        self.tipo_pedido = tipo_pedido
        super().__init__(
            f"O bloco {block_id} é '{tipo_atual}', mas o Markdown descreve '{tipo_pedido}'; "
            "a API do Notion não troca o tipo de um bloco (\"Block type mismatch\"). "
            "Mande o texto sem o prefixo (ele mantém o tipo atual), ou apague o bloco e "
            "escreva um novo no lugar."
        )


class PerdaDeFormatacaoError(EdicaoDeBlocoError):
    """Reescrever o bloco a partir de Markdown apagaria o que o Markdown não representa.

    Markdown não guarda menção (de página, data, usuário), equação, sublinhado
    nem cor — a edição por Markdown troca o *rich text* inteiro e os perderia.

    Attributes:
        perdas: Uma descrição por item que seria perdido.
    """

    def __init__(self, block_id: str, perdas: list[str]) -> None:
        self.perdas = list(perdas)
        lista = "; ".join(self.perdas[:8])
        if len(self.perdas) > 8:
            lista += f"; e mais {len(self.perdas) - 8}"
        super().__init__(
            f"Editar o bloco {block_id} por Markdown perderia: {lista}. Nada foi "
            "alterado. Para mudar só um trecho mantendo o resto, use trocar_trecho; "
            "para reescrever mesmo assim, passe aceitar_perda_de_formatacao=True."
        )


class ExclusaoArriscadaError(NotionSyncError, ValueError):
    """Apagar este bloco levaria uma subpágina ou um database inteiro para a lixeira.

    Attributes:
        tipo: ``child_page`` ou ``child_database``.
        titulo: Título do alvo.
    """

    def __init__(self, block_id: str, tipo: str, titulo: str) -> None:
        self.tipo = tipo
        self.titulo = titulo
        alvo = "a subpágina" if tipo == "child_page" else "o database"
        super().__init__(
            f"O bloco {block_id} é {alvo} '{titulo or '(sem título)'}': apagá-lo manda "
            "para a lixeira tudo o que está dentro. Nada foi apagado. Se é isso mesmo, "
            "repita com forcar_tipos_arriscados=True."
        )


class TrechoError(EdicaoDeBlocoError):
    """Base das recusas de :func:`~notion_starter.services.conteudo.trocar_trecho`."""


class TrechoNaoEncontradoError(TrechoError):
    """O trecho não aparece no texto do bloco."""

    def __init__(self, block_id: str, trecho: str, texto_atual: str) -> None:
        self.trecho = trecho
        amostra = texto_atual if len(texto_atual) <= 200 else texto_atual[:199] + "…"
        super().__init__(
            f"O trecho '{trecho}' não está no bloco {block_id}. Texto atual: '{amostra}'."
        )


class TrechoAmbiguoError(TrechoError):
    """O trecho aparece mais de uma vez e não foi pedido trocar todas."""

    def __init__(self, block_id: str, trecho: str, ocorrencias: int) -> None:
        self.ocorrencias = ocorrencias
        super().__init__(
            f"O trecho '{trecho}' aparece {ocorrencias} vezes no bloco {block_id}; peça "
            "para trocar todas ou use um trecho mais longo."
        )


class TrechoAtravessaItensError(TrechoError):
    """O trecho cruza formatações diferentes, ou fica dentro de menção/equação."""

    def __init__(self, block_id: str, trecho: str) -> None:
        super().__init__(
            f"O trecho '{trecho}' no bloco {block_id} atravessa formatações diferentes ou "
            "fica dentro de uma menção/equação, onde não dá para trocar texto sem perder a "
            "formatação. Use um trecho que fique dentro de um só pedaço de texto."
        )


def _corpo_do_erro(texto: str) -> tuple[str | None, dict[str, Any]]:
    """``(code, additional_data)`` do corpo JSON de um erro da API, se houver."""

    try:
        corpo = json.loads(texto) if texto else None
    except ValueError:
        return None, {}
    if not isinstance(corpo, dict):
        return None, {}
    codigo = corpo.get("code") if isinstance(corpo.get("code"), str) else None
    dados = corpo.get("additional_data")
    return codigo, dados if isinstance(dados, dict) else {}


class NotionHTTPError(NotionAPIError):
    """Resposta HTTP de erro retornada pela API do Notion.

    ``codigo`` e ``dados_adicionais`` são lidos do corpo **inteiro** antes de
    ele ser truncado — ``additional_data`` (ex.: ``committed_child_ids`` de um
    503) não cabe nos 500 caracteres guardados em ``body``.

    Args:
        status_code: Código HTTP retornado.
        body: Corpo da resposta; guardado truncado em até 500 caracteres.

    Attributes:
        codigo: O ``code`` do erro (ex.: ``validation_error``), se veio.
        dados_adicionais: O ``additional_data`` do erro, se veio.
    """

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body[:500]
        self.codigo, self.dados_adicionais = _corpo_do_erro(body)
        super().__init__(f"Notion HTTP {status_code}: {self.body}")


class NotionEscritaSalvaError(NotionHTTPError):
    """HTTP 503 numa escrita que o Notion **salvou** mas não conseguiu responder.

    A documentação (https://developers.notion.com/reference/request-limits)
    diz que uma escrita pode ser salva e ainda assim devolver 503, com
    ``additional_data.retry_guidance`` pedindo para reler o objeto e **não
    repetir** — repetir duplicaria o conteúdo. Esta exceção nunca é retentada.

    Attributes:
        recurso_id: ``committed_resource_id`` (página/database criado), se veio.
        filhos_criados: ``committed_child_ids`` (blocos anexados), se vieram.
    """

    def __init__(self, status_code: int, body: str = "") -> None:
        super().__init__(status_code, body)
        recurso = self.dados_adicionais.get("committed_resource_id")
        self.recurso_id = str(recurso) if recurso else None
        filhos = self.dados_adicionais.get("committed_child_ids")
        self.filhos_criados = [str(f) for f in filhos] if isinstance(filhos, list) else []
        detalhes = []
        if self.recurso_id:
            detalhes.append(f"recurso criado: {self.recurso_id}")
        if self.filhos_criados:
            detalhes.append(f"blocos criados: {', '.join(self.filhos_criados)}")
        extra = f" ({'; '.join(detalhes)})" if detalhes else ""
        self.args = (
            f"O Notion salvou a escrita, mas não respondeu a tempo (HTTP {status_code})"
            f"{extra}. NÃO repita: releia o objeto para confirmar o que foi gravado.",
        )


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


class FonteDeDadosIndefinidaError(NotionSyncError, ValueError):
    """Um database não tem exatamente um *data source* para receber a operação.

    No modelo multi-fonte do Notion (versão ``2025-09-03``) as linhas moram num
    *data source*, não no database. Quando o database tem uma fonte só, ela é a
    escolha óbvia; com nenhuma (não compartilhada com a integração) ou com
    várias, adivinhar gravaria no lugar errado — então a operação é recusada e
    a mensagem lista as fontes para quem chamou escolher.

    Attributes:
        database_id: Database consultado.
        fontes: ``(data_source_id, nome)`` de cada fonte encontrada.
    """

    def __init__(self, database_id: str, fontes: list[tuple[str, str]]) -> None:
        self.database_id = database_id
        self.fontes = list(fontes)
        if not self.fontes:
            mensagem = (
                f"O database {database_id} não expõe nenhum data source a esta "
                "integração: compartilhe-o com a integração no Notion."
            )
        else:
            listagem = ", ".join(f"{nome or '(sem nome)'} → {fonte}" for fonte, nome in fontes)
            mensagem = (
                f"O database {database_id} tem {len(self.fontes)} data sources "
                f"({listagem}): informe qual deles usar."
            )
        super().__init__(mensagem)


class MovimentoNaoAplicadoError(NotionSyncError, RuntimeError):
    """O Notion respondeu ao pedido de mover, mas a página continua em outro pai.

    Medido em 2026-09-27: ``PATCH /pages/{id}`` com ``parent`` responde 200 e
    **ignora** o campo. Por isso quem move relê a página e compara o pai; esta
    exceção é o que sobra quando a releitura não bate com o destino pedido.

    Attributes:
        page_id: Página que deveria ter sido movida.
        destino: Pai pedido, no formato ``parent`` da API.
        pai_atual: ``parent`` relido depois do pedido.
    """

    def __init__(
        self, page_id: str, destino: dict[str, Any], pai_atual: dict[str, Any]
    ) -> None:
        self.page_id = page_id
        self.destino = dict(destino)
        self.pai_atual = dict(pai_atual)
        super().__init__(
            f"A página {page_id} não foi movida: o pedido era {self.destino}, mas a "
            f"releitura mostra o pai {self.pai_atual}. Nada foi alterado."
        )


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
