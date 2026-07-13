from __future__ import annotations

import datetime as dt

from notion_starter.valores_br import data_br, numero_br

# -- numero_br ---------------------------------------------------------------


def test_numero_br_milhar_com_ponto():
    assert numero_br("1.614") == 1614
    assert numero_br("1.234.567") == 1234567


def test_numero_br_decimal_com_virgula():
    assert numero_br("2,7") == 2.7
    assert numero_br("1.234,56") == 1234.56


def test_numero_br_sufixos_textuais():
    assert numero_br("2,7 mil") == 2700
    assert numero_br("1,5 mi") == 1500000
    assert numero_br("2 bilhões") == 2000000000


def test_numero_br_moeda_e_negativo():
    assert numero_br("R$ 1.200") == 1200
    assert numero_br("-3,5") == -3.5


def test_numero_br_passa_numeros_prontos():
    assert numero_br(42) == 42
    assert numero_br(3.14) == 3.14


def test_numero_br_invalidos_devolvem_none():
    assert numero_br(None) is None
    assert numero_br("") is None
    assert numero_br("abc") is None
    assert numero_br("1.2.3") is None
    assert numero_br(True) is None


def test_numero_br_ponto_unico_fora_do_padrao_de_milhar_e_decimal():
    assert numero_br("3.14") == 3.14


# -- data_br -----------------------------------------------------------------


def test_data_br_formatos_texto():
    assert data_br("26/05/2026") == "2026-05-26"
    assert data_br("26-05-2026") == "2026-05-26"
    assert data_br("26.05.2026") == "2026-05-26"
    assert data_br("2026-05-26") == "2026-05-26"
    assert data_br("26/05/26") == "2026-05-26"


def test_data_br_objetos_date_e_datetime():
    assert data_br(dt.date(2026, 5, 26)) == "2026-05-26"
    assert data_br(dt.datetime(2026, 5, 26, 10, 30)) == "2026-05-26"


def test_data_br_serial_excel():
    # 2026-05-26 no sistema 1900 do Excel.
    assert data_br(46168) == "2026-05-26"


def test_data_br_invalidas_devolvem_none():
    assert data_br(None) is None
    assert data_br("") is None
    assert data_br("27/95/2026") is None
    assert data_br("amanhã") is None
    assert data_br(True) is None
    assert data_br(1) is None  # serial fora da faixa plausível
