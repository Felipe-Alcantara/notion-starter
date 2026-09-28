"""Inventário com datas e caminho, download retomável de corpos e busca no texto.

Três serviços encadeados, testados sem rede: ``inventario_workspace`` (um
``/search`` paginado vira registros com ``created_time`` e o caminho de
ancestrais), ``corpos`` (baixa o Markdown de cada página, retomável e
priorizado) e ``busca_conteudo`` (regex no texto baixado, sem acentos).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from notion_starter.services.busca_conteudo import (
    buscar_no_conteudo,
    compilar,
    procurar_no_texto,
    separar_meta,
)
from notion_starter.services.corpos import (
    baixar_corpos,
    cabecalho,
    caminho_do_corpo,
    ordenar_por_prioridade,
    selecionar_paginas,
)
from notion_starter.services.inventario_workspace import (
    InventarioInvalidoError,
    RegistroWorkspace,
    carregar_inventario,
    normalizar_registro,
    preencher_caminhos,
    resumir,
    salvar_inventario,
    varrer_workspace,
)


def _pagina(pid: str, titulo: str, pai: tuple[str, str | None], **extra: Any) -> dict[str, Any]:
    tipo, pai_id = pai
    parent = {"type": tipo, tipo: pai_id} if pai_id else {"type": "workspace", "workspace": True}
    return {
        "object": "page",
        "id": pid,
        "url": f"https://notion.so/{pid}",
        "created_time": extra.pop("criado", "2026-01-01T10:00:00.000Z"),
        "last_edited_time": "2026-09-01T10:00:00.000Z",
        "parent": parent,
        "properties": {
            "title": {"type": "title", "title": [{"plain_text": titulo}]},
            **extra.pop("props", {}),
        },
        **extra,
    }


def _database(did: str, titulo: str, pai_id: str) -> dict[str, Any]:
    return {
        "object": "database",
        "id": did,
        "title": [{"plain_text": titulo}],
        "created_time": "2025-12-01T10:00:00.000Z",
        "last_edited_time": "2026-09-01T10:00:00.000Z",
        "parent": {"type": "page_id", "page_id": pai_id},
    }


def _workspace() -> list[dict[str, Any]]:
    return [
        _pagina("raiz", "Estudo", ("page_id", None)),
        _pagina("prog", "Programação", ("page_id", "raiz")),
        _database("db-ideias", "Ideias", "prog"),
        _pagina("i1", "Rascunho de artigo", ("database_id", "db-ideias"),
                criado="2026-03-01T09:00:00.000Z",
                props={"Etapa": {"type": "select", "select": {"name": "Ideia"}},
                       "Vazia": {"type": "rich_text", "rich_text": []}}),
        _pagina("velha", "Arquivada", ("page_id", "raiz"), archived=True),
    ]


class ClienteBusca:
    def __init__(self) -> None:
        self.filtros: list[Any] = []

    def buscar(self, query=None, page_size=100, buscar_todos=False, filtro=None):
        self.filtros.append(filtro)
        itens = _workspace()
        if filtro:
            itens = [i for i in itens if i["object"] == filtro["value"]]
        return itens


# -- inventário ------------------------------------------------------------------


def test_registro_traz_datas_colunas_preenchidas_e_arquivado():
    registro = normalizar_registro(_workspace()[3])

    assert registro.criado_em == "2026-03-01T09:00:00.000Z"
    assert registro.editado_em == "2026-09-01T10:00:00.000Z"
    assert registro.pai_tipo == "database_id" and registro.pai_id == "db-ideias"
    assert registro.propriedades == {"title": "Rascunho de artigo", "Etapa": "Ideia"}
    assert normalizar_registro(_workspace()[4]).arquivado is True


def test_varredura_preenche_o_caminho_de_ancestrais():
    registros = varrer_workspace(cliente=ClienteBusca())

    linha = next(r for r in registros if r.id == "i1")
    assert linha.caminho == ["Estudo", "Programação", "Ideias"]
    assert linha.caminho_completo[-1] == "Rascunho de artigo"
    assert resumir(registros)["databases"] == 1


def test_filtro_vai_para_o_search_e_filtro_invalido_recusa():
    cliente = ClienteBusca()

    registros = varrer_workspace(filtro="database", cliente=cliente)

    assert cliente.filtros == [{"property": "object", "value": "database"}]
    assert [r.objeto for r in registros] == ["database"]
    with pytest.raises(ValueError):
        varrer_workspace(filtro="bloco", cliente=cliente)


def test_caminho_para_em_ciclo_sem_travar():
    a = RegistroWorkspace("a", "page", "A", None, None, "page_id", "b")
    b = RegistroWorkspace("b", "page", "B", None, None, "page_id", "a")

    preencher_caminhos([a, b])

    assert a.caminho == ["B"] and b.caminho == ["A"]


def test_salvar_e_carregar_ida_e_volta(tmp_path):
    registros = varrer_workspace(cliente=ClienteBusca())
    destino = tmp_path / "sub" / "inventario.json"

    salvar_inventario(registros, destino)
    relidos = carregar_inventario(destino)

    assert [r.para_dict() for r in relidos] == [r.para_dict() for r in registros]
    assert not list(destino.parent.glob("*.parcial"))


def test_carregar_aceita_lista_pura_e_recusa_formato_estranho(tmp_path):
    lista = tmp_path / "lista.json"
    lista.write_text('[{"id": "x", "objeto": "page", "titulo": "X", "criado_em": null, '
                     '"editado_em": null, "pai_tipo": "workspace", "pai_id": null, '
                     '"extra_desconhecido": 1}]', encoding="utf-8")
    assert carregar_inventario(lista)[0].titulo == "X"

    estranho = tmp_path / "estranho.json"
    estranho.write_text('{"itens": [1, 2]}', encoding="utf-8")
    with pytest.raises(InventarioInvalidoError):
        carregar_inventario(estranho)


# -- corpos ----------------------------------------------------------------------


def _registros() -> list[RegistroWorkspace]:
    return varrer_workspace(cliente=ClienteBusca())


def test_selecao_pula_databases_arquivados_e_prefixos_de_caminho():
    registros = _registros()

    todas = selecionar_paginas(registros)
    assert {r.id for r in todas} == {"raiz", "prog", "i1"}

    sem_prog = selecionar_paginas(registros, ignorar_caminhos=["Estudo / Programação"])
    assert {r.id for r in sem_prog} == {"raiz"}

    sem_ideias = selecionar_paginas(registros, ignorar_databases=["db-ideias"])
    assert "i1" not in {r.id for r in sem_ideias}

    so_ideias = selecionar_paginas(registros, somente_databases=["DB-IDEIAS"])
    assert [r.id for r in so_ideias] == ["i1"]

    com_arquivadas = selecionar_paginas(registros, incluir_arquivados=True)
    assert "velha" in {r.id for r in com_arquivadas}


def test_prioridade_poe_soltas_primeiro_e_candidatas_antes_do_resto():
    def linha(pid: str, titulo: str) -> RegistroWorkspace:
        return RegistroWorkspace(pid, "page", titulo, None, None, "database_id", "db-grande")

    grandes = [linha(f"t{i}", "Tarefa") for i in range(3)] + [linha("a1", "Ideia de artigo")]
    solta = RegistroWorkspace("s", "page", "Nota", None, None, "page_id", "raiz")

    ordem = ordenar_por_prioridade(
        [*grandes, solta], priorizar=re.compile("artigo"), limite_volumoso=3
    )

    assert [p.id for p in ordem] == ["s", "a1", "t0", "t1", "t2"]


class ClienteCorpos:
    def __init__(self, falhar: set[str] | None = None) -> None:
        self.lidos: list[str] = []
        self.falhar = falhar or set()

    def ler_blocos(self, block_id: str, buscar_todos: bool = False, recursivo: bool = False):
        self.lidos.append(block_id)
        if block_id in self.falhar:
            raise RuntimeError("rede caiu")
        return [{"type": "paragraph", "has_children": False,
                 "paragraph": {"rich_text": [{"type": "text", "plain_text": f"corpo {block_id}",
                                              "text": {"content": f"corpo {block_id}"}}]}}]


def test_download_retoma_de_onde_parou_e_respeita_o_limite(tmp_path):
    paginas = selecionar_paginas(_registros())
    cliente = ClienteCorpos()

    primeira = baixar_corpos(paginas, tmp_path, limite=2, trabalhadores=1, cliente=cliente)
    segunda = baixar_corpos(paginas, tmp_path, trabalhadores=2, cliente=cliente)

    assert (primeira.baixados, primeira.adiados) == (2, 1)
    assert (segunda.baixados, segunda.pulados) == (1, 2)
    assert sorted(cliente.lidos) == sorted(p.id for p in paginas)  # cada uma lida uma vez
    texto = caminho_do_corpo(tmp_path, "i1").read_text(encoding="utf-8")
    meta, corpo = separar_meta(texto)
    assert meta["caminho"] == "Estudo / Programação / Ideias"
    assert meta["criado_em"] == "2026-03-01T09:00:00.000Z"
    assert corpo.strip() == "corpo i1"


def test_falha_nao_deixa_arquivo_e_fica_para_a_proxima(tmp_path):
    paginas = selecionar_paginas(_registros())

    resultado = baixar_corpos(paginas, tmp_path, cliente=ClienteCorpos(falhar={"prog"}))

    assert "prog" in resultado.falhas and "rede caiu" in resultado.falhas["prog"]
    assert not caminho_do_corpo(tmp_path, "prog").exists()
    assert not list(tmp_path.glob("*.parcial"))
    novo = baixar_corpos(paginas, tmp_path, cliente=ClienteCorpos())
    assert (novo.baixados, novo.pulados) == (1, 2)


def test_titulo_com_fim_de_comentario_nao_quebra_o_cabecalho():
    registro = RegistroWorkspace("x", "page", "setas --> e mais", None, None, "workspace", None)

    meta, corpo = separar_meta(cabecalho(registro) + "texto")

    assert meta["titulo"] == "setas --> e mais"
    assert corpo == "texto"


def test_parametros_invalidos_recusam(tmp_path):
    with pytest.raises(ValueError):
        baixar_corpos([], tmp_path, trabalhadores=0, cliente=ClienteCorpos())
    with pytest.raises(ValueError):
        baixar_corpos([], tmp_path, limite=0, cliente=ClienteCorpos())


# -- busca no texto --------------------------------------------------------------


def _gravar(pasta: Path, pid: str, titulo: str, corpo: str, criado: str) -> None:
    registro = RegistroWorkspace(pid, "page", titulo, criado, None, "workspace", None)
    caminho_do_corpo(pasta, pid).write_text(cabecalho(registro) + corpo, encoding="utf-8")


def test_busca_ignora_acentos_e_corta_o_trecho_do_original(tmp_path):
    _gravar(tmp_path, "p1", "Diário", "Hoje pensei numa PUBLICAÇÃO sobre IA.", "2026-02-01")
    _gravar(tmp_path, "p2", "Outra", "nada aqui", "2026-01-01")
    _gravar(tmp_path, "p3", "Mais", "publicacao, publicação e publicacão", "2026-03-01")

    ocorrencias = buscar_no_conteudo(tmp_path, r"publica[cç][aã]o")

    assert [o.id for o in ocorrencias] == ["p3", "p1"]
    assert ocorrencias[1].trechos == ["Hoje pensei numa PUBLICAÇÃO sobre IA."]
    assert ocorrencias[0].total == 3
    assert ocorrencias[1].titulo == "Diário" and ocorrencias[1].criado_em == "2026-02-01"


def test_busca_com_acentos_e_caixa_quando_pedido(tmp_path):
    _gravar(tmp_path, "p1", "A", "Publicação e publicacao", "2026-01-01")

    exata = buscar_no_conteudo(tmp_path, "Publicação", ignorar_acentos=False, ignorar_caixa=False)

    assert exata[0].total == 1


def test_trecho_do_original_com_ligadura_e_mapa_certo():
    expressao = compilar("final")
    termos, trechos = procurar_no_texto("o ﬁnal chegou", expressao, contexto=2)

    assert termos == {"final": 1}
    assert trechos == ["o ﬁnal c"]


def test_expressao_invalida_ou_pasta_ausente_recusam(tmp_path):
    with pytest.raises(ValueError, match="inválida"):
        buscar_no_conteudo(tmp_path, "(sem fechar")
    with pytest.raises(ValueError, match="Pasta"):
        buscar_no_conteudo(tmp_path / "nao-existe", "x")
