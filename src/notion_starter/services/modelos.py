"""Caso de uso: listar e preencher os **modelos nativos** de um database.

O que a API permite (medido em 2026-09-27, versão ``2025-09-03``):

* **listar** os modelos: ``GET /data_sources/{id}/templates`` devolve
  ``{"id", "name", "is_default"}``; um modelo sem título aparece como
  ``"New page"``;
* **preencher** um modelo existente: ele é uma página comum, então o PATCH de
  propriedades e o append de blocos funcionam.

O que a API **não** permite: criar um modelo novo nem escolher o padrão — isso
só pela interface do Notion. Daí o fluxo deste módulo:

1. a pessoa clica em "Novo modelo" no Notion quantas vezes precisar, sem digitar
   nada (cada clique deixa um modelo "New page" vazio);
2. :func:`preencher_modelos` dá a cada modelo vazio o nome, as colunas e o corpo
   de um item do manifesto (:func:`carregar_manifesto`).

É idempotente: um modelo que já tem o nome do item **e** corpo é pulado; um que
tem o nome mas ficou sem corpo (rodada interrompida) é completado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from notion_starter import NotionClient
from notion_starter import properties as prop
from notion_starter.exceptions import NotionSyncError

#: Nomes com que um modelo sem título aparece (comparação sem caixa).
NOMES_SEM_TITULO = frozenset({"", "new page", "untitled", "nova página", "sem título"})

AcaoModelo = Literal["preenchido", "completado", "ja_existia", "sem_modelo_vazio"]


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


class ManifestoInvalidoError(NotionSyncError, ValueError):
    """O manifesto de modelos tem problemas; nada foi escrito.

    Attributes:
        problemas: Uma frase por problema, com o item afetado.
    """

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = list(problemas)
        super().__init__("Manifesto de modelos inválido: " + "; ".join(self.problemas))


@dataclass(frozen=True)
class ItemModelo:
    """Um modelo desejado: nome, de onde vem o corpo e as colunas-padrão.

    Attributes:
        nome: Nome do modelo (vira o título da página-modelo).
        arquivo: Markdown do corpo, já resolvido a partir da pasta do manifesto.
        copiar_de: Página cujo corpo é copiado bloco a bloco (alternativa ao
            ``arquivo``, para corpos com tabela, colunas ou callout).
        propriedades: ``{coluna: valor em texto}``, no formato do ``editar-linha``.
    """

    nome: str
    arquivo: Path | None = None
    copiar_de: str | None = None
    propriedades: dict[str, str] = field(default_factory=dict)

    @property
    def tem_corpo(self) -> bool:
        """O item diz de onde vem o corpo."""

        return self.arquivo is not None or bool(self.copiar_de)


@dataclass(frozen=True)
class ModeloNativo:
    """Um modelo nativo como a API o lista."""

    id: str
    nome: str
    padrao: bool

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {"id": self.id, "nome": self.nome, "padrao": self.padrao}


@dataclass(frozen=True)
class AcaoNoModelo:
    """O que a rodada fez (ou faria, no ``dry_run``) com um item do manifesto."""

    nome: str
    acao: AcaoModelo
    modelo_id: str | None = None
    detalhe: str = ""

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {
            "nome": self.nome,
            "acao": self.acao,
            "modelo_id": self.modelo_id,
            "detalhe": self.detalhe,
        }


@dataclass(frozen=True)
class ResultadoModelos:
    """Resultado de :func:`preencher_modelos`.

    Attributes:
        data_source_id: Fonte cujos modelos foram lidos.
        acoes: Uma ação por item do manifesto, na ordem dele.
        vazios_restantes: Modelos vazios que sobraram sem uso.
        dry_run: Nada foi escrito.
    """

    data_source_id: str
    acoes: tuple[AcaoNoModelo, ...]
    vazios_restantes: int
    dry_run: bool

    @property
    def faltam(self) -> int:
        """Quantos modelos vazios ainda precisam ser criados na interface."""

        return sum(1 for a in self.acoes if a.acao == "sem_modelo_vazio")

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {
            "data_source_id": self.data_source_id,
            "dry_run": self.dry_run,
            "acoes": [a.para_dict() for a in self.acoes],
            "vazios_restantes": self.vazios_restantes,
            "faltam_modelos_vazios": self.faltam,
        }


def carregar_manifesto(caminho: Path | str) -> list[ItemModelo]:
    """Lê e valida um manifesto JSON de modelos.

    Formato: uma lista (ou ``{"modelos": [...]}``) de objetos com ``nome``
    (obrigatório), ``arquivo`` (Markdown, relativo à pasta do manifesto) **ou**
    ``copiar_de`` (ID da página de origem do corpo), e ``propriedades``
    (``{coluna: valor}``).

    Raises:
        ManifestoInvalidoError: Com todos os problemas de uma vez.
    """

    caminho = Path(caminho)
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestoInvalidoError([f"não foi possível ler {caminho}: {exc}"]) from exc
    itens_brutos = bruto.get("modelos") if isinstance(bruto, dict) else bruto
    if not isinstance(itens_brutos, list):
        raise ManifestoInvalidoError(["o manifesto deve ser uma lista de modelos"])

    problemas: list[str] = []
    itens: list[ItemModelo] = []
    vistos: set[str] = set()
    for posicao, item in enumerate(itens_brutos, start=1):
        rotulo = f"item {posicao}"
        if not isinstance(item, dict):
            problemas.append(f"{rotulo}: deve ser um objeto")
            continue
        nome = str(item.get("nome") or "").strip()
        if not nome:
            problemas.append(f"{rotulo}: 'nome' é obrigatório")
            continue
        rotulo = f"{rotulo} ({nome})"
        if nome.casefold() in vistos:
            problemas.append(f"{rotulo}: nome repetido no manifesto")
        vistos.add(nome.casefold())
        arquivo_bruto, copiar_de = item.get("arquivo"), item.get("copiar_de")
        if arquivo_bruto and copiar_de:
            problemas.append(f"{rotulo}: use 'arquivo' ou 'copiar_de', não os dois")
        arquivo: Path | None = None
        if arquivo_bruto:
            arquivo = (caminho.parent / str(arquivo_bruto)).resolve()
            if not arquivo.is_file():
                problemas.append(f"{rotulo}: arquivo não encontrado: {arquivo}")
        propriedades = item.get("propriedades") or {}
        if not isinstance(propriedades, dict):
            problemas.append(f"{rotulo}: 'propriedades' deve ser um objeto")
            propriedades = {}
        itens.append(
            ItemModelo(
                nome=nome,
                arquivo=arquivo,
                copiar_de=str(copiar_de).strip() if copiar_de else None,
                propriedades={str(k): str(v) for k, v in propriedades.items()},
            )
        )
    if problemas:
        raise ManifestoInvalidoError(problemas)
    return itens


def listar_modelos(
    database_id: str,
    *,
    data_source_id: str | None = None,
    cliente: NotionClient | None = None,
) -> list[ModeloNativo]:
    """Lista os modelos nativos do database (da fonte única ou da informada)."""

    cli = cliente or _cliente_padrao()
    fonte = data_source_id or cli.resolver_data_source(database_id)
    return [
        ModeloNativo(
            id=str(m.get("id") or ""),
            nome=str(m.get("name") or ""),
            padrao=bool(m.get("is_default")),
        )
        for m in cli.listar_modelos(fonte)
    ]


def _payloads(
    itens: list[ItemModelo], schema: dict[str, Any]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Converte as colunas de cada item, validando tudo **antes** de escrever."""

    titulo = next((n for n, d in schema.items() if d.get("type") == "title"), None)
    problemas: list[str] = []
    if titulo is None:
        problemas.append("o database não tem coluna de título")
    payloads: dict[str, dict[str, dict[str, Any]]] = {}
    for item in itens:
        payload: dict[str, dict[str, Any]] = {}
        if titulo is not None:
            payload[titulo] = prop.title(item.nome)
        for coluna, texto in item.propriedades.items():
            definicao = schema.get(coluna)
            if not isinstance(definicao, dict):
                disponiveis = ", ".join(sorted(schema))
                problemas.append(
                    f"{item.nome}: coluna '{coluna}' não existe (disponíveis: {disponiveis})"
                )
                continue
            try:
                payload[coluna] = prop.valor_de_texto(str(definicao.get("type") or ""), texto)
            except ValueError as exc:
                problemas.append(f"{item.nome}: coluna '{coluna}': {exc}")
        payloads[item.nome] = payload
    if problemas:
        raise ManifestoInvalidoError(problemas)
    return payloads


def _escrever_corpo(cli: NotionClient, modelo_id: str, item: ItemModelo) -> None:
    if item.arquivo is not None:
        from notion_starter.services.conteudo import escrever_conteudo

        escrever_conteudo(modelo_id, item.arquivo.read_text(encoding="utf-8"), cliente=cli)
    elif item.copiar_de:
        from notion_starter.services.copia_corpo import copiar_corpo

        copiar_corpo(item.copiar_de, modelo_id, so_se_vazio=True, cliente=cli)


def preencher_modelos(
    database_id: str,
    itens: list[ItemModelo],
    *,
    data_source_id: str | None = None,
    dry_run: bool = False,
    cliente: NotionClient | None = None,
) -> ResultadoModelos:
    """Dá nome, colunas e corpo aos modelos vazios, na ordem do manifesto.

    Um modelo é **vazio** quando não tem corpo e o nome é o de um modelo sem
    título (:data:`NOMES_SEM_TITULO`, como o ``"New page"`` medido) — um modelo
    com nome próprio nunca é reaproveitado, mesmo sem corpo.

    Args:
        database_id: Database dono dos modelos.
        itens: Itens do manifesto (ver :func:`carregar_manifesto`).
        data_source_id: Fonte a usar quando o database tem mais de uma.
        dry_run: Só planeja: diz qual modelo receberia cada item.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        O :class:`ResultadoModelos`, com uma ação por item.

    Raises:
        ManifestoInvalidoError: Coluna inexistente, calculada ou valor inválido
            em algum item — conferido antes da primeira escrita.
        FonteDeDadosIndefinidaError: Database com zero ou várias fontes, sem
            ``data_source_id``.
    """

    cli = cliente or _cliente_padrao()
    fonte = data_source_id or cli.resolver_data_source(database_id)
    schema = cli.get_data_source(fonte).get("properties") or {}
    payloads = _payloads(itens, schema)

    modelos = [m for m in cli.listar_modelos(fonte) if m.get("id")]
    corpo: dict[str, bool] = {}

    def tem_corpo(modelo_id: str) -> bool:
        if modelo_id not in corpo:
            corpo[modelo_id] = bool(cli.ler_blocos(modelo_id))
        return corpo[modelo_id]

    por_nome = {str(m.get("name") or "").strip(): m for m in modelos}
    nomes_do_manifesto = {item.nome for item in itens}
    vazios = [
        m for m in modelos
        if str(m.get("name") or "").strip().casefold() in NOMES_SEM_TITULO
        and str(m.get("name") or "").strip() not in nomes_do_manifesto
        and not tem_corpo(str(m["id"]))
    ]

    acoes: list[AcaoNoModelo] = []
    for item in itens:
        existente = por_nome.get(item.nome)
        if existente is not None:
            modelo_id = str(existente["id"])
            if tem_corpo(modelo_id) or not item.tem_corpo:
                acoes.append(AcaoNoModelo(item.nome, "ja_existia", modelo_id))
                continue
            if not dry_run:
                cli.atualizar_pagina(modelo_id, payloads[item.nome])
                _escrever_corpo(cli, modelo_id, item)
            acoes.append(
                AcaoNoModelo(item.nome, "completado", modelo_id, "tinha o nome, faltava o corpo")
            )
            continue
        if not vazios:
            acoes.append(
                AcaoNoModelo(
                    item.nome,
                    "sem_modelo_vazio",
                    detalhe="crie mais um modelo em branco no Notion (Novo modelo, sem "
                    "digitar nada) e rode de novo",
                )
            )
            continue
        modelo_id = str(vazios.pop(0)["id"])
        if not dry_run:
            # Nome e colunas primeiro: se o corpo falhar, a próxima rodada acha o
            # modelo pelo nome e só completa o corpo.
            cli.atualizar_pagina(modelo_id, payloads[item.nome])
            _escrever_corpo(cli, modelo_id, item)
        acoes.append(AcaoNoModelo(item.nome, "preenchido", modelo_id))

    return ResultadoModelos(
        data_source_id=fonte,
        acoes=tuple(acoes),
        vazios_restantes=len(vazios),
        dry_run=dry_run,
    )
