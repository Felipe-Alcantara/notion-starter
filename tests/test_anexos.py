from __future__ import annotations

import pytest

from notion_starter.services.anexos import anexar_arquivo


class ClienteFake:
    def __init__(self, pagina=None):
        self._pagina = pagina or {"properties": {}}
        self.uploads = []
        self.atualizacoes = []

    def enviar_arquivo(self, conteudo, nome, content_type):
        self.uploads.append((nome, content_type, len(conteudo)))
        return "upload-1"

    def obter_pagina(self, page_id):
        return self._pagina

    def atualizar_pagina(self, page_id, props):
        self.atualizacoes.append((page_id, props))
        return {"id": page_id}


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "relatorio.docx"
    caminho.write_bytes(b"conteudo")
    return caminho


def test_anexa_arquivo_com_mime_e_propriedade(arquivo):
    cliente = ClienteFake()
    resumo = anexar_arquivo("pag1", arquivo, cliente=cliente)

    nome, content_type, tamanho = cliente.uploads[0]
    assert nome == "relatorio.docx"
    assert "wordprocessingml" in content_type
    assert tamanho == 8
    page_id, props = cliente.atualizacoes[0]
    assert page_id == "pag1"
    anexos = props["Arquivos e mídia"]["files"]
    assert anexos[0]["file_upload"]["id"] == "upload-1"
    assert resumo["total_anexos"] == 1


def test_preserva_anexos_existentes_por_padrao(arquivo):
    pagina = {
        "properties": {
            "Arquivos e mídia": {
                "files": [
                    {"type": "external", "name": "antigo.pdf", "external": {"url": "https://x"}},
                    {"type": "file", "name": "notion.png", "file": {"url": "https://tmp"}},
                ]
            }
        }
    }
    cliente = ClienteFake(pagina)
    resumo = anexar_arquivo("pag1", arquivo, cliente=cliente)

    anexos = cliente.atualizacoes[0][1]["Arquivos e mídia"]["files"]
    assert resumo["total_anexos"] == 3
    assert anexos[0]["external"]["url"] == "https://x"
    # arquivo hospedado pelo Notion é re-referenciado como external
    assert anexos[1] == {"type": "external", "name": "notion.png", "external": {"url": "https://tmp"}}
    assert anexos[2]["type"] == "file_upload"


def test_substituir_ignora_existentes(arquivo):
    pagina = {
        "properties": {
            "Anexos": {"files": [{"type": "external", "name": "a", "external": {"url": "u"}}]}
        }
    }
    cliente = ClienteFake(pagina)
    resumo = anexar_arquivo(
        "pag1", arquivo, propriedade="Anexos", substituir=True, cliente=cliente
    )
    assert resumo["total_anexos"] == 1


def test_arquivo_inexistente_levanta(tmp_path):
    with pytest.raises(ValueError, match="não encontrado"):
        anexar_arquivo("pag1", tmp_path / "nada.bin", cliente=ClienteFake())
