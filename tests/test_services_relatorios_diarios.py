"""Testes do caso de uso de relatórios diários (um por data, sem duplicar)."""

from __future__ import annotations

import pytest

from notion_starter import properties
from notion_starter.services import relatorios_diarios as svc


class ClienteFake:
    """Database em memória com uma propriedade de título e uma de data."""

    def __init__(self, paginas: list[dict] | None = None):
        self.paginas = paginas or []
        self.criadas: list[tuple[str, dict]] = []
        self.atualizadas: list[tuple[str, dict]] = []
        self.escritas: list[tuple[str, str]] = []
        self._sequencia = 0

    def get_database(self, database_id):
        return {
            "properties": {
                "Relatório": {"type": "title"},
                "Data": {"type": "date"},
                "Resumo": {"type": "rich_text"},
            }
        }

    def consultar_database(self, database_id, buscar_todos=False, **kwargs):
        return self.paginas

    def criar_pagina(self, database_id, propriedades):
        self._sequencia += 1
        page_id = f"pagina-{self._sequencia}"
        self.criadas.append((page_id, propriedades))
        return {"id": page_id, "url": f"https://notion.so/{page_id}"}

    def atualizar_pagina(self, page_id, propriedades):
        self.atualizadas.append((page_id, propriedades))
        return {"id": page_id}


def _pagina(page_id: str, data: str) -> dict:
    return {"id": page_id, "properties": {"Data": {"date": {"start": data}}}}


@pytest.fixture
def escrever_espiao(monkeypatch):
    """Substitui a escrita de conteúdo, isolando o teste da conversão Markdown."""
    chamadas: list[tuple[str, str]] = []

    def falso_escrever(page_id, markdown, *, substituir=False, cliente=None):
        chamadas.append((page_id, markdown))
        return markdown.count("\n") + 1

    monkeypatch.setattr(svc, "escrever_conteudo", falso_escrever)
    return chamadas


class TestPaginasPorData:
    def test_mapeia_data_para_id(self):
        cliente = ClienteFake([_pagina("a", "2026-07-20"), _pagina("b", "2026-07-21")])
        assert svc.paginas_por_data("db", cliente=cliente) == {
            "2026-07-20": "a",
            "2026-07-21": "b",
        }

    def test_ignora_paginas_sem_data(self):
        cliente = ClienteFake([{"id": "x", "properties": {"Data": {"date": None}}}])
        assert svc.paginas_por_data("db", cliente=cliente) == {}

    def test_normaliza_data_com_hora(self):
        cliente = ClienteFake([_pagina("a", "2026-07-20T09:30:00.000-03:00")])
        assert svc.paginas_por_data("db", cliente=cliente) == {"2026-07-20": "a"}

    def test_data_repetida_mantem_a_primeira_ocorrencia(self):
        cliente = ClienteFake([_pagina("primeira", "2026-07-20"), _pagina("segunda", "2026-07-20")])
        assert svc.paginas_por_data("db", cliente=cliente) == {"2026-07-20": "primeira"}


class TestPublicarRelatorios:
    def test_cria_pagina_quando_a_data_nao_existe(self, escrever_espiao):
        cliente = ClienteFake()
        relatorio = svc.RelatorioDiario(data="2026-07-24", corpo_markdown="## Feito")

        resultado = svc.publicar_relatorios("db", [relatorio], cliente=cliente)

        assert len(cliente.criadas) == 1
        assert resultado.criadas == 1 and resultado.complementadas == 0
        assert resultado.relatorios[0].acao == "criada"
        assert resultado.relatorios[0].url == "https://notion.so/pagina-1"

    def test_anexa_corpo_a_pagina_existente_sem_duplicar(self, escrever_espiao):
        cliente = ClienteFake([_pagina("existente", "2026-07-24")])
        relatorio = svc.RelatorioDiario(data="2026-07-24", corpo_markdown="## Outro projeto")

        resultado = svc.publicar_relatorios("db", [relatorio], cliente=cliente)

        assert cliente.criadas == []
        assert escrever_espiao == [("existente", "## Outro projeto")]
        assert resultado.complementadas == 1
        assert resultado.relatorios[0].acao == "complementada"

    def test_pagina_existente_preserva_propriedades_por_padrao(self, escrever_espiao):
        # O dia pode já registrar trabalho de outro projeto: sobrescrever o
        # resumo apagaria esse registro.
        cliente = ClienteFake([_pagina("existente", "2026-07-24")])
        relatorio = svc.RelatorioDiario(
            data="2026-07-24",
            corpo_markdown="corpo",
            propriedades={"Resumo": properties.rich_text("novo resumo")},
        )

        svc.publicar_relatorios("db", [relatorio], cliente=cliente)

        assert cliente.atualizadas == []

    def test_pode_atualizar_propriedades_da_pagina_existente(self, escrever_espiao):
        cliente = ClienteFake([_pagina("existente", "2026-07-24")])
        relatorio = svc.RelatorioDiario(
            data="2026-07-24",
            propriedades={"Resumo": properties.rich_text("novo resumo")},
        )

        svc.publicar_relatorios(
            "db", [relatorio], atualizar_propriedades_existentes=True, cliente=cliente
        )

        assert cliente.atualizadas[0][0] == "existente"

    def test_titulo_padrao_usa_a_data_em_formato_brasileiro(self, escrever_espiao):
        cliente = ClienteFake()
        svc.publicar_relatorios("db", [svc.RelatorioDiario(data="2026-07-24")], cliente=cliente)
        titulo = cliente.criadas[0][1]["Relatório"]["title"][0]["text"]["content"]
        assert titulo == "Relatório — 24/07/2026"

    def test_titulo_explicito_vence_o_modelo(self, escrever_espiao):
        cliente = ClienteFake()
        svc.publicar_relatorios(
            "db",
            [svc.RelatorioDiario(data="2026-07-24", titulo="Fechamento da sprint")],
            cliente=cliente,
        )
        titulo = cliente.criadas[0][1]["Relatório"]["title"][0]["text"]["content"]
        assert titulo == "Fechamento da sprint"

    def test_preenche_a_propriedade_de_data_automaticamente(self, escrever_espiao):
        cliente = ClienteFake()
        svc.publicar_relatorios("db", [svc.RelatorioDiario(data="2026-07-24")], cliente=cliente)
        assert cliente.criadas[0][1]["Data"] == {"date": {"start": "2026-07-24"}}

    def test_propriedades_informadas_chegam_na_pagina_criada(self, escrever_espiao):
        cliente = ClienteFake()
        svc.publicar_relatorios(
            "db",
            [
                svc.RelatorioDiario(
                    data="2026-07-24",
                    propriedades={"Resumo": properties.rich_text("o que foi feito")},
                )
            ],
            cliente=cliente,
        )
        assert "Resumo" in cliente.criadas[0][1]

    def test_corpo_vazio_nao_escreve_blocos(self, escrever_espiao):
        cliente = ClienteFake()
        resultado = svc.publicar_relatorios(
            "db", [svc.RelatorioDiario(data="2026-07-24", corpo_markdown="   ")], cliente=cliente
        )
        assert escrever_espiao == []
        assert resultado.relatorios[0].blocos_escritos == 0

    def test_mesma_data_repetida_na_entrada_cria_uma_pagina_so(self, escrever_espiao):
        # A segunda ocorrência deve complementar a página recém-criada.
        cliente = ClienteFake()
        relatorios = [
            svc.RelatorioDiario(data="2026-07-24", corpo_markdown="primeiro"),
            svc.RelatorioDiario(data="2026-07-24", corpo_markdown="segundo"),
        ]

        resultado = svc.publicar_relatorios("db", relatorios, cliente=cliente)

        assert len(cliente.criadas) == 1
        assert resultado.criadas == 1 and resultado.complementadas == 1
        assert [pagina for pagina, _ in escrever_espiao] == ["pagina-1", "pagina-1"]

    def test_database_sem_titulo_falha_com_mensagem_clara(self, escrever_espiao):
        class SemTitulo(ClienteFake):
            def get_database(self, database_id):
                return {"properties": {"Data": {"type": "date"}}}

        with pytest.raises(ValueError, match="título"):
            svc.publicar_relatorios(
                "db", [svc.RelatorioDiario(data="2026-07-24")], cliente=SemTitulo()
            )

    def test_publicacao_sem_relatorios_nao_faz_nada(self, escrever_espiao):
        cliente = ClienteFake()
        resultado = svc.publicar_relatorios("db", [], cliente=cliente)
        assert resultado.relatorios == ()
        assert cliente.criadas == []
