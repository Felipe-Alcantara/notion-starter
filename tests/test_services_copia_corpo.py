"""Copiar o corpo bloco a bloco sem cair nas recusas da API.

O double :class:`NotionFalso` imita o que foi medido em 2026-09-27 no workspace
real: a leitura traz campos opcionais como ``null`` (``paragraph.icon``) e itens
de *rich text* com ``plain_text``/``href``; a escrita recusa ``null`` onde
espera objeto, recusa mais de dois níveis de ``children`` e é **atômica** por
lote (um bloco inválido derruba todos). Tabela, colunas e coluna só nascem com
os filhos na mesma requisição.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from notion_starter.exceptions import (
    EscritaAbaixoDeDatabaseError,
    EscritaParcialError,
    NotionHTTPError,
)
from notion_starter.services.copia_corpo import copiar_corpo

ORIGEM = "pagina-origem"
DESTINO = "pagina-destino"
_EXIGEM_FILHOS = {"table", "column_list", "column"}
_GRAVAVEIS = {
    "paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item",
    "numbered_list_item", "to_do", "toggle", "quote", "callout", "code", "divider",
    "table", "table_row", "column_list", "column", "image", "bookmark", "synced_block",
}


def _texto(conteudo: str, **extra: Any) -> dict[str, Any]:
    """Item de rich text **como a leitura devolve**."""

    return {
        "type": "text",
        "text": {"content": conteudo, "link": None},
        "annotations": {"bold": False, "color": "default"},
        "plain_text": conteudo,
        "href": None,
        **extra,
    }


def _lido(tipo: str, dados: dict[str, Any], filhos: list[dict[str, Any]] | None = None):
    """Bloco **como a leitura devolve** (campos só-leitura e ``null`` incluídos)."""

    return {"type": tipo, tipo: dados, "_filhos": list(filhos or [])}


def _paragrafo(texto: str) -> dict[str, Any]:
    return _lido("paragraph", {"rich_text": [_texto(texto)], "color": "default", "icon": None})


def _sem_nulos_em(valor: Any, caminho: str = "") -> None:
    if isinstance(valor, dict):
        for chave, item in valor.items():
            if item is None and chave != "synced_from":
                raise NotionHTTPError(
                    400,
                    '{"object":"error","status":400,"code":"validation_error",'
                    f'"message":"body.{caminho}{chave} should be an object or `undefined`"}}',
                )
            _sem_nulos_em(item, f"{caminho}{chave}.")
    elif isinstance(valor, list):
        for item in valor:
            _sem_nulos_em(item, caminho)


class NotionFalso:
    """Árvore de blocos em memória com as regras de escrita da API."""

    def __init__(self, paginas: dict[str, list[dict[str, Any]]]) -> None:
        self._seq = 0
        self.filhos: dict[str, list[dict[str, Any]]] = {}
        self.escritas: list[tuple[str, int]] = []
        self.excluidos: list[str] = []
        self.falhar_na_escrita: int | None = None
        for pagina, blocos in paginas.items():
            self.filhos[pagina] = [self._guardar(b) for b in blocos]

    def _novo_id(self) -> str:
        self._seq += 1
        return f"b{self._seq}"

    def _guardar(self, lido: dict[str, Any]) -> dict[str, Any]:
        bloco = {k: v for k, v in lido.items() if k != "_filhos"}
        bloco["id"] = bloco.get("id") or self._novo_id()
        bloco["object"] = "block"
        self.filhos[bloco["id"]] = [self._guardar(f) for f in lido.get("_filhos", [])]
        bloco["has_children"] = bool(self.filhos[bloco["id"]])
        return bloco

    # -- leitura -----------------------------------------------------------------

    def ler_blocos(self, block_id: str, buscar_todos: bool = False, recursivo: bool = False):
        resultado = []
        for bloco in self.filhos.get(block_id, []):
            copia = {**bloco, "has_children": bool(self.filhos.get(bloco["id"]))}
            if recursivo and copia["has_children"] and copia["type"] != "child_database":
                copia["_filhos"] = self.ler_blocos(bloco["id"], buscar_todos, True)
            resultado.append(copia)
        return resultado

    # -- escrita -----------------------------------------------------------------

    def _validar(self, bloco: dict[str, Any], nivel: int) -> None:
        tipo = bloco["type"]
        if tipo not in _GRAVAVEIS:
            raise NotionHTTPError(400, f'{{"message":"tipo {tipo} não gravável"}}')
        corpo = bloco[tipo]
        for item in corpo.get("rich_text", []):
            if "plain_text" in item or "href" in item:
                raise NotionHTTPError(400, '{"message":"rich_text com campo de leitura"}')
        filhos = corpo.get("children", [])
        if tipo in _EXIGEM_FILHOS and not filhos:
            raise NotionHTTPError(400, f'{{"message":"{tipo} exige children"}}')
        if filhos and nivel >= 2:
            raise NotionHTTPError(400, '{"message":"aninhamento acima de 2 níveis"}')
        if len(filhos) > 100:
            raise NotionHTTPError(400, '{"message":"mais de 100 children"}')
        for filho in filhos:
            self._validar(filho, nivel + 1)

    def _criar(self, pai_id: str, bloco: dict[str, Any]) -> dict[str, Any]:
        tipo = bloco["type"]
        corpo = {k: v for k, v in bloco[tipo].items() if k != "children"}
        novo = {"id": self._novo_id(), "object": "block", "type": tipo, tipo: corpo}
        self.filhos[novo["id"]] = []
        for filho in bloco[tipo].get("children", []):
            self.filhos[novo["id"]].append(self._criar(novo["id"], filho))
        return novo

    def anexar_blocos(self, block_id: str, blocos: list[dict[str, Any]], **_: Any):
        if self.falhar_na_escrita is not None and len(self.escritas) + 1 == self.falhar_na_escrita:
            self.escritas.append((block_id, len(blocos)))
            raise NotionHTTPError(500, '{"message":"falha simulada"}')
        self.escritas.append((block_id, len(blocos)))
        if len(blocos) > 100:
            raise NotionHTTPError(400, '{"message":"mais de 100 blocos"}')
        # Lote atômico: valida tudo antes de criar qualquer um.
        _sem_nulos_em(blocos)
        for bloco in blocos:
            self._validar(bloco, 0)
        criados = [self._criar(block_id, bloco) for bloco in blocos]
        self.filhos.setdefault(block_id, []).extend(criados)
        return {"results": criados}

    def excluir_bloco(self, block_id: str) -> dict[str, Any]:
        self.excluidos.append(block_id)
        for filhos in self.filhos.values():
            filhos[:] = [b for b in filhos if b["id"] != block_id]
        return {"id": block_id, "in_trash": True}

    # -- conferência -------------------------------------------------------------

    def contagem(self, pagina: str) -> Counter[str]:
        total: Counter[str] = Counter()

        def descer(bloco_id: str) -> None:
            for bloco in self.filhos.get(bloco_id, []):
                total[bloco["type"]] += 1
                descer(bloco["id"])

        descer(pagina)
        return total


def _pagina_medida() -> list[dict[str, Any]]:
    """O formato da página copiada na medição: tabela de 9 linhas, to_do, quote…"""

    linhas = [
        _lido("table_row", {"cells": [[_texto(f"l{i}c1")], [_texto(f"l{i}c2")]]})
        for i in range(9)
    ]
    return [
        _lido("heading_2", {"rich_text": [_texto("Estrutura")], "is_toggleable": False,
                            "color": "default"}),
        _paragrafo("Introdução"),
        _lido("table", {"table_width": 2, "has_column_header": True,
                        "has_row_header": False}, linhas),
        _lido("to_do", {"rich_text": [_texto("revisar")], "checked": True, "color": "default"}),
        _lido("quote", {"rich_text": [_texto("citação")], "color": "default"}),
        _lido("bulleted_list_item", {"rich_text": [_texto("item")], "color": "default"},
              [_lido("bulleted_list_item", {"rich_text": [_texto("sub")], "color": "default"})]),
        _lido("divider", {}),
        _lido("code", {"rich_text": [_texto("print(1)")], "language": "python", "caption": []}),
    ]


def test_copia_a_pagina_medida_numa_escrita_e_confere_a_contagem():
    notion = NotionFalso({ORIGEM: _pagina_medida(), DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, conferir=True, cliente=notion)

    assert notion.contagem(DESTINO) == notion.contagem(ORIGEM)
    assert resultado.por_tipo["table_row"] == 9
    assert resultado.blocos_de_topo == 8
    assert resultado.escritas == 1
    assert resultado.conferencia["confere"] is True
    assert resultado.ignorados == ()
    to_do = next(b for b in notion.filhos[DESTINO] if b["type"] == "to_do")
    assert to_do["to_do"]["checked"] is True


def test_aninhamento_fundo_e_anexado_depois_no_bloco_criado():
    fundo = _lido("toggle", {"rich_text": [_texto("n1")]}, [
        _lido("toggle", {"rich_text": [_texto("n2")]}, [
            _lido("toggle", {"rich_text": [_texto("n3")]}, [
                _lido("toggle", {"rich_text": [_texto("n4")]}, [_paragrafo("n5")]),
            ]),
        ]),
    ])
    notion = NotionFalso({ORIGEM: [fundo, _paragrafo("fim")], DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert notion.contagem(DESTINO) == Counter({"toggle": 4, "paragraph": 2})
    assert resultado.escritas >= 2
    assert [b["type"] for b in notion.filhos[DESTINO]] == ["toggle", "paragraph"]


def test_colunas_nascem_com_os_filhos_e_coluna_sem_copiavel_ganha_paragrafo():
    colunas = _lido("column_list", {}, [
        _lido("column", {}, [_paragrafo("esquerda")]),
        _lido("column", {}, [_lido("child_page", {"title": "Sub"})]),
    ])
    notion = NotionFalso({ORIGEM: [colunas], DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert notion.contagem(DESTINO) == Counter({"column_list": 1, "column": 2, "paragraph": 2})
    assert [b.tipo for b in resultado.ignorados] == ["child_page"]


def test_ignora_o_que_nao_se_recria_e_copia_imagem_externa():
    blocos = [
        _lido("child_page", {"title": "Filha"}),
        _lido("child_database", {"title": "Tabela"}),
        _lido("image", {"type": "file", "file": {"url": "https://s3/x.png",
                                                 "expiry_time": "2026-09-27T12:00:00Z"},
                        "caption": []}),
        _lido("image", {"type": "external", "external": {"url": "https://exemplo.org/a.png"},
                        "caption": []}),
        _lido("link_preview", {"url": "https://github.com/x"}),
    ]
    notion = NotionFalso({ORIGEM: blocos, DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert [b.tipo for b in resultado.ignorados] == [
        "child_page", "child_database", "image", "link_preview",
    ]
    assert "expira" in resultado.ignorados[2].motivo
    assert notion.contagem(DESTINO) == Counter({"image": 1})


def test_mencao_nao_regravavel_vira_texto_e_e_relatada():
    mencao = {
        "type": "mention",
        "mention": {"type": "link_preview", "link_preview": {"url": "https://github.com/x"}},
        "annotations": {"bold": True},
        "plain_text": "github.com/x",
        "href": "https://github.com/x",
    }
    bloco = _lido("paragraph", {"rich_text": [_texto("veja "), mencao], "icon": None})
    bloco["id"] = "com-mencao"
    notion = NotionFalso({ORIGEM: [bloco], DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert resultado.degradados == ("com-mencao",)
    itens = notion.filhos[DESTINO][0]["paragraph"]["rich_text"]
    assert itens[1]["text"] == {"content": "github.com/x", "link": {"url": "https://github.com/x"}}
    assert itens[1]["annotations"] == {"bold": True}


def test_so_se_vazio_nao_escreve_em_destino_com_conteudo():
    notion = NotionFalso({ORIGEM: [_paragrafo("a")], DESTINO: [_paragrafo("já tem")]})

    resultado = copiar_corpo(ORIGEM, DESTINO, so_se_vazio=True, cliente=notion)

    assert resultado.pulado is True
    assert notion.escritas == []


def test_destino_com_database_recusa_sem_a_liberacao():
    notion = NotionFalso({
        ORIGEM: [_paragrafo("a")],
        DESTINO: [_lido("child_database", {"title": "Linhas"})],
    })

    with pytest.raises(EscritaAbaixoDeDatabaseError):
        copiar_corpo(ORIGEM, DESTINO, cliente=notion)
    assert notion.escritas == []

    copiar_corpo(ORIGEM, DESTINO, mesmo_com_database=True, cliente=notion)
    assert notion.contagem(DESTINO)["paragraph"] == 1


def test_falha_no_segundo_lote_desfaz_o_primeiro():
    notion = NotionFalso({ORIGEM: [_paragrafo(f"p{i}") for i in range(150)], DESTINO: []})
    notion.falhar_na_escrita = 2

    with pytest.raises(EscritaParcialError) as erro:
        copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert len(erro.value.desfeitos) == 100
    assert erro.value.criados == []
    assert erro.value.lote_incerto is True  # 5xx: o lote pode ter sido gravado
    assert notion.filhos[DESTINO] == []


def test_tabela_com_mais_de_100_linhas_completa_depois():
    linhas = [_lido("table_row", {"cells": [[_texto(str(i))]]}) for i in range(120)]
    tabela = _lido("table", {"table_width": 1, "has_column_header": False,
                             "has_row_header": False}, linhas)
    notion = NotionFalso({ORIGEM: [tabela], DESTINO: []})

    copiar_corpo(ORIGEM, DESTINO, cliente=notion)

    assert notion.contagem(DESTINO) == Counter({"table": 1, "table_row": 120})


def test_dry_run_planeja_sem_escrever():
    notion = NotionFalso({ORIGEM: _pagina_medida(), DESTINO: []})

    resultado = copiar_corpo(ORIGEM, DESTINO, dry_run=True, cliente=notion)

    assert resultado.dry_run is True
    assert resultado.blocos_total == sum(notion.contagem(ORIGEM).values())
    assert notion.escritas == []


def test_origem_igual_ao_destino_recusa():
    notion = NotionFalso({ORIGEM: [_paragrafo("a")]})

    with pytest.raises(ValueError):
        copiar_corpo(ORIGEM, ORIGEM.upper(), cliente=notion)
