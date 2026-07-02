"""Gera um relatório HTML navegável a partir do ``mapa.json``.

Lê o mapa coletado por ``coletar_mapa.py`` e produz um ``mapa.html`` standalone
(sem dependências externas): uma árvore expansível do workspace mais seções de
destaque — duplicatas por nome, ranking de databases por nº de linhas, itens
vazios e órfãos. Abra o arquivo no navegador.

Execução:
    python examples/gerar_arvore_html.py [mapa.json] [mapa.html]
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ENTRADA_PADRAO = Path("mapa.json")
SAIDA_PADRAO = Path("mapa.html")


def _carregar(entrada: Path) -> dict:
    if not entrada.exists():
        raise SystemExit(f"{entrada} não encontrado. Rode antes: python examples/coletar_mapa.py")
    return json.loads(entrada.read_text(encoding="utf-8"))


def _indexar(mapa: dict) -> tuple[dict[str, dict], dict[str, list[str]], list[str]]:
    """Devolve (itens por id, filhos por id-pai, ids raiz)."""

    itens = {item["id"]: item for item in mapa["itens"]}
    filhos: dict[str, list[str]] = {}
    raizes: list[str] = []

    for item in mapa["itens"]:
        pai = item.get("parent_id")
        if pai and pai in itens:
            filhos.setdefault(pai, []).append(item["id"])
        else:
            raizes.append(item["id"])

    def chave(item_id: str) -> str:
        return itens[item_id]["titulo"].lower()

    for lista in filhos.values():
        lista.sort(key=chave)
    raizes.sort(key=chave)
    return itens, filhos, raizes


def _render_no(
    item_id: str,
    itens: dict[str, dict],
    filhos: dict[str, list[str]],
    linhas_db: dict[str, int],
) -> str:
    item = itens[item_id]
    titulo = html.escape(item["titulo"])
    is_db = item["tipo"] == "database"
    icone = "🗃️" if is_db else "📄"

    sufixo = ""
    if is_db:
        n = linhas_db.get(item_id, -1)
        if n >= 0:
            sufixo = f' <span class="badge">{n} linhas</span>'
        else:
            sufixo = ' <span class="badge sem">? linhas</span>'

    link = ""
    if item.get("url"):
        link = f' <a href="{html.escape(item["url"])}" target="_blank" class="link">↗</a>'

    sub = filhos.get(item_id, [])
    rotulo = f"{icone} {titulo}{sufixo}{link}"

    if not sub:
        return f'<li class="leaf">{rotulo}</li>'

    filhos_html = "\n".join(_render_no(f, itens, filhos, linhas_db) for f in sub)
    return (
        f"<li><details><summary>{rotulo} "
        f'<span class="count">({len(sub)})</span></summary>\n'
        f"<ul>\n{filhos_html}\n</ul></details></li>"
    )


def _secao_duplicatas(mapa: dict, itens: dict[str, dict]) -> str:
    dups = mapa.get("duplicatas", {})
    if not dups:
        return "<p>Nenhuma duplicata por nome. 🎉</p>"
    linhas = []
    for titulo, ids in sorted(dups.items(), key=lambda kv: -len(kv[1])):
        linhas.append(f"<li><b>{html.escape(titulo)}</b> — {len(ids)} itens</li>")
    return f"<ul>{''.join(linhas)}</ul>"


def _secao_ranking(mapa: dict, itens: dict[str, dict]) -> str:
    linhas_db = mapa.get("linhas_por_database", {})
    ranking = sorted(
        ((itens[i]["titulo"], n) for i, n in linhas_db.items() if i in itens),
        key=lambda t: -t[1],
    )
    if not ranking:
        return "<p>Sem databases.</p>"
    linhas = [
        f"<tr><td>{html.escape(nome)}</td><td>{n if n >= 0 else '?'}</td></tr>"
        for nome, n in ranking
    ]
    return f"<table><tr><th>Database</th><th>Linhas</th></tr>{''.join(linhas)}</table>"


def _secao_orfaos(mapa: dict, itens: dict[str, dict]) -> str:
    orfaos = [i for i in mapa.get("orfaos", []) if i in itens]
    if not orfaos:
        return "<p>Nenhum órfão. 🎉</p>"
    linhas = [f"<li>{html.escape(itens[i]['titulo'])}</li>" for i in orfaos]
    return f"<ul>{''.join(linhas)}</ul>"


def gerar_html(mapa: dict) -> str:
    itens, filhos, raizes = _indexar(mapa)
    linhas_db = mapa.get("linhas_por_database", {})

    arvore = "\n".join(_render_no(r, itens, filhos, linhas_db) for r in raizes)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mapa do Workspace Notion</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: system-ui, sans-serif; background:#1a1a1a; color:#e0e0e0;
         margin:0; padding:2rem; line-height:1.5; }}
  h1 {{ margin-top:0; }}
  .resumo {{ display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1.5rem; }}
  .card {{ background:#252525; border:1px solid #3a3a3a; border-radius:8px;
          padding:.75rem 1.25rem; }}
  .card b {{ font-size:1.5rem; display:block; color:#8a7fff; }}
  details {{ margin:.15rem 0; }}
  summary {{ cursor:pointer; padding:.1rem .25rem; border-radius:4px; }}
  summary:hover {{ background:#2d2d2d; }}
  ul {{ list-style:none; padding-left:1.25rem; border-left:1px solid #333;
       margin:.1rem 0; }}
  li.leaf {{ padding:.1rem .25rem; }}
  .badge {{ background:#2d4a2d; color:#9fe09f; border-radius:10px;
           padding:0 .5rem; font-size:.75rem; }}
  .badge.sem {{ background:#4a2d2d; color:#e09f9f; }}
  .count {{ color:#888; font-size:.8rem; }}
  .link {{ text-decoration:none; opacity:.6; }}
  .link:hover {{ opacity:1; }}
  section {{ background:#222; border:1px solid #333; border-radius:8px;
            padding:1rem 1.5rem; margin:1rem 0; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ text-align:left; padding:.3rem .6rem; border-bottom:1px solid #333; }}
  details.dest > summary {{ font-weight:bold; font-size:1.1rem; }}
</style>
</head>
<body>
<h1>🗺️ Mapa do Workspace Notion</h1>
<div class="resumo">
  <div class="card"><b>{mapa["total_paginas"]}</b> páginas</div>
  <div class="card"><b>{mapa["total_databases"]}</b> databases</div>
  <div class="card"><b>{len(mapa.get("duplicatas", {}))}</b> nomes duplicados</div>
  <div class="card"><b>{len(mapa.get("orfaos", []))}</b> órfãos</div>
</div>

<section><details class="dest" open><summary>📑 Duplicatas por nome</summary>
{_secao_duplicatas(mapa, itens)}</details></section>

<section><details class="dest"><summary>📊 Databases por tamanho</summary>
{_secao_ranking(mapa, itens)}</details></section>

<section><details class="dest"><summary>🔗 Órfãos (parent não visível)</summary>
{_secao_orfaos(mapa, itens)}</details></section>

<h2>🌳 Árvore do workspace</h2>
<ul>
{arvore}
</ul>
</body>
</html>
"""


def main(entrada: Path, saida: Path) -> None:
    mapa = _carregar(entrada)
    saida.write_text(gerar_html(mapa), encoding="utf-8")
    print(f"HTML gerado em {saida}. Abra no navegador.", file=sys.stderr)


if __name__ == "__main__":
    ent = Path(sys.argv[1]) if len(sys.argv) > 1 else ENTRADA_PADRAO
    sai = Path(sys.argv[2]) if len(sys.argv) > 2 else SAIDA_PADRAO
    main(ent, sai)
