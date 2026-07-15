from __future__ import annotations

import pytest

from notion_starter.services.ingestao import FontePlanilha, ingerir

CSV_CONTAS = """Nome,Seguidores,Criada em,Plataforma,Ativa,Email
Conta A,"1.614",26/05/2026,Instagram,sim,a@ex.com
Conta B,"2,7 mil",27/95/2026,TikTok,não,b@ex.com
,,,,,
"""


@pytest.fixture
def planilha_csv(tmp_path):
    caminho = tmp_path / "contas.csv"
    caminho.write_text(CSV_CONTAS, encoding="utf-8")
    return caminho


def test_csv_vira_itens_com_propriedades_tipadas(planilha_csv):
    fonte = FontePlanilha(
        planilha_csv,
        tipos={
            "Seguidores": "numero",
            "Criada em": "data",
            "Plataforma": "select",
            "Ativa": "checkbox",
            "Email": "email",
        },
    )
    itens = list(fonte.coletar())

    assert len(itens) == 2  # linha vazia ignorada
    a = itens[0]
    assert a.nome == "Conta A"
    assert a.origem == "contas.csv:2"
    assert a.propriedades["Seguidores"] == {"number": 1614}
    assert a.propriedades["Criada em"]["date"]["start"] == "2026-05-26"
    assert a.propriedades["Plataforma"] == {"select": {"name": "Instagram"}}
    assert a.propriedades["Ativa"] == {"checkbox": True}
    assert a.propriedades["Email"] == {"email": "a@ex.com"}


def test_valor_invalido_vai_para_observacoes_sem_ser_descartado(planilha_csv):
    fonte = FontePlanilha(planilha_csv, tipos={"Seguidores": "numero", "Criada em": "data"})
    b = list(fonte.coletar())[1]

    assert b.propriedades["Seguidores"] == {"number": 2700}
    assert "Criada em" not in b.propriedades
    observacoes = b.propriedades["Observações"]["rich_text"][0]["text"]["content"]
    assert "Criada em: 27/95/2026" in observacoes


def test_renomear_colunas(planilha_csv):
    fonte = FontePlanilha(planilha_csv, renomear={"Email": "E-mail de acesso"})
    item = next(iter(fonte.coletar()))
    assert "E-mail de acesso" in item.propriedades
    assert "Email" not in item.propriedades


def test_tipo_invalido_levanta(planilha_csv):
    with pytest.raises(ValueError, match="Tipos aceitos"):
        FontePlanilha(planilha_csv, tipos={"Seguidores": "moeda"})


def test_coluna_titulo_inexistente_levanta(planilha_csv):
    fonte = FontePlanilha(planilha_csv, coluna_titulo="Apelido")
    with pytest.raises(ValueError, match="Apelido"):
        list(fonte.coletar())


def test_arquivo_inexistente_e_formato_nao_suportado(tmp_path):
    with pytest.raises(ValueError, match="não encontrada"):
        list(FontePlanilha(tmp_path / "nada.csv").coletar())
    ods = tmp_path / "dados.ods"
    ods.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não suportado"):
        list(FontePlanilha(ods).coletar())


def test_xlsx_com_aba_e_serial_de_data(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    caminho = tmp_path / "dados.xlsx"
    pasta = openpyxl.Workbook()
    aba = pasta.active
    aba.title = "Contas"
    aba.append(["Nome", "Seguidores", "Criada em"])
    aba.append(["Conta X", 1614, 46168])
    pasta.save(caminho)

    fonte = FontePlanilha(
        caminho, aba="Contas", tipos={"Seguidores": "numero", "Criada em": "data"}
    )
    itens = list(fonte.coletar())

    assert itens[0].nome == "Conta X"
    assert itens[0].propriedades["Seguidores"] == {"number": 1614}
    assert itens[0].propriedades["Criada em"]["date"]["start"] == "2026-05-26"


def test_xlsx_aba_inexistente_levanta(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    caminho = tmp_path / "dados.xlsx"
    openpyxl.Workbook().save(caminho)
    with pytest.raises(ValueError, match="não existe"):
        list(FontePlanilha(caminho, aba="Outra").coletar())


# -- Integração com o caso de uso idempotente -------------------------------


class ClienteFake:
    def __init__(self):
        self.criadas = []
        self.atualizadas = []

    def consultar_database(self, database_id, page_size=1, filtro=None):
        return []

    def criar_pagina(self, database_id, props):
        self.criadas.append(props)
        return {"id": f"page-{len(self.criadas)}"}

    def atualizar_pagina(self, page_id, props):
        self.atualizadas.append((page_id, props))
        return {"id": page_id}


def test_ingerir_relata_motivo_de_cada_falha(planilha_csv):
    class ClienteQueRejeita(ClienteFake):
        def criar_pagina(self, database_id, props):
            raise RuntimeError("Nome is not a property that exists")

    resultado = ingerir(FontePlanilha(planilha_csv), client=ClienteQueRejeita(), database_id="db1")

    assert resultado.erros == 2
    assert len(resultado.falhas) == 2
    assert resultado.falhas[0] == (
        "Conta A (contas.csv:2): Nome is not a property that exists"
    )


def test_ingerir_grava_propriedades_tipadas_da_planilha(planilha_csv):
    fonte = FontePlanilha(planilha_csv, tipos={"Seguidores": "numero"})
    cliente = ClienteFake()

    resultado = ingerir(fonte, client=cliente, database_id="db1")

    assert resultado.criados == 2
    props = cliente.criadas[0]
    assert props["Nome"]["title"][0]["text"]["content"] == "Conta A"
    assert props["Fonte"] == {"select": {"name": "planilha"}}
    assert props["Seguidores"] == {"number": 1614}
    assert props["Origem"]["rich_text"][0]["text"]["content"] == "contas.csv:2"
