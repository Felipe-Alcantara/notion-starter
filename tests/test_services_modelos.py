"""Modelos nativos: listar pela API e preencher os vazios a partir de um manifesto.

Fatos medidos em 2026-09-27 (versão 2025-09-03): ``GET
/data_sources/{id}/templates`` devolve ``{"templates": [{"id", "name",
"is_default"}], "has_more", "next_cursor"}``; um modelo sem título aparece como
``"New page"``; a API não cria modelo, mas escrever propriedades e corpo num
modelo existente funciona.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import responses

from notion_starter import NotionClient
from notion_starter import properties as prop
from notion_starter.constants import NOTION_BASE_URL, NOTION_DATA_SOURCE_VERSION
from notion_starter.services.modelos import (
    ManifestoInvalidoError,
    carregar_manifesto,
    listar_modelos,
    preencher_modelos,
)

DATABASE = "db-ideias"
FONTE = "ds-ideias"


# -- cliente ---------------------------------------------------------------------


@responses.activate
def test_listar_modelos_percorre_a_paginacao_na_versao_de_data_source():
    url = f"{NOTION_BASE_URL}/data_sources/{FONTE}/templates"
    responses.add(
        responses.GET,
        url,
        json={
            "templates": [{"id": "m1", "name": "New page", "is_default": True}],
            "has_more": True,
            "next_cursor": "c2",
        },
    )
    responses.add(
        responses.GET,
        url,
        json={"templates": [{"id": "m2", "name": "Resenha", "is_default": False}],
              "has_more": False, "next_cursor": None},
    )

    modelos = NotionClient(token="ntn_teste", max_retries=0).listar_modelos(FONTE)

    assert [m["id"] for m in modelos] == ["m1", "m2"]
    assert responses.calls[0].request.headers["Notion-Version"] == NOTION_DATA_SOURCE_VERSION
    assert "start_cursor=c2" in responses.calls[1].request.url


# -- valor_de_texto --------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo,texto,esperado",
    [
        ("select", "Ideia", {"select": {"name": "Ideia"}}),
        ("select", "", {"select": None}),
        ("multi_select", "IA, Games", {"multi_select": [{"name": "IA"}, {"name": "Games"}]}),
        ("checkbox", "sim", {"checkbox": True}),
        ("number", "3", {"number": 3}),
        ("number", "2.5", {"number": 2.5}),
        ("date", "2026-09-01..2026-09-03",
         {"date": {"start": "2026-09-01", "end": "2026-09-03"}}),
        ("url", "", {"url": None}),
        ("relation", "a, b", {"relation": [{"id": "a"}, {"id": "b"}]}),
    ],
)
def test_valor_de_texto_segue_a_regra_do_editar_linha(tipo, texto, esperado):
    assert prop.valor_de_texto(tipo, texto) == esperado


@pytest.mark.parametrize("tipo,texto", [("formula", "x"), ("status", " "), ("files", "a")])
def test_valor_de_texto_recusa_o_que_nao_se_escreve(tipo, texto):
    with pytest.raises(ValueError):
        prop.valor_de_texto(tipo, texto)


# -- manifesto -------------------------------------------------------------------


def _manifesto(pasta: Path, itens: Any) -> Path:
    caminho = pasta / "modelos.json"
    caminho.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_manifesto_resolve_arquivo_relativo_a_pasta(tmp_path):
    (tmp_path / "roteiro.md").write_text("# Roteiro", encoding="utf-8")
    caminho = _manifesto(tmp_path, [
        {"nome": "🎬 Roteiro", "arquivo": "roteiro.md", "propriedades": {"Etapa": "Ideia"}},
        {"nome": "🧩 Artigo", "copiar_de": "pagina-modelo"},
    ])

    itens = carregar_manifesto(caminho)

    assert itens[0].arquivo == (tmp_path / "roteiro.md").resolve()
    assert itens[0].propriedades == {"Etapa": "Ideia"}
    assert itens[1].copiar_de == "pagina-modelo" and itens[1].tem_corpo


def test_manifesto_invalido_lista_todos_os_problemas(tmp_path):
    caminho = _manifesto(tmp_path, [
        {"arquivo": "x.md"},
        {"nome": "A", "arquivo": "falta.md"},
        {"nome": "B", "arquivo": "b.md", "copiar_de": "p"},
        {"nome": "a"},
    ])

    with pytest.raises(ManifestoInvalidoError) as erro:
        carregar_manifesto(caminho)

    texto = " | ".join(erro.value.problemas)
    assert "'nome' é obrigatório" in texto
    assert "arquivo não encontrado" in texto
    assert "não os dois" in texto
    assert "nome repetido" in texto


# -- preenchimento ---------------------------------------------------------------


class NotionModelos:
    """Uma fonte com modelos (páginas) e uma página de origem para ``copiar_de``."""

    def __init__(self, modelos: list[tuple[str, str, int]]) -> None:
        # (id, nome, quantidade de blocos no corpo)
        self.nomes = {mid: nome for mid, nome, _ in modelos}
        self.ordem = [mid for mid, _, _ in modelos]
        self.corpos: dict[str, list[dict[str, Any]]] = {
            mid: [{"id": f"{mid}-b{i}", "type": "paragraph", "paragraph": {"rich_text": []}}
                  for i in range(n)]
            for mid, _, n in modelos
        }
        self.corpos["pagina-modelo"] = [
            {"id": "o1", "type": "to_do", "has_children": False,
             "to_do": {"rich_text": [], "checked": False, "color": None}},
        ]
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.anexos: list[str] = []
        self._seq = 0

    def resolver_data_source(self, database_id: str) -> str:
        assert database_id == DATABASE
        return FONTE

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        return {
            "id": FONTE,
            "properties": {
                "Nome": {"type": "title"},
                "Etapa": {"type": "select"},
                "Formato": {"type": "select"},
                "Criado em": {"type": "created_time"},
            },
        }

    def listar_modelos(self, data_source_id: str) -> list[dict[str, Any]]:
        return [{"id": m, "name": self.nomes[m], "is_default": i == 0}
                for i, m in enumerate(self.ordem)]

    def ler_blocos(self, block_id: str, buscar_todos: bool = False, recursivo: bool = False):
        return list(self.corpos.get(block_id, []))

    def atualizar_pagina(self, page_id: str, propriedades: dict[str, Any]) -> dict[str, Any]:
        self.patches.append((page_id, propriedades))
        titulo = propriedades.get("Nome", {}).get("title")
        if titulo:
            self.nomes[page_id] = "".join(t["text"]["content"] for t in titulo)
        return {"id": page_id}

    def anexar_blocos(self, block_id: str, blocos: list[dict[str, Any]], **_: Any):
        self.anexos.append(block_id)
        criados = []
        for bloco in blocos:
            self._seq += 1
            criados.append({"id": f"n{self._seq}", **bloco})
        self.corpos.setdefault(block_id, []).extend(criados)
        return {"results": criados}


def _itens(tmp_path: Path) -> list[Any]:
    (tmp_path / "roteiro.md").write_text("# Roteiro\n\n- gancho", encoding="utf-8")
    return carregar_manifesto(_manifesto(tmp_path, [
        {"nome": "📚 Resenha", "arquivo": "roteiro.md"},
        {"nome": "🎬 Roteiro", "arquivo": "roteiro.md",
         "propriedades": {"Etapa": "Ideia", "Formato": "Vídeo"}},
        {"nome": "🧩 Artigo", "copiar_de": "pagina-modelo"},
        {"nome": "💡 Ideia rápida", "arquivo": "roteiro.md"},
    ]))


def test_preenche_os_vazios_na_ordem_e_pula_o_que_ja_existe(tmp_path):
    notion = NotionModelos([
        ("m1", "New page", 0),
        ("m2", "📚 Resenha", 3),
        ("m3", "Meu modelo", 0),  # nome próprio: nunca reaproveitado
        ("m4", "New page", 0),
    ])

    resultado = preencher_modelos(DATABASE, _itens(tmp_path), cliente=notion)

    acoes = {a.nome: (a.acao, a.modelo_id) for a in resultado.acoes}
    assert acoes == {
        "📚 Resenha": ("ja_existia", "m2"),
        "🎬 Roteiro": ("preenchido", "m1"),
        "🧩 Artigo": ("preenchido", "m4"),
        "💡 Ideia rápida": ("sem_modelo_vazio", None),
    }
    assert resultado.faltam == 1
    patch_roteiro = dict(notion.patches)["m1"]
    assert patch_roteiro["Etapa"] == {"select": {"name": "Ideia"}}
    assert notion.nomes["m1"] == "🎬 Roteiro"
    assert notion.corpos["m1"] and notion.corpos["m4"][0]["type"] == "to_do"
    assert "m3" not in notion.anexos


def test_segunda_rodada_nao_escreve_nada(tmp_path):
    notion = NotionModelos([("m1", "New page", 0), ("m2", "New page", 0),
                            ("m3", "New page", 0), ("m4", "New page", 0)])
    itens = _itens(tmp_path)
    preencher_modelos(DATABASE, itens, cliente=notion)
    patches, anexos = len(notion.patches), len(notion.anexos)

    resultado = preencher_modelos(DATABASE, itens, cliente=notion)

    assert {a.acao for a in resultado.acoes} == {"ja_existia"}
    assert (len(notion.patches), len(notion.anexos)) == (patches, anexos)


def test_modelo_com_nome_e_sem_corpo_e_completado(tmp_path):
    notion = NotionModelos([("m1", "🎬 Roteiro", 0)])

    resultado = preencher_modelos(DATABASE, _itens(tmp_path)[1:2], cliente=notion)

    assert resultado.acoes[0].acao == "completado"
    assert notion.corpos["m1"]


def test_coluna_inexistente_ou_calculada_recusa_antes_de_escrever(tmp_path):
    (tmp_path / "a.md").write_text("oi", encoding="utf-8")
    itens = carregar_manifesto(_manifesto(tmp_path, [
        {"nome": "A", "arquivo": "a.md", "propriedades": {"Temas": "IA"}},
        {"nome": "B", "arquivo": "a.md", "propriedades": {"Criado em": "2026-01-01"}},
    ]))
    notion = NotionModelos([("m1", "New page", 0), ("m2", "New page", 0)])

    with pytest.raises(ManifestoInvalidoError) as erro:
        preencher_modelos(DATABASE, itens, cliente=notion)

    assert len(erro.value.problemas) == 2
    assert notion.patches == [] and notion.anexos == []


def test_dry_run_planeja_sem_escrever(tmp_path):
    notion = NotionModelos([("m1", "New page", 0)])

    resultado = preencher_modelos(DATABASE, _itens(tmp_path), dry_run=True, cliente=notion)

    assert resultado.dry_run
    assert [a.acao for a in resultado.acoes].count("preenchido") == 1
    assert notion.patches == [] and notion.anexos == []


def test_listar_modelos_do_servico_resolve_a_fonte():
    notion = NotionModelos([("m1", "New page", 0), ("m2", "Resenha", 1)])

    modelos = listar_modelos(DATABASE, cliente=notion)

    assert [m.para_dict() for m in modelos] == [
        {"id": "m1", "nome": "New page", "padrao": True},
        {"id": "m2", "nome": "Resenha", "padrao": False},
    ]
