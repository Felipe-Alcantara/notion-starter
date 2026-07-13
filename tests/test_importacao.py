from __future__ import annotations

import json

import pytest

from notion_starter.services.importacao import (
    EstadoImportacao,
    importar_com_estado,
)


def test_importa_e_registra_estado(tmp_path):
    caminho = tmp_path / "estado.json"
    estado = EstadoImportacao(caminho)
    itens = [{"nome": "a"}, {"nome": "b"}]

    resultado = importar_com_estado(
        itens,
        chave=lambda i: i["nome"],
        criar=lambda i: f"page-{i['nome']}",
        estado=estado,
    )

    assert resultado.criados == 2
    assert resultado.pulados == 0
    gravado = json.loads(caminho.read_text(encoding="utf-8"))
    assert gravado == {"a": "page-a", "b": "page-b"}


def test_reexecucao_pula_o_que_ja_existe(tmp_path):
    caminho = tmp_path / "estado.json"
    caminho.write_text(json.dumps({"a": "page-a"}), encoding="utf-8")
    estado = EstadoImportacao(caminho)
    criados: list[str] = []

    def criar(item):
        criados.append(item)
        return f"page-{item}"

    resultado = importar_com_estado(
        ["a", "b"], chave=lambda i: i, criar=criar, estado=estado
    )

    assert resultado.pulados == 1
    assert resultado.criados == 1
    assert criados == ["b"]
    assert estado.page_id("a") == "page-a"


def test_falha_nao_perde_progresso_nem_para_o_lote(tmp_path):
    estado = EstadoImportacao(tmp_path / "estado.json")

    def criar(item):
        if item == "b":
            raise RuntimeError("falha simulada")
        return f"page-{item}"

    resultado = importar_com_estado(
        ["a", "b", "c"], chave=lambda i: i, criar=criar, estado=estado
    )

    assert resultado.criados == 2
    assert resultado.erros == 1
    assert resultado.falhas == ["b"]
    assert "a" in estado and "c" in estado and "b" not in estado


def test_parar_no_erro_propaga_a_excecao(tmp_path):
    estado = EstadoImportacao(tmp_path / "estado.json")

    def criar(item):
        raise RuntimeError("falha")

    with pytest.raises(RuntimeError):
        importar_com_estado(
            ["a"], chave=lambda i: i, criar=criar, estado=estado, parar_no_erro=True
        )


def test_chave_vazia_levanta(tmp_path):
    estado = EstadoImportacao(tmp_path / "estado.json")
    with pytest.raises(ValueError):
        importar_com_estado([""], chave=lambda i: i, criar=lambda i: "x", estado=estado)


def test_estado_corrompido_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "estado.json"
    caminho.write_text("{corrompido", encoding="utf-8")
    with pytest.raises(ValueError, match="estado inválido"):
        EstadoImportacao(caminho)
