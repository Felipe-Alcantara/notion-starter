"""A reescrita de corpo não pode custar o que ela não sabe repor.

``escrever --substituir`` apaga o corpo antes de escrever. Antes destes testes
ele apagava **tudo**, inclusive imagem (URL assinada que expira) e
``child_database`` — nesse caso levando junto o database inteiro que morava na
página, com ID novo ao restaurar e todo link salvo quebrado.
"""

from __future__ import annotations

from typing import Any

import pytest

from notion_starter.services.conteudo import (
    TIPOS_NAO_RECRIAVEIS,
    escrever_conteudo,
    limpar_conteudo,
)


class ClienteFalso:
    """Cliente mínimo: registra o que foi apagado e devolve o que foi anexado."""

    def __init__(self, blocos: list[dict[str, Any]]) -> None:
        self.blocos = blocos
        self.apagados: list[str] = []
        self.anexados: list[dict[str, Any]] = []

    def ler_blocos(self, page_id: str, *, buscar_todos: bool = False) -> list[dict[str, Any]]:
        return self.blocos

    def excluir_bloco(self, block_id: str) -> dict[str, Any]:
        self.apagados.append(block_id)
        return {"id": block_id}

    def anexar_blocos(self, page_id: str, lote: list[dict[str, Any]]) -> dict[str, Any]:
        self.anexados.extend(lote)
        return {"results": lote}


def _pagina_mista() -> ClienteFalso:
    return ClienteFalso(
        [
            {"id": "texto-1", "type": "paragraph"},
            {"id": "imagem", "type": "image"},
            {"id": "texto-2", "type": "heading_2"},
            {"id": "database", "type": "child_database"},
            {"id": "subpagina", "type": "child_page"},
        ]
    )


def test_limpar_preserva_blocos_nao_recriaveis_por_padrao():
    cliente = _pagina_mista()

    resultado = limpar_conteudo("pg", cliente=cliente)

    assert cliente.apagados == ["texto-1", "texto-2"]
    assert [tipo for _, tipo in resultado.preservados] == [
        "image",
        "child_database",
        "child_page",
    ]
    assert resultado.apagados == 2


def test_limpar_apaga_tudo_quando_pedido_explicitamente():
    cliente = _pagina_mista()

    resultado = limpar_conteudo("pg", incluir_nao_recriaveis=True, cliente=cliente)

    assert len(cliente.apagados) == 5
    assert resultado.preservados == []


def test_resultado_de_limpeza_continua_valendo_como_numero():
    """Quem só usava a contagem antiga não pode quebrar com o tipo novo."""

    cliente = ClienteFalso([{"id": "a", "type": "paragraph"}])

    resultado = limpar_conteudo("pg", cliente=cliente)

    assert resultado == 1
    assert int(resultado) == 1


def test_substituir_nao_apaga_a_imagem_da_pagina():
    """Mesmo com a escrita solta autorizada, o que não se recria fica."""

    cliente = _pagina_mista()

    resultado = escrever_conteudo(
        "pg", "# Texto novo", substituir=True, mesmo_com_database=True, cliente=cliente
    )

    assert "imagem" not in cliente.apagados
    assert "database" not in cliente.apagados
    assert [tipo for _, tipo in resultado.preservados] == [
        "image",
        "child_database",
        "child_page",
    ]
    assert int(resultado) == 1


def test_substituir_com_apagar_nao_recriaveis_leva_tudo():
    cliente = _pagina_mista()

    resultado = escrever_conteudo(
        "pg",
        "# Texto novo",
        substituir=True,
        apagar_nao_recriaveis=True,
        mesmo_com_database=True,
        cliente=cliente,
    )

    assert len(cliente.apagados) == 5
    assert resultado.preservados == []


def test_escrita_sem_substituir_nao_apaga_nada_e_nao_reporta_limpeza():
    cliente = _pagina_mista()

    resultado = escrever_conteudo(
        "pg", "# Só anexa", mesmo_com_database=True, cliente=cliente
    )

    assert cliente.apagados == []
    assert resultado.limpeza is None
    assert resultado.preservados == []


def test_markdown_vazio_nao_chega_a_apagar_nada():
    """A validação vem antes da limpeza: entrada inválida nunca zera a página."""

    cliente = _pagina_mista()

    with pytest.raises(ValueError):
        escrever_conteudo(
            "pg", "   ", substituir=True, mesmo_com_database=True, cliente=cliente
        )

    assert cliente.apagados == []


def test_child_database_esta_na_lista_de_nao_recriaveis():
    """O caso mais grave: apagar este bloco leva o database inteiro junto."""

    assert "child_database" in TIPOS_NAO_RECRIAVEIS
    assert "image" in TIPOS_NAO_RECRIAVEIS
    assert "paragraph" not in TIPOS_NAO_RECRIAVEIS


class ClienteComDatabase(ClienteFalso):
    """Página que parece um documento, mas é a casa de uma database."""

    def __init__(self, titulo: str = "Tarefas — HOME") -> None:
        super().__init__(
            [
                {"id": "texto", "type": "paragraph"},
                {
                    "id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
                    "type": "child_database",
                    "child_database": {"title": titulo},
                },
            ]
        )


def test_databases_da_pagina_encontra_a_tabela_de_dentro():
    from notion_starter.services.conteudo import databases_da_pagina

    encontradas = databases_da_pagina("pg", cliente=ClienteComDatabase())

    assert encontradas == [
        ("30296e2d-cd39-4cf3-8bbd-3fb2f53c0195", "Tarefas — HOME")
    ]


def test_pagina_so_de_texto_nao_reporta_database():
    from notion_starter.services.conteudo import databases_da_pagina

    cliente = ClienteFalso([{"id": "a", "type": "paragraph"}])

    assert databases_da_pagina("pg", cliente=cliente) == []


def test_escrever_em_pagina_com_database_e_recusado():
    """O erro clássico: link de página que contém tabela, texto solto embaixo."""

    from notion_starter.exceptions import EscritaAbaixoDeDatabaseError

    cliente = ClienteComDatabase()

    with pytest.raises(EscritaAbaixoDeDatabaseError) as erro:
        escrever_conteudo("pg", "# Anotação", cliente=cliente)

    assert cliente.anexados == []
    assert erro.value.databases[0][1] == "Tarefas — HOME"


def test_mensagem_da_recusa_ensina_o_caminho_certo():
    """A mensagem é o produto: um modelo fraco tem que saber o que fazer depois."""

    from notion_starter.exceptions import EscritaAbaixoDeDatabaseError

    with pytest.raises(EscritaAbaixoDeDatabaseError) as erro:
        escrever_conteudo("pg", "# Anotação", cliente=ClienteComDatabase())

    mensagem = str(erro.value)
    assert "CONTÉM database" in mensagem
    assert "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195" in mensagem
    assert "notion-tasks linhas" in mensagem
    assert "editar-linha" in mensagem
    assert "--mesmo-com-database" in mensagem


def test_escrita_solta_e_permitida_com_pedido_explicito():
    cliente = ClienteComDatabase()

    resultado = escrever_conteudo(
        "pg", "# Anotação", mesmo_com_database=True, cliente=cliente
    )

    assert int(resultado) == 1
    assert cliente.anexados


def test_substituir_em_pagina_com_database_nao_apaga_nada_ao_recusar():
    """A recusa vem ANTES da limpeza: a tabela não pode ser tocada."""

    from notion_starter.exceptions import EscritaAbaixoDeDatabaseError

    cliente = ClienteComDatabase()

    with pytest.raises(EscritaAbaixoDeDatabaseError):
        escrever_conteudo("pg", "# Novo", substituir=True, cliente=cliente)

    assert cliente.apagados == []
