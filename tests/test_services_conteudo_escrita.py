"""Escrever e limpar o corpo de uma página sem zerá-la por acidente.

Medido no workspace real: ``escrever --substituir`` apagava o corpo inteiro e só
depois descobria que o Notion recusava o conteúdo novo (tabela com 101 linhas,
parágrafo com 119 trechos, lote com mais de 1000 elementos) — a página ficava
vazia. A limpeza também só olhava o tipo do bloco de topo: ``equation``,
``link_to_page`` e um toggle com database dentro iam para a lixeira.

A :class:`ArvoreFalsa` imita a API: filhos por pai, ``position``, ``results``
com os irmãos seguintes quando há posição, e falhas configuráveis.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.exceptions import (
    ConteudoInvalidoError,
    EscritaAbaixoDeDatabaseError,
    EscritaParcialError,
    LimpezaIncompletaError,
    NotionConnectionError,
    NotionHTTPError,
)
from notion_starter.services import conteudo as svc


class ArvoreFalsa:
    def __init__(self, filhos: dict[str, list[dict[str, Any]]]) -> None:
        self.filhos = {pai: [dict(b) for b in lista] for pai, lista in filhos.items()}
        self.chamadas: list[tuple[Any, ...]] = []
        self.apagados: list[str] = []
        self.falhar_anexo_numero: int | None = None
        self.erro_anexo: Exception = NotionHTTPError(400, "body failed validation")
        self.falhar_exclusao_de: set[str] = set()
        self._contador = 0
        self._anexos = 0

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler", block_id))
        return [dict(b) for b in self.filhos.get(block_id, [])]

    def ids(self, pai: str = "pg") -> list[str]:
        return [b["id"] for b in self.filhos.get(pai, [])]

    def anexar_blocos(self, block_id, blocos, *, apos_bloco_id=None, no_inicio=False):
        self._anexos += 1
        self.chamadas.append(("anexar", block_id, len(blocos), apos_bloco_id, no_inicio))
        if self.falhar_anexo_numero == self._anexos:
            raise self.erro_anexo
        novos = []
        for bloco in blocos:
            self._contador += 1
            novos.append({"id": f"n{self._contador}", "type": bloco["type"]})
        irmaos = self.filhos.setdefault(block_id, [])
        if no_inicio:
            posicao = 0
        elif apos_bloco_id:
            posicao = [b["id"] for b in irmaos].index(apos_bloco_id) + 1
        else:
            posicao = len(irmaos)
        irmaos[posicao:posicao] = novos
        seguintes = irmaos[posicao + len(novos) :] if (no_inicio or apos_bloco_id) else []
        return {"results": [*novos, *seguintes]}

    def excluir_bloco(self, block_id):
        self.chamadas.append(("excluir", block_id))
        if block_id in self.falhar_exclusao_de:
            raise NotionHTTPError(502, "bad gateway")
        self.apagados.append(block_id)
        for pai, lista in self.filhos.items():
            self.filhos[pai] = [b for b in lista if b["id"] != block_id]
        return {"id": block_id, "in_trash": True}

    def restaurar_bloco(self, block_id):
        if block_id == "sumido":
            raise NotionHTTPError(404, "not found")
        self.chamadas.append(("restaurar", block_id))
        return {"id": block_id, "in_trash": False}

    def etapas(self) -> list[str]:
        return [c[0] for c in self.chamadas if c[0] != "ler"]


def _p(id_: str, **extra) -> dict[str, Any]:
    return {"id": id_, "type": "paragraph", "paragraph": {"rich_text": []}, **extra}


def _pagina_com_texto() -> ArvoreFalsa:
    return ArvoreFalsa({"pg": [_p("velho-1"), _p("velho-2"), _p("velho-3")]})


# -- validação antes de apagar ----------------------------------------------------------


def test_trechos_demais_num_paragrafo_nao_apagam_a_pagina():
    """Medido: 119 trechos → 400 depois do DELETE, página com 0 blocos."""

    arvore = _pagina_com_texto()
    markdown = " ".join(f"`c{i}`" for i in range(60))

    with pytest.raises(ConteudoInvalidoError, match="119 trechos"):
        svc.escrever_conteudo("pg", markdown, substituir=True, cliente=arvore)

    assert arvore.etapas() == []
    assert arvore.ids() == ["velho-1", "velho-2", "velho-3"]


def test_tabela_com_101_linhas_e_recusada_antes_de_apagar():
    arvore = _pagina_com_texto()
    linhas = ["| a | b |", "| --- | --- |"] + [f"| {i} | x |" for i in range(101)]

    with pytest.raises(ConteudoInvalidoError, match="102 linhas"):
        svc.escrever_conteudo("pg", "\n".join(linhas), substituir=True, cliente=arvore)

    assert arvore.apagados == []







def test_criar_subpagina_valida_antes_de_criar():
    class Cliente:
        def __init__(self):
            self.criadas = []

        def criar_subpagina(self, *a, **k):
            self.criadas.append(a)
            return {"id": "sub"}

    cliente = Cliente()
    linhas = ["| a | b |", "| --- | --- |"] + [f"| {i} | x |" for i in range(101)]
    with pytest.raises(ConteudoInvalidoError):
        svc.criar_subpagina("pai", "T", markdown="\n".join(linhas), cliente=cliente)
    assert cliente.criadas == []


# -- escrever antes de apagar --------------------------------------------------------------


def test_substituir_anexa_o_novo_antes_de_apagar_o_antigo():
    arvore = _pagina_com_texto()

    resultado = svc.escrever_conteudo("pg", "novo", substituir=True, cliente=arvore)

    assert arvore.etapas() == ["anexar", "excluir", "excluir", "excluir"]
    assert arvore.ids() == ["n1"]
    assert resultado.criados == [svc.BlocoCriado(id="n1", tipo="paragraph")]
    assert resultado.limpeza.apagados_ids == [
        ("velho-1", "paragraph"),
        ("velho-2", "paragraph"),
        ("velho-3", "paragraph"),
    ]


def test_substituir_com_anexo_recusado_deixa_a_pagina_intacta():
    arvore = _pagina_com_texto()
    arvore.falhar_anexo_numero = 1

    with pytest.raises(EscritaParcialError) as erro:
        svc.escrever_conteudo("pg", "novo", substituir=True, cliente=arvore)

    assert arvore.apagados == []
    assert arvore.ids() == ["velho-1", "velho-2", "velho-3"]
    assert "Nada do conteúdo antigo foi apagado" in str(erro.value)
    assert isinstance(erro.value, RuntimeError)  # compatível com o tipo antigo


def test_segundo_lote_falha_e_o_primeiro_e_desfeito():
    """Sem desfazer, repetir o comando duplicava os 100 primeiros blocos."""

    arvore = _pagina_com_texto()
    arvore.falhar_anexo_numero = 2
    markdown = "\n\n".join(f"linha {i}" for i in range(150))

    with pytest.raises(EscritaParcialError) as erro:
        svc.escrever_conteudo("pg", markdown, substituir=True, cliente=arvore)

    assert arvore.ids() == ["velho-1", "velho-2", "velho-3"]
    assert len(erro.value.desfeitos) == 100
    assert erro.value.criados == []
    assert erro.value.lote_incerto is False


def test_falha_de_rede_num_lote_avisa_que_ele_pode_ter_sido_gravado():
    arvore = ArvoreFalsa({"pg": []})
    arvore.falhar_anexo_numero = 1
    arvore.erro_anexo = NotionConnectionError("timeout")

    with pytest.raises(EscritaParcialError) as erro:
        svc.escrever_conteudo("pg", "texto", cliente=arvore)

    assert erro.value.lote_incerto is True
    assert "blocos pg" in str(erro.value)


def test_limpeza_que_falha_depois_de_escrever_lista_o_que_ficou():
    arvore = _pagina_com_texto()
    arvore.falhar_exclusao_de = {"velho-2"}

    with pytest.raises(LimpezaIncompletaError) as erro:
        svc.escrever_conteudo("pg", "novo", substituir=True, cliente=arvore)

    assert erro.value.apagados == [("velho-1", "paragraph")]
    assert erro.value.pendentes == [("velho-2", "paragraph"), ("velho-3", "paragraph")]
    assert erro.value.blocos_novos == ["n1"]


def test_limpar_que_falha_no_meio_diz_o_que_apagou():
    arvore = ArvoreFalsa({"pg": [_p("A"), _p("B"), _p("C"), _p("D")]})
    arvore.falhar_exclusao_de = {"C"}

    with pytest.raises(LimpezaIncompletaError) as erro:
        svc.limpar_conteudo("pg", cliente=arvore)

    assert [bloco_id for bloco_id, _ in erro.value.apagados] == ["A", "B"]
    assert [bloco_id for bloco_id, _ in erro.value.pendentes] == ["C", "D"]
    assert "restaurar_bloco" in str(erro.value)


def test_restaurar_blocos_devolve_o_que_voltou_e_o_que_falhou():
    arvore = ArvoreFalsa({"pg": []})

    resultado = svc.restaurar_blocos(["A", "sumido", "B"], cliente=arvore)

    assert resultado.restaurados == ["A", "B"]
    assert resultado.falhas[0][0] == "sumido"


# -- posição e IDs criados -----------------------------------------------------------


def test_apos_bloco_encadeia_os_lotes_no_ultimo_criado():
    """Com posição a API devolve também os irmãos: o 'último' é o do lote, não da página."""

    arvore = ArvoreFalsa({"pg": [_p("A"), _p("B")]})
    markdown = "\n\n".join(f"linha {i}" for i in range(150))

    resultado = svc.escrever_conteudo("pg", markdown, apos_bloco_id="A", cliente=arvore)

    anexos = [c for c in arvore.chamadas if c[0] == "anexar"]
    assert anexos[0][3] == "A"
    assert anexos[1][3] == "n100"
    assert arvore.ids() == ["A", *[f"n{i}" for i in range(1, 151)], "B"]
    assert len(resultado.criados) == 150


def test_inicio_poe_o_primeiro_lote_no_topo_e_encadeia_o_resto():
    arvore = ArvoreFalsa({"pg": [_p("A")]})
    markdown = "\n\n".join(f"linha {i}" for i in range(120))

    svc.escrever_conteudo("pg", markdown, inicio=True, cliente=arvore)

    anexos = [c for c in arvore.chamadas if c[0] == "anexar"]
    assert anexos[0][4] is True
    assert anexos[1][3] == "n100"
    assert arvore.ids()[0] == "n1" and arvore.ids()[-1] == "A"


@pytest.mark.parametrize("posicao", [{"apos_bloco_id": "A"}, {"inicio": True}])
def test_posicao_nao_combina_com_substituir(posicao):
    arvore = _pagina_com_texto()
    with pytest.raises(ValueError, match="substituir"):
        svc.escrever_conteudo("pg", "x", substituir=True, cliente=arvore, **posicao)
    assert arvore.chamadas == []


def test_criados_nao_mudam_a_comparacao_com_int():
    arvore = ArvoreFalsa({"pg": []})
    resultado = svc.escrever_conteudo("pg", "a\n\nb", cliente=arvore)
    assert resultado == 2
    assert resultado == svc.ResultadoEscrita(anexados=2)


# -- o que a limpeza apaga: lista branca e subárvore ----------------------------------------


@pytest.mark.parametrize(
    "bloco",
    [
        {"type": "equation", "equation": {"expression": "e=mc^2"}},
        {"type": "link_to_page", "link_to_page": {"type": "page_id", "page_id": "x"}},
        {"type": "table_of_contents", "table_of_contents": {}},
        {"type": "breadcrumb", "breadcrumb": {}},
        {"type": "unsupported", "unsupported": {}},
        {"type": "tab", "tab": {}},
        {"type": "template", "template": {"rich_text": []}},
        {"type": "toggle", "toggle": {"rich_text": []}},
        {"type": "callout", "callout": {"rich_text": []}},
        {"type": "heading_4", "heading_4": {"rich_text": []}},
        {"type": "heading_2", "heading_2": {"rich_text": [], "is_toggleable": True}},
    ],
    ids=lambda b: b["type"] + ("-toggle" if b.get("heading_2", {}).get("is_toggleable") else ""),
)
def test_limpar_preserva_o_que_o_markdown_nao_recria(bloco):
    arvore = ArvoreFalsa({"pg": [_p("texto"), {"id": "X", **bloco}]})

    resultado = svc.limpar_conteudo("pg", cliente=arvore)

    assert arvore.apagados == ["texto"]
    assert resultado.preservados == [("X", bloco["type"])]
    assert "X" in resultado.motivos


def test_toggle_preservado_avisa_do_risco_de_duplicar():
    arvore = ArvoreFalsa({"pg": [{"id": "T", "type": "toggle", "toggle": {"rich_text": []}}]})

    resultado = svc.limpar_conteudo("pg", cliente=arvore)

    assert "duplicado" in resultado.motivos["T"]


def test_item_de_lista_com_imagem_dentro_e_preservado_inteiro():
    arvore = ArvoreFalsa(
        {
            "pg": [
                {"id": "L", "type": "bulleted_list_item", "has_children": True,
                 "bulleted_list_item": {"rich_text": []}},
            ],
            "L": [{"id": "img", "type": "image", "image": {}}],
        }
    )

    resultado = svc.escrever_conteudo(
        "pg", "novo", substituir=True, mesmo_com_database=True, cliente=arvore
    )

    assert "L" not in arvore.apagados
    assert resultado.preservados == [("L", "bulleted_list_item")]
    assert "contém 'image'" in resultado.limpeza.motivos["L"]


def test_lista_aninhada_so_de_texto_continua_sendo_apagada():
    arvore = ArvoreFalsa(
        {
            "pg": [{"id": "L", "type": "bulleted_list_item", "has_children": True,
                    "bulleted_list_item": {"rich_text": []}}],
            "L": [{"id": "sub", "type": "bulleted_list_item",
                   "bulleted_list_item": {"rich_text": []}}],
        }
    )

    svc.limpar_conteudo("pg", cliente=arvore)

    assert arvore.apagados == ["L"]


def test_database_dentro_de_toggle_dispara_a_recusa():
    arvore = ArvoreFalsa(
        {
            "pg": [_p("A"), {"id": "T", "type": "toggle", "has_children": True,
                             "toggle": {"rich_text": []}}],
            "T": [{"id": "db", "type": "child_database",
                   "child_database": {"title": "Clientes"}}],
        }
    )

    with pytest.raises(EscritaAbaixoDeDatabaseError) as erro:
        svc.escrever_conteudo("pg", "# nota", substituir=True, cliente=arvore)

    assert erro.value.databases == [("db", "Clientes")]
    assert arvore.etapas() == []


def test_database_dentro_de_coluna_dispara_a_recusa():
    arvore = ArvoreFalsa(
        {
            "pg": [{"id": "cl", "type": "column_list", "has_children": True,
                    "column_list": {}}],
            "cl": [{"id": "c1", "type": "column", "has_children": True, "column": {}}],
            "c1": [{"id": "db", "type": "child_database", "child_database": {"title": "X"}}],
        }
    )

    with pytest.raises(EscritaAbaixoDeDatabaseError):
        svc.escrever_conteudo("pg", "texto", cliente=arvore)

    assert svc.databases_da_pagina("pg", profundo=True, cliente=arvore) == [("db", "X")]
    assert svc.databases_da_pagina("pg", cliente=arvore) == []


def test_varredura_nao_desce_em_subpagina():
    arvore = ArvoreFalsa(
        {
            "pg": [{"id": "T", "type": "toggle", "has_children": True,
                    "toggle": {"rich_text": []}}],
            "T": [{"id": "sp", "type": "child_page", "has_children": True,
                   "child_page": {"title": "Sub"}}],
            "sp": [{"id": "db", "type": "child_database", "child_database": {"title": "Y"}}],
        }
    )

    assert svc.databases_da_pagina("pg", profundo=True, cliente=arvore) == []
    assert ("ler", "sp") not in arvore.chamadas
