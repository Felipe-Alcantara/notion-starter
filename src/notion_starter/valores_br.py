"""Normalização de valores no formato brasileiro.

Planilhas brasileiras trazem números com ponto de milhar e vírgula decimal
(``1.614`` é mil seiscentos e quatorze; ``2,7 mil`` é 2700) e datas em vários
formatos (``dd/mm/aaaa``, serial do Excel…). Estas funções puras convertem
esses valores para tipos Python previsíveis **antes** de tocar o Notion.

Regra de ouro herdada das migrações reais: valor ambíguo ou inválido devolve
``None`` — quem chama decide preservar o texto original (ex.: numa propriedade
"Observações") em vez de gravar um dado errado.
"""

from __future__ import annotations

import datetime as _dt
import re

#: Multiplicadores aceitos como sufixo textual de números ("2,7 mil" -> 2700).
_MULTIPLICADORES = {
    "mil": 1_000,
    "mi": 1_000_000,
    "milhao": 1_000_000,
    "milhão": 1_000_000,
    "milhoes": 1_000_000,
    "milhões": 1_000_000,
    "bi": 1_000_000_000,
    "bilhao": 1_000_000_000,
    "bilhão": 1_000_000_000,
    "bilhoes": 1_000_000_000,
    "bilhões": 1_000_000_000,
}

_FORMATOS_DATA = (
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d.%m.%Y",
)

#: Época do serial de datas do Excel (sistema 1900, com o bug do ano bissexto
#: já compensado: o serial 1 é 1900-01-01, e o Excel conta 1900 como bissexto).
_EPOCA_EXCEL = _dt.date(1899, 12, 30)

#: Faixa plausível de seriais Excel aceitos (1930–2100, aproximadamente).
_SERIAL_EXCEL_MIN = 10_959
_SERIAL_EXCEL_MAX = 73_415


def numero_br(valor: str | int | float | None) -> int | float | None:
    """Converte um número em formato brasileiro para ``int``/``float``.

    Trata ponto como separador de milhar e vírgula como decimal, e aceita os
    sufixos textuais ``mil``, ``mi``/``milhões`` e ``bi``/``bilhões``.

    Exemplos: ``"1.614"`` → ``1614``; ``"1.234,56"`` → ``1234.56``;
    ``"2,7 mil"`` → ``2700``; ``"R$ 1.200"`` → ``1200``.

    Args:
        valor: Texto (ou número já convertido) vindo da fonte.

    Returns:
        ``int`` quando o resultado é inteiro, ``float`` caso contrário, ou
        ``None`` se o valor não é um número reconhecível.
    """

    if valor is None:
        return None
    if isinstance(valor, bool):  # bool é subclasse de int; não é número de planilha
        return None
    if isinstance(valor, (int, float)):
        return valor

    texto = str(valor).strip().lower()
    if not texto:
        return None
    texto = re.sub(r"^r\$\s*", "", texto)

    multiplicador = 1
    partes = texto.rsplit(" ", 1)
    if len(partes) == 2 and partes[1] in _MULTIPLICADORES:
        texto, sufixo = partes[0].strip(), partes[1]
        multiplicador = _MULTIPLICADORES[sufixo]

    if not re.fullmatch(r"-?[\d.,]+", texto):
        return None

    # Vírgula presente: é o decimal; pontos são milhar.
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    # Só pontos: milhar quando o padrão bate (grupos de 3); senão, ambíguo
    # demais para adivinhar — trata como milhar somente se plausível.
    elif "." in texto:
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
            texto = texto.replace(".", "")
        elif texto.count(".") > 1:
            return None
        # um único ponto fora do padrão de milhar: decimal em formato neutro

    try:
        resultado = float(texto) * multiplicador
    except ValueError:
        return None
    if resultado.is_integer():
        return int(resultado)
    return resultado


def data_br(
    valor: str | int | float | _dt.date | _dt.datetime | None,
) -> str | None:
    """Converte uma data em formato brasileiro (ou serial Excel) para ISO.

    Aceita ``dd/mm/aaaa``, ``dd/mm/aa``, ``dd-mm-aaaa``, ``dd.mm.aaaa``,
    ``aaaa-mm-dd``, objetos ``date``/``datetime`` e o serial numérico do Excel.

    Args:
        valor: Valor bruto vindo da fonte.

    Returns:
        A data em ``YYYY-MM-DD``, ou ``None`` para valores inválidos (ex.:
        ``27/95/2026``) — preserve o texto original em vez de gravar data errada.
    """

    if valor is None:
        return None
    if isinstance(valor, _dt.datetime):
        return valor.date().isoformat()
    if isinstance(valor, _dt.date):
        return valor.isoformat()
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        serial = int(valor)
        if _SERIAL_EXCEL_MIN <= serial <= _SERIAL_EXCEL_MAX:
            return (_EPOCA_EXCEL + _dt.timedelta(days=serial)).isoformat()
        return None

    texto = str(valor).strip()
    if not texto:
        return None
    for formato in _FORMATOS_DATA:
        try:
            return _dt.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    return None
