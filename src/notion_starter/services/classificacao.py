"""Classificação em lote de linhas, com relatório e *dry-run* seguro.

O padrão para preencher uma coluna em centenas de linhas é sempre o mesmo:
aplicar uma regra pura, conferir a distribuição resultante e só depois fazer as
escritas. Este módulo concentra a parte repetitiva sem buscar linhas por conta
própria: o chamador passa as linhas já consultadas e decide explicitamente se
quer aplicar a classificação.

Por padrão, :func:`classificar_em_lote` não faz nenhuma escrita. A aplicação
pode ser feita na mesma chamada com ``aplicar=True`` ou depois, com
:func:`aplicar_classificacoes`. O serviço aceita um callback genérico para
escrita e também oferece um atalho para ``NotionClient``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from notion_starter import NotionClient, properties

ValorClassificacao = Hashable
RegraClassificacao = Callable[[Any], ValorClassificacao | None]
AplicadorClassificacao = Callable[[Any, ValorClassificacao], Any]
MontadorPropriedade = Callable[[ValorClassificacao], dict[str, Any]]


@dataclass(frozen=True)
class LinhaClassificada:
    """Uma linha que recebeu um valor, preservando a linha original."""

    linha: Any
    valor: ValorClassificacao
    id: str | None = None

    @property
    def page_id(self) -> str | None:
        """ID da página no Notion, quando a linha tem um ``id``."""

        return self.id


# Nome alternativo para quem prefere a forma substantiva da operação.
ClassificacaoLinha = LinhaClassificada


@dataclass
class ResultadoClassificacao:
    """Relatório de uma classificação em lote.

    ``linhas_sem_classificacao`` contém as linhas originais, e não apenas os
    IDs, para permitir uma segunda análise sem uma nova consulta ao Notion.
    ``classificacoes`` mantém o par linha/valor necessário para uma aplicação
    posterior.
    """

    distribuicao: dict[ValorClassificacao, int] = field(default_factory=dict)
    classificacoes: list[LinhaClassificada] = field(default_factory=list)
    sem_classificacao: list[Any] = field(default_factory=list)
    aplicadas: int = 0
    aplicado: bool = False

    @property
    def por_valor(self) -> dict[ValorClassificacao, int]:
        """Alias legível para a distribuição por valor."""

        return self.distribuicao

    @property
    def linhas_classificadas(self) -> list[Any]:
        """Linhas que receberam classificação, na ordem de entrada."""

        return [item.linha for item in self.classificacoes]

    @property
    def linhas_sem_classificacao(self) -> list[Any]:
        """Alias explícito para as linhas que ficaram sem valor."""

        return self.sem_classificacao

    @property
    def ids_sem_classificacao(self) -> list[str]:
        """IDs das linhas sem classificação que possuem ``id``."""

        return [id_ for id_ in (_id_da_linha(linha) for linha in self.sem_classificacao) if id_]

    @property
    def total(self) -> int:
        """Quantidade total de linhas analisadas."""

        return len(self.classificacoes) + len(self.sem_classificacao)

    @property
    def classificadas(self) -> int:
        """Quantidade de linhas que receberam classificação."""

        return len(self.classificacoes)

    @property
    def pendentes(self) -> int:
        """Quantidade de linhas sem classificação."""

        return len(self.sem_classificacao)

    def aplicar(
        self,
        *,
        aplicador: AplicadorClassificacao | None = None,
        cliente: NotionClient | None = None,
        coluna: str | None = None,
        montar_propriedade: MontadorPropriedade | None = None,
    ) -> int:
        """Aplica as classificações deste relatório uma única vez por chamada.

        Args:
            aplicador: Callback ``(linha, valor)`` que efetiva uma escrita.
            cliente: Cliente Notion para usar o atalho de atualização de página.
            coluna: Nome exato da coluna a atualizar quando ``cliente`` é usado.
            montar_propriedade: Converte o valor em payload de propriedade.
                O padrão é ``properties.select``.

        Returns:
            Quantidade de linhas efetivamente enviadas para o aplicador.

        Raises:
            ValueError: Se nenhuma forma de aplicação for informada ou se uma
                linha não tiver ID ao usar ``cliente``.

        ``sem_classificacao`` nunca é aplicado. Se o aplicador falhar no meio,
        a exceção sobe e ``aplicadas`` conserva a quantidade que já teve
        sucesso, permitindo diagnóstico do lote parcial.
        """

        efetivar = _resolver_aplicador(
            aplicador=aplicador,
            cliente=cliente,
            coluna=coluna,
            montar_propriedade=montar_propriedade,
        )
        self.aplicado = True
        for item in self.classificacoes:
            efetivar(item.linha, item.valor)
            self.aplicadas += 1
        return len(self.classificacoes)


def classificar_em_lote(
    linhas: Iterable[Any],
    regra: RegraClassificacao,
    *,
    aplicar: bool = False,
    aplicador: AplicadorClassificacao | None = None,
    cliente: NotionClient | None = None,
    coluna: str | None = None,
    montar_propriedade: MontadorPropriedade | None = None,
) -> ResultadoClassificacao:
    """Classifica linhas e devolve a distribuição sem escrever por padrão.

    Args:
        linhas: Linhas já buscadas. Cada item pode ser qualquer objeto; ao usar
            ``cliente`` para aplicar, ele precisa ter ``id``.
        regra: Função que recebe uma linha e devolve o valor da classificação.
            ``None`` ou texto vazio significam que a linha ficou sem
            classificação.
        aplicar: Quando verdadeiro, aplica as classificações logo após montar
            o relatório. O padrão ``False`` é um *dry-run*.
        aplicador: Callback genérico ``(linha, valor)`` para a escrita.
        cliente: Atalho para chamar ``atualizar_pagina`` em cada linha.
        coluna: Nome da coluna usada com ``cliente``.
        montar_propriedade: Constrói o payload da coluna. O padrão é select;
            use, por exemplo, ``properties.status`` para uma coluna status.

    Returns:
        :class:`ResultadoClassificacao` com a distribuição, as linhas sem
        classificação e os pares necessários para aplicação posterior.

    A função não consulta o Notion e, com ``aplicar=False``, não chama nenhum
    aplicador nem exige cliente. Assim, o relatório pode ser revisado antes de
    uma segunda chamada explícita a :func:`aplicar_classificacoes`.
    """

    if not callable(regra):
        raise TypeError("regra deve ser uma função de classificação.")

    resultado = ResultadoClassificacao()
    for linha in linhas:
        valor = regra(linha)
        if _sem_classificacao(valor):
            resultado.sem_classificacao.append(linha)
            continue
        _validar_valor_classificacao(valor)
        resultado.distribuicao[valor] = resultado.distribuicao.get(valor, 0) + 1
        resultado.classificacoes.append(
            LinhaClassificada(linha=linha, valor=valor, id=_id_da_linha(linha))
        )

    if aplicar:
        resultado.aplicar(
            aplicador=aplicador,
            cliente=cliente,
            coluna=coluna,
            montar_propriedade=montar_propriedade,
        )
    return resultado


def aplicar_classificacoes(
    resultado: ResultadoClassificacao,
    *,
    aplicador: AplicadorClassificacao | None = None,
    cliente: NotionClient | None = None,
    coluna: str | None = None,
    montar_propriedade: MontadorPropriedade | None = None,
) -> int:
    """Aplica explicitamente um relatório produzido por ``classificar_em_lote``.

    Esta forma separada é útil quando a distribuição precisa ser mostrada ou
    revisada entre o *dry-run* e a escrita.
    """

    if not isinstance(resultado, ResultadoClassificacao):
        raise TypeError("resultado deve ser um ResultadoClassificacao.")
    return resultado.aplicar(
        aplicador=aplicador,
        cliente=cliente,
        coluna=coluna,
        montar_propriedade=montar_propriedade,
    )


def _resolver_aplicador(
    *,
    aplicador: AplicadorClassificacao | None,
    cliente: NotionClient | None,
    coluna: str | None,
    montar_propriedade: MontadorPropriedade | None,
) -> AplicadorClassificacao:
    """Monta um aplicador genérico ou um aplicador baseado no cliente Notion."""

    if aplicador is not None:
        if not callable(aplicador):
            raise TypeError("aplicador deve ser uma função de escrita.")
        if cliente is not None or coluna is not None or montar_propriedade is not None:
            raise ValueError(
                "Informe aplicador ou cliente/coluna, não as duas formas de aplicação."
            )
        return aplicador

    if cliente is None:
        raise ValueError(
            "Para aplicar, informe aplicador ou cliente junto com a coluna da classificação."
        )
    if not coluna or not coluna.strip():
        raise ValueError("coluna é obrigatória quando cliente é usado para aplicar.")
    if montar_propriedade is not None and not callable(montar_propriedade):
        raise TypeError("montar_propriedade deve ser uma função de escrita.")

    nome_coluna = coluna.strip()
    montar = montar_propriedade or _montar_select

    def atualizar(linha: Any, valor: ValorClassificacao) -> None:
        page_id = _id_da_linha(linha)
        if not page_id:
            raise ValueError(
                "Toda linha classificada precisa de 'id' para aplicação via Notion."
            )
        propriedade = montar(valor)
        if not isinstance(propriedade, dict):
            raise TypeError("montar_propriedade deve devolver um dicionário de propriedade.")
        cliente.atualizar_pagina(page_id, {nome_coluna: propriedade})

    return atualizar


def _montar_select(valor: ValorClassificacao) -> dict[str, Any]:
    """Converte o valor padrão de uma classificação em uma opção select."""

    return properties.select(str(valor))


def _id_da_linha(linha: Any) -> str | None:
    """Lê o ID de uma linha sem exigir que a classificação conheça Notion."""

    if not isinstance(linha, Mapping):
        return None
    valor = linha.get("id")
    return str(valor) if valor else None


def _sem_classificacao(valor: Any) -> bool:
    """Identifica ausência de classificação sem descartar valores falsos válidos."""

    return valor is None or (isinstance(valor, str) and not valor.strip())


def _validar_valor_classificacao(valor: Any) -> None:
    """Garante que o valor possa ser contado na distribuição."""

    try:
        hash(valor)
    except TypeError as exc:
        raise TypeError(
            "A regra deve devolver valores classificáveis (hashable), None ou texto vazio."
        ) from exc


__all__ = [
    "AplicadorClassificacao",
    "ClassificacaoLinha",
    "LinhaClassificada",
    "MontadorPropriedade",
    "RegraClassificacao",
    "ResultadoClassificacao",
    "ValorClassificacao",
    "aplicar_classificacoes",
    "classificar_em_lote",
]
