"""Caso de uso: ligar duas linhas por uma coluna de relação, nos dois sentidos.

O Notion declara dois tipos de relação, e o tipo **não diz** o que a API vai
fazer com a outra ponta:

- ``dual_property``: há coluna espelho declarada no alvo e o Notion sincroniza.
- ``single_property``: o nome sugere mão única, mas isso não se confirma na
  prática. Medido no workspace real em 2026-08-17, numa relação auto-referente
  que ``2022-06-28`` e ``2025-09-03`` reportam como ``single_property``: gravar
  só a ponta A **fez** a ponta B enxergar A. Já numa relação para outro
  database não existe coluna de volta onde gravar.

Conclusão prática: **não dá para deduzir o comportamento do tipo declarado.**
Assumir "grava sozinho" deixa metade da malha faltando; assumir "não grava"
gasta requisição à toa e pode duplicar.

Este módulo resolve isso do único jeito confiável — **conferindo**. Ele escreve
uma ponta, relê a outra e só grava o que ainda faltar. O resultado sai simétrico
nos dois mundos, e o retorno diz quais páginas precisaram de escrita de fato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_starter import NotionClient
from notion_starter.schema import descrever_database


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


def _sem_hifens(identificador: str) -> str:
    """Compara IDs do Notion ignorando hífens — a API aceita as duas formas."""

    return str(identificador).replace("-", "").lower()


@dataclass
class ResultadoRelacao:
    """O que a operação mudou em cada ponta da ligação.

    Attributes:
        coluna: Nome da coluna de relação usada.
        bidirecional: Se a coluna é ``dual_property`` (o Notion espelha sozinho).
        escritas: IDs das páginas que receberam PATCH.
        ja_estava: IDs das páginas que já tinham a ligação (nada a fazer).
        desfeita: Se a operação foi de remover a ligação.
    """

    coluna: str
    bidirecional: bool
    escritas: list[str]
    ja_estava: list[str]
    desfeita: bool = False

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável, para a saída ``--json`` das bordas."""

        return {
            "coluna": self.coluna,
            "bidirecional": self.bidirecional,
            "acao": "desfeita" if self.desfeita else "ligada",
            "paginas_escritas": self.escritas,
            "paginas_ja_no_estado": self.ja_estava,
        }


def _relacao_da_coluna(
    page_id: str, coluna: str, *, cliente: NotionClient
) -> tuple[dict[str, Any], list[str]]:
    """Devolve a página inteira e os IDs já ligados naquela coluna.

    A página inteira (e não só as propriedades) porque quem chama também precisa
    do ``parent`` para descobrir o database — e assim basta uma leitura.

    Raises:
        ValueError: Se a coluna não existir na página ou não for de relação.
    """

    pagina = cliente.obter_pagina(page_id)
    props = pagina.get("properties", {})
    if coluna not in props:
        relacoes = sorted(
            nome for nome, info in props.items() if info.get("type") == "relation"
        )
        disponiveis = ", ".join(relacoes) or "(nenhuma)"
        raise ValueError(
            f"A página {page_id} não tem a coluna '{coluna}'. "
            f"Colunas de relação disponíveis: {disponiveis}."
        )
    tipo = props[coluna].get("type")
    if tipo != "relation":
        raise ValueError(
            f"A coluna '{coluna}' é do tipo '{tipo}', não 'relation'. "
            "Para editar uma coluna comum use 'editar-linha'."
        )
    ligados = [
        str(item.get("id"))
        for item in props[coluna].get("relation", [])
        if isinstance(item, dict) and item.get("id")
    ]
    return pagina, ligados


def _aplicar(
    page_id: str,
    coluna: str,
    ligados: list[str],
    alvo: str,
    *,
    desfazer: bool,
    cliente: NotionClient,
) -> bool:
    """Grava a ponta se ela ainda não estiver no estado desejado.

    Returns:
        ``True`` se houve escrita; ``False`` se já estava como se queria.
    """

    presente = any(_sem_hifens(item) == _sem_hifens(alvo) for item in ligados)
    if desfazer and not presente:
        return False
    if not desfazer and presente:
        return False

    if desfazer:
        novos = [item for item in ligados if _sem_hifens(item) != _sem_hifens(alvo)]
    else:
        novos = [*ligados, alvo]

    cliente.atualizar_pagina(
        page_id, {coluna: {"relation": [{"id": item} for item in novos]}}
    )
    return True


def relacionar(
    page_a: str,
    page_b: str,
    coluna: str,
    *,
    desfazer: bool = False,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Liga (ou desliga) duas linhas por uma coluna de relação, nos dois sentidos.

    A operação é **idempotente**: uma ponta que já está no estado desejado não
    recebe PATCH, então rodar de novo não duplica ligação nem gasta requisição.

    Quando a coluna é ``dual_property``, o Notion sincroniza e só ``page_a`` é
    escrita. Quando é ``single_property`` **e auto-referente**, a ponta ``page_b``
    é **relida** depois da primeira escrita: se o Notion já espelhou, nada é
    gravado; se não espelhou, a volta é gravada. É a releitura que torna o
    resultado simétrico sem depender do tipo declarado, que não é confiável
    para prever esse comportamento.

    Numa relação para **outro** database e de mão única não existe coluna de
    volta para escrever — forçar uma daria erro de coluna inexistente —, então o
    retorno registra só a ponta ``A``.

    Args:
        page_a: Uma das linhas.
        page_b: A outra linha.
        coluna: Nome da coluna de relação em ``page_a``.
        desfazer: Remove a ligação em vez de criá-la.
        cliente: Cliente Notion opcional (injeção para testes/uso alternativo).

    Returns:
        Um dicionário serializável com a coluna, se ela é bidirecional, quais
        páginas foram escritas e quais já estavam no estado pedido.

    Raises:
        ValueError: Se a coluna não existir ou não for de relação.
    """

    cliente = cliente or _cliente_padrao()
    pagina_a, ligados_a = _relacao_da_coluna(page_a, coluna, cliente=cliente)

    # A configuração dual/single mora no **schema do database**, não na linha —
    # a linha só traz os IDs já ligados. Por isso é preciso olhar o pai. Sem
    # database pai (página solta), o padrão conservador é tratar como mão única
    # auto-referente: escreve as duas pontas, que é o que não deixa buraco.
    database_alvo = ""
    bidirecional = False
    auto_referente = True
    pai = pagina_a.get("parent", {})
    if pai.get("type") == "database_id":
        descricao = descrever_database(cliente.get_database(pai["database_id"]))
        alvo = next((c for c in descricao.colunas if c.nome == coluna), None)
        if alvo is not None and alvo.relacao is not None:
            bidirecional = alvo.relacao.bidirecional
            auto_referente = alvo.relacao.auto_referente
            database_alvo = alvo.relacao.database_id

    escritas: list[str] = []
    ja_estava: list[str] = []

    def registrar(page_id: str, mudou: bool) -> None:
        (escritas if mudou else ja_estava).append(page_id)

    registrar(
        page_a,
        _aplicar(page_a, coluna, ligados_a, page_b, desfazer=desfazer, cliente=cliente),
    )

    # Bidirecional: o Notion espelha sozinho, escrever a volta é redundante.
    # Entre databases diferentes e de mão única: não há coluna de volta.
    if not bidirecional and auto_referente:
        _, ligados_b = _relacao_da_coluna(page_b, coluna, cliente=cliente)
        registrar(
            page_b,
            _aplicar(
                page_b, coluna, ligados_b, page_a, desfazer=desfazer, cliente=cliente
            ),
        )

    resultado = ResultadoRelacao(
        coluna=coluna,
        bidirecional=bidirecional,
        escritas=escritas,
        ja_estava=ja_estava,
        desfeita=desfazer,
    )
    dados = resultado.para_dict()
    if database_alvo:
        dados["database_alvo"] = database_alvo
    return dados
