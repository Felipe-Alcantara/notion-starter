from __future__ import annotations

from notion_starter import readers as r

# -- Texto -----------------------------------------------------------------


def test_ler_title_usa_plain_text():
    prop = {"type": "title", "title": [{"plain_text": "Ada"}, {"plain_text": " Lovelace"}]}
    assert r.ler_title(prop) == "Ada Lovelace"


def test_ler_title_cai_para_text_content():
    # Payload montado à mão (como o de properties.title), sem plain_text.
    prop = {"type": "title", "title": [{"text": {"content": "Oi"}}]}
    assert r.ler_title(prop) == "Oi"


def test_ler_rich_text():
    prop = {"type": "rich_text", "rich_text": [{"plain_text": "corpo"}]}
    assert r.ler_rich_text(prop) == "corpo"


def test_texto_vazio_ou_ausente():
    assert r.ler_title({"type": "title", "title": []}) == ""
    assert r.ler_title(None) == ""
    assert r.ler_rich_text({}) == ""


# -- Select / status / multi_select ----------------------------------------


def test_ler_select():
    assert r.ler_select({"type": "select", "select": {"name": "Engenharia"}}) == "Engenharia"


def test_ler_select_vazio_retorna_none():
    assert r.ler_select({"type": "select", "select": None}) is None
    assert r.ler_select(None) is None


def test_ler_status():
    assert r.ler_status({"type": "status", "status": {"name": "00. Inbox"}}) == "00. Inbox"
    assert r.ler_status({"type": "status", "status": None}) is None


def test_ler_multi_select():
    prop = {"type": "multi_select", "multi_select": [{"name": "GitHub"}, {"name": "Programação"}]}
    assert r.ler_multi_select(prop) == ["GitHub", "Programação"]
    assert r.ler_multi_select({"type": "multi_select", "multi_select": []}) == []
    assert r.ler_multi_select(None) == []


# -- Data ------------------------------------------------------------------


def test_ler_date_retorna_start():
    prop = {"type": "date", "date": {"start": "2026-07-01", "end": "2026-07-02"}}
    assert r.ler_date(prop) == "2026-07-01"


def test_ler_date_vazia_retorna_none():
    assert r.ler_date({"type": "date", "date": None}) is None
    assert r.ler_date(None) is None


# -- Escalares -------------------------------------------------------------


def test_escalares():
    assert r.ler_email({"type": "email", "email": "a@b.com"}) == "a@b.com"
    assert r.ler_phone_number({"type": "phone_number", "phone_number": "+55 11"}) == "+55 11"
    assert r.ler_url({"type": "url", "url": "https://x.y"}) == "https://x.y"
    assert r.ler_number({"type": "number", "number": 3}) == 3
    assert r.ler_checkbox({"type": "checkbox", "checkbox": True}) is True


def test_escalares_vazios():
    assert r.ler_email({"type": "email", "email": None}) is None
    assert r.ler_number({"type": "number", "number": None}) is None
    assert r.ler_checkbox({"type": "checkbox"}) is False
    assert r.ler_checkbox(None) is False


# -- Relation / people -----------------------------------------------------


def test_ler_relation():
    prop = {"type": "relation", "relation": [{"id": "pg1"}, {"id": "pg2"}]}
    assert r.ler_relation(prop) == ["pg1", "pg2"]
    assert r.ler_relation({"type": "relation", "relation": []}) == []
    assert r.ler_relation(None) == []


def test_ler_people():
    prop = {"type": "people", "people": [{"id": "u1"}]}
    assert r.ler_people(prop) == ["u1"]
    assert r.ler_people(None) == []


# -- Despacho por tipo -----------------------------------------------------


def test_ler_propriedade_despacha_pelo_tipo():
    assert r.ler_propriedade({"type": "select", "select": {"name": "X"}}) == "X"
    assert r.ler_propriedade({"type": "checkbox", "checkbox": False}) is False


def test_ler_propriedade_tipo_nao_suportado_retorna_none():
    assert r.ler_propriedade({"type": "rollup", "rollup": {"number": 9}}) is None
    assert r.ler_propriedade("não é dict") is None


# -- extrair_valores -------------------------------------------------------


def test_extrair_valores_mapeia_pagina_inteira():
    pagina = {
        "id": "pg1",
        "properties": {
            "Nome": {"type": "title", "title": [{"plain_text": "Estudar Notion"}]},
            "Status": {"type": "status", "status": {"name": "00. Inbox"}},
            "Próximo prazo": {"type": "date", "date": {"start": "2026-07-01"}},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "Programação"}]},
            "Concluída": {"type": "checkbox", "checkbox": False},
        },
    }
    assert r.extrair_valores(pagina) == {
        "Nome": "Estudar Notion",
        "Status": "00. Inbox",
        "Próximo prazo": "2026-07-01",
        "Tags": ["Programação"],
        "Concluída": False,
    }


def test_extrair_valores_pagina_sem_properties():
    assert r.extrair_valores({}) == {}
    assert r.extrair_valores({"id": "pg1"}) == {}


def test_extrair_valores_tipo_nao_suportado_vira_none():
    pagina = {"properties": {"Fórmula": {"type": "formula", "formula": {"number": 7}}}}
    assert r.extrair_valores(pagina) == {"Fórmula": None}
