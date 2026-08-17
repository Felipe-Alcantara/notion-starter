"""Caso de uso: manter um relatório por dia em um database do Notion.

Idempotente **pela data**: antes de criar, procura no database uma página cuja
propriedade de data seja o dia informado. Se existir, o corpo novo é *anexado*
à página existente em vez de gerar uma linha duplicada — um mesmo dia costuma
acumular trabalho de mais de um projeto, e o registro do outro projeto não pode
ser perdido nem sobrescrito.

Não conhece a origem do conteúdo: recebe :class:`RelatorioDiario` já pronto.
Para montar relatórios a partir do histórico de um repositório, veja
:mod:`notion_starter.git_historico`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from notion_starter import NotionClient, properties
from notion_starter.services.conteudo import escrever_conteudo

#: Nome padrão das propriedades, seguindo a convenção da database de relatórios.
PROPRIEDADE_DATA_PADRAO = "Data"


@dataclass(frozen=True)
class RelatorioDiario:
    """Conteúdo de um dia, pronto para virar (ou complementar) uma página.

    ``propriedades`` aceita valores **já no formato do Notion** (montados com
    :mod:`notion_starter.properties`), permitindo preencher qualquer coluna do
    database sem que este serviço precise conhecê-las.
    """

    data: str  # ISO (AAAA-MM-DD)
    titulo: str = ""
    corpo_markdown: str = ""
    propriedades: dict[str, dict[str, object]] = field(default_factory=dict)

    def titulo_final(self, modelo: str) -> str:
        if self.titulo:
            return self.titulo
        ano, mes, dia = self.data.split("-")
        return modelo.format(data=f"{dia}/{mes}/{ano}", data_iso=self.data)


@dataclass(frozen=True)
class ResultadoRelatorio:
    """O que aconteceu com um dia processado."""

    data: str
    page_id: str
    criada: bool
    blocos_escritos: int
    url: str = ""

    @property
    def acao(self) -> str:
        return "criada" if self.criada else "complementada"


@dataclass(frozen=True)
class ResultadoPublicacao:
    """Consolidado de uma execução."""

    relatorios: tuple[ResultadoRelatorio, ...] = field(default_factory=tuple)

    @property
    def criadas(self) -> int:
        return sum(1 for r in self.relatorios if r.criada)

    @property
    def complementadas(self) -> int:
        return sum(1 for r in self.relatorios if not r.criada)


def _propriedade_titulo(propriedades: dict[str, Any]) -> str:
    for nome, definicao in propriedades.items():
        if definicao.get("type") == "title":
            return nome
    raise ValueError("O database não tem propriedade de título.")


def paginas_por_data(
    database_id: str,
    *,
    propriedade_data: str = PROPRIEDADE_DATA_PADRAO,
    cliente: NotionClient | None = None,
) -> dict[str, str]:
    """Mapeia ``data ISO -> page_id`` das páginas já existentes no database.

    Quando o mesmo dia aparece mais de uma vez (o database não impede), vence a
    primeira ocorrência retornada pela consulta, para que a execução seja
    determinística.
    """
    client = cliente or NotionClient()
    encontrados: dict[str, str] = {}
    for pagina in client.consultar_database(database_id, buscar_todos=True):
        valor = pagina.get("properties", {}).get(propriedade_data, {}).get("date")
        inicio = (valor or {}).get("start")
        if not inicio:
            continue
        # A propriedade pode guardar data com hora ("2026-07-24T09:00:00Z").
        data = inicio.split("T")[0]
        encontrados.setdefault(data, pagina["id"])
    return encontrados


def publicar_relatorios(
    database_id: str,
    relatorios: Iterable[RelatorioDiario],
    *,
    propriedade_data: str = PROPRIEDADE_DATA_PADRAO,
    modelo_titulo: str = "Relatório — {data}",
    atualizar_propriedades_existentes: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoPublicacao:
    """Cria ou complementa um relatório por data, sem duplicar.

    Args:
        database_id: Database que guarda os relatórios.
        relatorios: Dias a publicar.
        propriedade_data: Nome da propriedade de data usada como chave.
        modelo_titulo: Modelo do título quando o relatório não traz um;
            aceita ``{data}`` (DD/MM/AAAA) e ``{data_iso}``.
        atualizar_propriedades_existentes: Por padrão, páginas que já existem
            só recebem o corpo novo — as propriedades ficam como estão, porque
            costumam descrever o trabalho de outro projeto no mesmo dia. Ative
            para sobrescrevê-las também.
        cliente: Cliente já configurado (opcional).

    Returns:
        :class:`ResultadoPublicacao` com o destino de cada dia.
    """
    client = cliente or NotionClient()
    nome_titulo = _propriedade_titulo(client.get_database(database_id).get("properties", {}))
    existentes = paginas_por_data(database_id, propriedade_data=propriedade_data, cliente=client)

    resultados: list[ResultadoRelatorio] = []
    for relatorio in relatorios:
        page_id = existentes.get(relatorio.data)
        criada = page_id is None
        url = ""

        propriedades = dict(relatorio.propriedades)
        titulo = relatorio.titulo_final(modelo_titulo)
        propriedades.setdefault(nome_titulo, properties.title(titulo))
        propriedades.setdefault(propriedade_data, properties.date(relatorio.data))

        if criada:
            pagina = client.criar_pagina(database_id, propriedades)
            page_id = pagina["id"]
            url = pagina.get("url", "")
            # Mantém o mapa coerente se a mesma data vier repetida na entrada.
            existentes[relatorio.data] = page_id
        elif atualizar_propriedades_existentes:
            client.atualizar_pagina(page_id, propriedades)

        blocos = 0
        if relatorio.corpo_markdown.strip():
            # `int(...)`: escrever_conteudo passou a devolver um resultado rico
            # (o que anexou e o que a substituição preservou), que converte para
            # a contagem antiga. Converter em vez de ler o campo mantém válido
            # qualquer double que devolva só o número.
            blocos = int(escrever_conteudo(page_id, relatorio.corpo_markdown, cliente=client))

        resultados.append(
            ResultadoRelatorio(
                data=relatorio.data,
                page_id=page_id,
                criada=criada,
                blocos_escritos=blocos,
                url=url,
            )
        )
    return ResultadoPublicacao(relatorios=tuple(resultados))
