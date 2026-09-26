"""A versão exposta pelo módulo é a mesma do pacote que o PyPI publica."""

from __future__ import annotations

import sys
from pathlib import Path

import notion_starter

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: o pytest já instala o tomli nessa versão.
    import tomli as tomllib

RAIZ = Path(__file__).resolve().parents[1]


def test_versao_do_modulo_e_a_do_pyproject():
    """Os consumidores declaram a faixa pela versão do pacote e conferem a
    instalada por ``notion_starter.__version__``; subir só uma das duas faz a
    conferência mentir sobre quais APIs estão disponíveis."""

    dados = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert notion_starter.__version__ == dados["project"]["version"]
