"""Caso de uso: mover uma página sabendo antes o que acontece com as colunas.

Mover não é só trocar o lugar. Medido no workspace real em 2026-09-27, ao mover
uma linha para **outro** database pelo ``POST /pages/{id}/move``:

* o Notion **acrescenta ao schema do destino** as colunas da origem que não
  existem lá (uma ``multi_select`` apareceu no destino com as opções da origem);
* **descarta** o valor que conflita com o destino (um ``select`` cujas opções
  eram outras perdeu o valor);
* **descarta** as relações.

Nada disso aparece na resposta do endpoint. Este módulo lê a página e o schema
do destino **antes** e devolve a previsão (:class:`PrevisaoMovimento`):
colunas que serão criadas no destino, valores que serão perdidos e o que fica.
:func:`mover_pagina` aplica o movimento só quando não há perda ou quando quem
chamou aceitou as perdas, e confirma o pai relendo a página
(:meth:`~notion_starter.client.NotionClient.mover_pagina`).

As regras de previsão seguem o que foi medido; os casos não medidos (tipo
diferente com o mesmo nome, destino página para uma linha de database) são
previstos pelo lado seguro — como perda — e marcados no ``motivo``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from notion_starter import NotionClient
from notion_starter.client import TIPOS_PAI_DE_MOVIMENTO
from notion_starter.exceptions import NotionSyncError
from notion_starter.readers import ler_propriedade

#: Tipos calculados pelo Notion: no destino passam a valer as regras de lá.
TIPOS_CALCULADOS = frozenset(
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

#: Tipos cujo valor precisa existir entre as opções do destino.
_TIPOS_COM_OPCOES = ("select", "status", "multi_select")

TipoDestino = Literal["page_id", "data_source_id"]


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


class MovimentoComPerdasError(NotionSyncError, ValueError):
    """O movimento perderia valores de colunas e ninguém aceitou a perda.

    Nada foi movido. A previsão vai junto para a mensagem (e para quem trata o
    erro) dizer exatamente o que se perderia.

    Attributes:
        previsao: A previsão calculada antes de mover.
    """

    def __init__(self, previsao: PrevisaoMovimento) -> None:
        self.previsao = previsao
        perdas = "; ".join(f"{c.nome} ({c.motivo})" for c in previsao.perdidas)
        super().__init__(
            f"Mover {previsao.page_id} perderia {len(previsao.perdidas)} valor(es): "
            f"{perdas}. Nada foi movido; aceite as perdas explicitamente para seguir."
        )


@dataclass(frozen=True)
class ColunaAfetada:
    """Uma coluna da página que o movimento muda.

    Attributes:
        nome: Nome da coluna na origem.
        tipo: Tipo da coluna na origem.
        motivo: Por que ela entra nesta lista, em linguagem direta.
        valor: Valor atual na página (forma simples de ``readers``).
    """

    nome: str
    tipo: str
    motivo: str
    valor: Any = None

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {"nome": self.nome, "tipo": self.tipo, "motivo": self.motivo, "valor": self.valor}


@dataclass(frozen=True)
class PrevisaoMovimento:
    """O que o movimento vai fazer com a página e com o destino.

    Attributes:
        page_id: Página a mover.
        titulo: Título atual da página.
        pai_atual: ``parent`` atual, como a API devolve.
        tipo_pai: Como o destino foi informado (``page_id``/``database_id``/
            ``data_source_id``).
        destino_id: ID informado como destino.
        data_source_id: Fonte que recebe a página, quando o destino é database.
        acrescentadas: Colunas que o Notion vai **criar no schema do destino**.
        perdidas: Colunas cujo **valor** não sobrevive ao movimento.
        mantidas: Colunas que existem nos dois lados com valor compatível.
        calculadas: Colunas calculadas pelo Notion (recalculadas no destino).
    """

    page_id: str
    titulo: str
    pai_atual: dict[str, Any]
    tipo_pai: str
    destino_id: str
    data_source_id: str | None = None
    acrescentadas: tuple[ColunaAfetada, ...] = ()
    perdidas: tuple[ColunaAfetada, ...] = ()
    mantidas: tuple[str, ...] = ()
    calculadas: tuple[str, ...] = ()

    @property
    def muda_schema_do_destino(self) -> bool:
        """O movimento cria colunas novas no destino."""

        return bool(self.acrescentadas)

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON), com as listas já prontas para leitura."""

        return {
            "page_id": self.page_id,
            "titulo": self.titulo,
            "pai_atual": dict(self.pai_atual),
            "tipo_pai": self.tipo_pai,
            "destino_id": self.destino_id,
            "data_source_id": self.data_source_id,
            "colunas_acrescentadas_no_destino": [c.para_dict() for c in self.acrescentadas],
            "valores_perdidos": [c.para_dict() for c in self.perdidas],
            "colunas_mantidas": list(self.mantidas),
            "colunas_calculadas": list(self.calculadas),
        }


@dataclass(frozen=True)
class ResultadoMovimento:
    """Resultado de :func:`mover_pagina`.

    Attributes:
        previsao: A previsão calculada antes de mover.
        movido: ``False`` só no ``dry_run``.
        pai_novo: ``parent`` relido depois do movimento (vazio no ``dry_run``).
    """

    previsao: PrevisaoMovimento
    movido: bool
    pai_novo: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {**self.previsao.para_dict(), "movido": self.movido, "pai_novo": self.pai_novo}


def _tem_valor(valor: Any) -> bool:
    return valor not in (None, "", [], False)


def _titulo(propriedades: dict[str, Any]) -> str:
    for prop in propriedades.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return str(ler_propriedade(prop) or "")
    return ""


def _opcoes(definicao: dict[str, Any]) -> set[str]:
    tipo = str(definicao.get("type") or "")
    corpo = definicao.get(tipo) if isinstance(definicao.get(tipo), dict) else {}
    return {str(o.get("name")) for o in corpo.get("options", []) if isinstance(o, dict)}


def _faltando_nas_opcoes(valor: Any, opcoes: set[str]) -> list[str]:
    valores = valor if isinstance(valor, list) else [valor]
    return [str(v) for v in valores if _tem_valor(v) and str(v) not in opcoes]


def classificar_colunas(
    propriedades: dict[str, Any],
    schema_destino: dict[str, Any] | None,
) -> tuple[list[ColunaAfetada], list[ColunaAfetada], list[str], list[str]]:
    """Regra pura da previsão: compara as colunas da página com o destino.

    Args:
        propriedades: ``properties`` da página, como a API devolve (com ``type``).
        schema_destino: ``properties`` do data source de destino; ``None``
            quando o destino é uma página (fora de database só existe título).

    Returns:
        ``(acrescentadas, perdidas, mantidas, calculadas)``.
    """

    acrescentadas: list[ColunaAfetada] = []
    perdidas: list[ColunaAfetada] = []
    mantidas: list[str] = []
    calculadas: list[str] = []
    for nome, prop in sorted(propriedades.items()):
        if not isinstance(prop, dict):
            continue
        tipo = str(prop.get("type") or "")
        if tipo == "title":
            continue
        if tipo in TIPOS_CALCULADOS:
            calculadas.append(nome)
            continue
        valor = ler_propriedade(prop)
        if schema_destino is None:
            if _tem_valor(valor):
                perdidas.append(
                    ColunaAfetada(
                        nome, tipo, "o destino é uma página: fora de database só o título "
                        "existe (previsão, não medido)", valor
                    )
                )
            continue
        destino = schema_destino.get(nome)
        if tipo == "relation":
            if _tem_valor(valor):
                perdidas.append(
                    ColunaAfetada(nome, tipo, "relações são descartadas ao mudar de database "
                                  "(medido)", valor)
                )
            continue
        if not isinstance(destino, dict):
            acrescentadas.append(
                ColunaAfetada(nome, tipo, "não existe no destino: o Notion cria a coluna lá "
                              "(medido)", valor)
            )
            continue
        tipo_destino = str(destino.get("type") or "")
        if tipo_destino != tipo:
            if _tem_valor(valor):
                perdidas.append(
                    ColunaAfetada(nome, tipo, f"no destino a coluna é '{tipo_destino}': o "
                                  "valor é descartado (previsão, não medido)", valor)
                )
            else:
                mantidas.append(nome)
            continue
        if tipo in _TIPOS_COM_OPCOES:
            faltando = _faltando_nas_opcoes(valor, _opcoes(destino))
            if faltando:
                perdidas.append(
                    ColunaAfetada(nome, tipo, "opção inexistente no destino: "
                                  + ", ".join(repr(f) for f in faltando)
                                  + " (medido: o valor é descartado)", valor)
                )
                continue
        mantidas.append(nome)
    return acrescentadas, perdidas, mantidas, calculadas


def prever_movimento(
    page_id: str,
    novo_pai_id: str,
    *,
    tipo_pai: str = "page_id",
    cliente: NotionClient | None = None,
) -> PrevisaoMovimento:
    """Lê a página e o destino e prevê o que o movimento faz com as colunas.

    Só lê (1 GET da página, e para destino database 1–2 GETs do schema). Não
    escreve nada.

    Args:
        page_id: Página a mover.
        novo_pai_id: Destino (página, database ou data source).
        tipo_pai: ``"page_id"``, ``"database_id"`` ou ``"data_source_id"``.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        A :class:`PrevisaoMovimento`.

    Raises:
        ValueError: ``tipo_pai`` desconhecido ou IDs vazios.
        FonteDeDadosIndefinidaError: Database de destino com zero ou várias fontes.
    """

    page_id = (page_id or "").strip()
    novo_pai_id = (novo_pai_id or "").strip()
    if not page_id or not novo_pai_id:
        raise ValueError("page_id e novo_pai_id são obrigatórios.")
    if tipo_pai not in TIPOS_PAI_DE_MOVIMENTO:
        raise ValueError(f"tipo_pai desconhecido: {tipo_pai!r}.")

    cli = cliente or _cliente_padrao()
    pagina = cli.obter_pagina(page_id)
    propriedades = pagina.get("properties") if isinstance(pagina.get("properties"), dict) else {}

    fonte_id: str | None = None
    schema: dict[str, Any] | None = None
    if tipo_pai != "page_id":
        fonte_id = (
            cli.resolver_data_source(novo_pai_id) if tipo_pai == "database_id" else novo_pai_id
        )
        fonte = cli.get_data_source(fonte_id)
        schema = fonte.get("properties") if isinstance(fonte.get("properties"), dict) else {}

    acrescentadas, perdidas, mantidas, calculadas = classificar_colunas(propriedades, schema)
    pai_atual = pagina.get("parent") if isinstance(pagina.get("parent"), dict) else {}
    return PrevisaoMovimento(
        page_id=page_id,
        titulo=_titulo(propriedades),
        pai_atual=dict(pai_atual),
        tipo_pai=tipo_pai,
        destino_id=novo_pai_id,
        data_source_id=fonte_id,
        acrescentadas=tuple(acrescentadas),
        perdidas=tuple(perdidas),
        mantidas=tuple(mantidas),
        calculadas=tuple(calculadas),
    )


def mover_pagina(
    page_id: str,
    novo_pai_id: str,
    *,
    tipo_pai: str = "page_id",
    dry_run: bool = False,
    aceitar_perdas: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoMovimento:
    """Prevê, confere e move uma página — sem perda silenciosa de valores.

    Args:
        page_id: Página a mover.
        novo_pai_id: Destino (página, database ou data source).
        tipo_pai: ``"page_id"``, ``"database_id"`` ou ``"data_source_id"``.
        dry_run: Só devolve a previsão, sem mover.
        aceitar_perdas: Move mesmo que algum valor de coluna vá se perder.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        O :class:`ResultadoMovimento` com a previsão e o pai relido.

    Raises:
        MovimentoComPerdasError: Haveria perda e ``aceitar_perdas`` é falso.
        MovimentoNaoAplicadoError: O Notion não moveu (releitura divergente).
        FonteDeDadosIndefinidaError: Database de destino com zero ou várias fontes.
    """

    cli = cliente or _cliente_padrao()
    previsao = prever_movimento(page_id, novo_pai_id, tipo_pai=tipo_pai, cliente=cli)
    if dry_run:
        return ResultadoMovimento(previsao=previsao, movido=False)
    if previsao.perdidas and not aceitar_perdas:
        raise MovimentoComPerdasError(previsao)
    # A fonte já foi resolvida na previsão: mover direto para ela evita que
    # uma fonte nova, criada entre as duas leituras, mude o alvo.
    if previsao.data_source_id:
        relida = cli.mover_pagina(page_id, previsao.data_source_id, tipo_pai="data_source_id")
    else:
        relida = cli.mover_pagina(page_id, novo_pai_id, tipo_pai="page_id")
    pai_novo = relida.get("parent") if isinstance(relida.get("parent"), dict) else {}
    return ResultadoMovimento(previsao=previsao, movido=True, pai_novo=dict(pai_novo))
