"""Ler o schema real de um database antes de escrever nele.

Sem isto, descobrir o nome exato de uma coluna, os valores aceitos por um
select ou se uma relação é de mão única exigia chamar a API do Notion na mão —
que é exatamente o passo que se pula quando se está com pressa, e o erro só
aparece depois, gravado.
"""

from __future__ import annotations

from notion_starter import descrever_database


def _database() -> dict:
    return {
        "id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
        "title": [{"plain_text": "Tarefas — "}, {"plain_text": "HOME"}],
        "properties": {
            "Prioridade": {
                "type": "select",
                "select": {"options": [{"name": "Baixa"}, {"name": "Alta"}]},
            },
            "Tarefa": {"type": "title"},
            "Subtarefas relacionadas": {
                "type": "relation",
                "relation": {
                    "database_id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
                    "type": "single_property",
                    "single_property": {},
                },
            },
            "Projeto": {
                "type": "relation",
                "relation": {
                    "database_id": "38e91f95-497e-818b-ab08-ff19918d6c7c",
                    "type": "dual_property",
                    "dual_property": {"synced_property_name": "Tarefas"},
                },
            },
            "Finalização": {"type": "last_edited_time"},
            "Etapa": {
                "type": "status",
                "status": {"options": [{"name": "Entrada"}, {"name": "Concluída"}]},
            },
        },
    }


def test_titulo_vem_concatenado_do_rich_text():
    assert descrever_database(_database()).titulo == "Tarefas — HOME"


def test_database_sem_titulo_nao_devolve_string_vazia():
    assert descrever_database({"id": "x", "properties": {}}).titulo == "(sem título)"


def test_coluna_de_titulo_vem_primeiro_e_o_resto_em_ordem_alfabetica():
    """Ordem estável: a mesma entrada sai sempre igual, e o título lidera."""

    nomes = [coluna.nome for coluna in descrever_database(_database()).colunas]

    assert nomes[0] == "Tarefa"
    assert nomes[1:] == [
        "Etapa",
        "Finalização",
        "Prioridade",
        "Projeto",
        "Subtarefas relacionadas",
    ]


def test_opcoes_de_select_e_status_sao_expostas():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}

    assert colunas["Prioridade"].opcoes == ("Baixa", "Alta")
    assert colunas["Etapa"].opcoes == ("Entrada", "Concluída")


def test_tipo_calculado_pelo_notion_e_marcado_como_nao_editavel():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}

    assert colunas["Finalização"].editavel is False
    assert colunas["Tarefa"].editavel is True
    assert "Finalização" not in {c.nome for c in descrever_database(_database()).editaveis}


def test_relacao_de_mao_unica_e_identificada_e_avisada():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}
    relacao = colunas["Subtarefas relacionadas"].relacao

    assert relacao is not None
    assert relacao.bidirecional is False
    assert relacao.auto_referente is True
    assert "single_property" in (relacao.aviso or "")


def test_relacao_bidirecional_nao_gera_aviso():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}
    relacao = colunas["Projeto"].relacao

    assert relacao is not None
    assert relacao.bidirecional is True
    assert relacao.coluna_espelho == "Tarefas"
    assert relacao.auto_referente is False
    assert relacao.aviso is None


def test_avisos_do_database_listam_so_o_que_exige_acao():
    avisos = descrever_database(_database()).avisos

    assert len(avisos) == 1
    assert avisos[0].startswith("Subtarefas relacionadas:")


def test_auto_referencia_ignora_hifens_do_id():
    """A API aceita o ID com e sem hífen; comparar cru daria falso negativo."""

    database = {
        "id": "30296e2dcd394cf38bbd3fb2f53c0195",
        "properties": {
            "Sub": {
                "type": "relation",
                "relation": {
                    "database_id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
                    "type": "single_property",
                },
            }
        },
    }

    relacao = descrever_database(database).colunas[0].relacao

    assert relacao is not None and relacao.auto_referente is True


def test_para_dict_serializa_opcoes_relacao_e_avisos():
    dados = descrever_database(_database()).para_dict()
    por_nome = {coluna["nome"]: coluna for coluna in dados["colunas"]}

    assert por_nome["Prioridade"]["opcoes"] == ["Baixa", "Alta"]
    assert por_nome["Projeto"]["relacao"]["bidirecional"] is True
    assert "opcoes" not in por_nome["Tarefa"]
    assert len(dados["avisos"]) == 1
