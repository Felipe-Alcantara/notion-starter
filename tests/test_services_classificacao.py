from __future__ import annotations

import pytest

from notion_starter import properties
from notion_starter.services import (
    ResultadoClassificacao,
    aplicar_classificacoes,
    classificar_em_lote,
)


def _linha(page_id: str, titulo: str) -> dict:
    return {"id": page_id, "properties": {"Nome": titulo}}


class ClienteFake:
    def __init__(self) -> None:
        self.atualizacoes: list[tuple[str, dict]] = []

    def atualizar_pagina(self, page_id: str, propriedades: dict) -> dict:
        self.atualizacoes.append((page_id, propriedades))
        return {"id": page_id}


def test_classificar_em_lote_gera_distribuicao_e_preserva_sem_classificacao():
    linhas = [_linha("a", "bug"), _linha("b", "feature"), _linha("c", "sem dado")]

    resultado = classificar_em_lote(
        linhas,
        lambda linha: {"bug": "Correção", "feature": "Feature"}.get(
            linha["properties"]["Nome"]
        ),
    )

    assert isinstance(resultado, ResultadoClassificacao)
    assert resultado.distribuicao == {"Correção": 1, "Feature": 1}
    assert resultado.por_valor is resultado.distribuicao
    assert resultado.linhas_sem_classificacao == [linhas[2]]
    assert resultado.ids_sem_classificacao == ["c"]
    assert resultado.classificadas == 2
    assert resultado.pendentes == 1
    assert resultado.total == 3
    assert resultado.aplicadas == 0
    assert resultado.aplicado is False


def test_dry_run_nao_chama_aplicador():
    aplicadas: list[tuple[dict, str]] = []
    resultado = classificar_em_lote(
        [_linha("a", "x")],
        lambda _linha: "Tipo A",
        aplicador=lambda linha, valor: aplicadas.append((linha, valor)),
    )

    assert aplicadas == []
    assert resultado.aplicado is False


def test_aplicar_classificacoes_chama_callback_somente_para_classificadas():
    linhas = [_linha("a", "x"), _linha("b", "?")]
    aplicadas: list[tuple[str, str]] = []
    resultado = classificar_em_lote(
        linhas,
        lambda linha: None if linha["properties"]["Nome"] == "?" else "Tipo A",
    )

    quantidade = aplicar_classificacoes(
        resultado,
        aplicador=lambda linha, valor: aplicadas.append((linha["id"], valor)),
    )

    assert quantidade == 1
    assert aplicadas == [("a", "Tipo A")]
    assert resultado.aplicadas == 1
    assert resultado.aplicado is True


def test_aplicar_true_atualiza_cliente_com_select_por_padrao():
    cliente = ClienteFake()

    resultado = classificar_em_lote(
        [_linha("a", "x"), _linha("b", "y")],
        lambda linha: "A" if linha["id"] == "a" else None,
        aplicar=True,
        cliente=cliente,
        coluna="Tipo",
    )

    assert resultado.aplicadas == 1
    assert cliente.atualizacoes == [("a", {"Tipo": properties.select("A")})]


def test_aplicar_aceita_montador_de_outra_propriedade():
    cliente = ClienteFake()

    classificar_em_lote(
        [_linha("a", "x")],
        lambda _linha: "Em andamento",
        aplicar=True,
        cliente=cliente,
        coluna="Status",
        montar_propriedade=properties.status,
    )

    assert cliente.atualizacoes == [("a", {"Status": properties.status("Em andamento")})]


def test_aplicar_sem_destino_levanta_erro():
    resultado = classificar_em_lote([_linha("a", "x")], lambda _linha: "A")

    with pytest.raises(ValueError, match="aplicador ou cliente"):
        resultado.aplicar()


def test_cliente_exige_id_na_linha():
    resultado = classificar_em_lote([{"nome": "x"}], lambda _linha: "A")

    with pytest.raises(ValueError, match="precisa de 'id'"):
        resultado.aplicar(cliente=ClienteFake(), coluna="Tipo")


def test_valor_falso_e_contado_e_valor_nao_hashable_e_rejeitado():
    resultado = classificar_em_lote([_linha("a", "zero")], lambda _linha: 0)
    assert resultado.distribuicao == {0: 1}

    with pytest.raises(TypeError, match="valores classificáveis"):
        classificar_em_lote([_linha("a", "lista")], lambda _linha: ["A"])


def test_resultado_precisa_ser_do_tipo_esperado_para_aplicar():
    with pytest.raises(TypeError, match="ResultadoClassificacao"):
        aplicar_classificacoes(object(), aplicador=lambda _linha, _valor: None)
