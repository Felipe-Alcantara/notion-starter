"""Limites documentados da API aplicados antes de enviar qualquer bloco.

https://developers.notion.com/reference/request-limits: todo array (de blocos
ou de rich text) com até 100 elementos, links com até 2000 caracteres e cada
requisição com até 1000 elementos de bloco e 500 KB. Passar disso é HTTP 400 —
e, numa substituição, o 400 chegava depois de o corpo antigo já ter sido
apagado.
"""

from __future__ import annotations

import pytest

from notion_starter.content import markdown_para_blocos, planejar_lotes, validar_blocos
from notion_starter.exceptions import ConteudoInvalidoError


def test_celula_de_tabela_com_trechos_demais_e_recusada():
    celula = " ".join(f"`c{i}`" for i in range(60))
    with pytest.raises(ConteudoInvalidoError, match="coluna 1"):
        validar_blocos(markdown_para_blocos(f"| {celula} | b |\n| --- | --- |\n| x | y |"))


def test_cem_tabelas_de_dez_linhas_viram_mais_de_um_lote():
    """100 blocos de topo, mas 1100 elementos: a API recusa num lote só."""

    tabela = "| a | b |\n| --- | --- |\n" + "\n".join(f"| {i} | x |" for i in range(9))
    blocos = markdown_para_blocos("\n\n".join([tabela] * 100))
    assert len(blocos) == 100

    lotes = planejar_lotes(blocos)

    assert len(lotes) >= 2
    for lote in lotes:
        assert sum(1 + len(b["table"]["children"]) for b in lote) <= 1000


def test_lotes_simples_continuam_de_100():
    blocos = markdown_para_blocos("\n\n".join(f"linha {i}" for i in range(250)))
    assert [len(lote) for lote in planejar_lotes(blocos)] == [100, 100, 50]


def test_link_acima_de_2000_caracteres_fica_so_texto():
    url = "https://x.com/" + "a" * 2000
    item = markdown_para_blocos(f"[site]({url})")[0]["paragraph"]["rich_text"][0]
    assert "link" not in item["text"]


def test_codigo_gigante_vira_varios_blocos_de_codigo():
    texto = "x" * (2000 * 150)
    blocos = markdown_para_blocos(f"```python\n{texto}\n```")
    assert [b["type"] for b in blocos] == ["code", "code"]
    assert all(len(b["code"]["rich_text"]) <= 100 for b in blocos)
    assert all(b["code"]["language"] == "python" for b in blocos)
    validar_blocos(blocos)
