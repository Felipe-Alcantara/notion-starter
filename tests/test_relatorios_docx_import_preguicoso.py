"""Importar o módulo de DOCX não pode carregar python-docx/lxml.

Todo comando da CLI importa este módulo; com o import no topo, python-docx e
lxml custavam ~100 ms de abertura mesmo em quem nunca exporta DOCX.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _rodar(codigo: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(SRC)!r}); {codigo}"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_importar_o_modulo_nao_carrega_docx_nem_lxml():
    resultado = _rodar(
        "import notion_starter.services.relatorios_docx; "
        "print('docx' in sys.modules, 'lxml' in sys.modules)"
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "False False"


def test_sem_python_docx_so_a_renderizacao_falha(tmp_path):
    resultado = _rodar(
        "sys.modules['docx'] = None; "
        "from notion_starter.services import relatorios_docx as r; "
        f"r.renderizar_docx({str(tmp_path / 'x.docx')!r}, titulo='T', "
        "data_relatorio='2026-09-26', propriedades={}, markdown='oi')"
    )

    assert resultado.returncode != 0
    assert "python-docx" in resultado.stderr


def test_renderizar_carrega_docx_sob_demanda(tmp_path):
    pytest.importorskip("docx")
    from notion_starter.services import relatorios_docx as r

    destino = r.renderizar_docx(
        tmp_path / "rel.docx",
        titulo="T",
        data_relatorio="2026-09-26",
        propriedades={"Status": "Concluído"},
        markdown="| a | b |\n| --- | --- |\n| 1 | 2 |",
    )

    assert destino.is_file()
    assert r.Document is not None
