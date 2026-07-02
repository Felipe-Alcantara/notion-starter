from __future__ import annotations

from datetime import date, datetime

from notion_starter import properties as p


def test_title():
    assert p.title("Oi") == {"title": [{"text": {"content": "Oi"}}]}


def test_rich_text():
    assert p.rich_text("corpo") == {"rich_text": [{"text": {"content": "corpo"}}]}


def test_email_phone_url_number_checkbox():
    assert p.email("a@b.com") == {"email": "a@b.com"}
    assert p.phone_number("+55 11") == {"phone_number": "+55 11"}
    assert p.url("https://x.y") == {"url": "https://x.y"}
    assert p.number(3) == {"number": 3}
    assert p.checkbox(True) == {"checkbox": True}


def test_select_status_multi_select():
    assert p.select("A") == {"select": {"name": "A"}}
    assert p.status("Concluído") == {"status": {"name": "Concluído"}}
    assert p.multi_select(["x", "y"]) == {"multi_select": [{"name": "x"}, {"name": "y"}]}


def test_relation():
    assert p.relation(["id-1", "id-2"]) == {"relation": [{"id": "id-1"}, {"id": "id-2"}]}
    assert p.relation([]) == {"relation": []}


def test_date_com_string():
    assert p.date("2026-06-24") == {"date": {"start": "2026-06-24"}}


def test_date_com_date_e_intervalo():
    resultado = p.date(date(2026, 6, 24), datetime(2026, 6, 25, 10, 0))
    assert resultado["date"]["start"] == "2026-06-24"
    assert resultado["date"]["end"].startswith("2026-06-25T10:00")
