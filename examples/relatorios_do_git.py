"""Publica um relatório por dia de trabalho, lido do histórico de um repositório git.

Idempotente: dias que já têm relatório no database recebem o conteúdo novo
anexado, em vez de virar linha duplicada — um mesmo dia pode acumular trabalho
de mais de um projeto.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/relatorios_do_git.py <DATABASE_ID> <CAMINHO_DO_REPO>
    python examples/relatorios_do_git.py <DATABASE_ID> . --desde 2026-07-01
    python examples/relatorios_do_git.py <DATABASE_ID> . --simular

O corpo gerado é factual (a lista de commits do dia): serve como base para
quem depois complementa o relatório com a narrativa — por que algo foi feito,
o que ficou pendente. Para publicar um texto escrito à mão, use
``notion_starter.services.relatorios_diarios`` diretamente, montando cada
``RelatorioDiario`` com o corpo desejado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from notion_starter import git_historico, properties
from notion_starter.services.relatorios_diarios import RelatorioDiario, publicar_relatorios


def montar_relatorios(
    repositorio: Path,
    *,
    nome_projeto: str,
    desde: str,
    ate: str,
    autor: str,
    propriedade_resumo: str,
) -> list[RelatorioDiario]:
    """Converte cada dia de trabalho do repositório em um relatório."""
    relatorios: list[RelatorioDiario] = []
    for dia in git_historico.dias_de_trabalho(repositorio, desde=desde, ate=ate, autor=autor):
        plural = "commit" if dia.total == 1 else "commits"
        resumo = (
            f"{nome_projeto}: {dia.total} {plural} entre {dia.primeira_hora} e {dia.ultima_hora}."
        )
        relatorios.append(
            RelatorioDiario(
                data=dia.data,
                corpo_markdown=git_historico.resumo_markdown(dia, titulo=nome_projeto),
                propriedades={propriedade_resumo: properties.rich_text(resumo)},
            )
        )
    return relatorios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database_id", help="database que guarda os relatórios")
    parser.add_argument("repositorio", help="caminho do repositório git")
    parser.add_argument("--desde", default="", help="data ISO inicial (inclusiva)")
    parser.add_argument("--ate", default="", help="data ISO final (inclusiva)")
    parser.add_argument("--autor", default="", help="filtra commits por autor")
    parser.add_argument("--projeto", default="", help="nome exibido (padrão: pasta do repo)")
    parser.add_argument("--propriedade-data", default="Data", help="coluna de data do database")
    parser.add_argument("--propriedade-resumo", default="Resumo", help="coluna de resumo")
    parser.add_argument(
        "--simular",
        action="store_true",
        help="mostra o que seria publicado, sem escrever no Notion",
    )
    args = parser.parse_args(argv)

    repositorio = Path(args.repositorio).expanduser().resolve()
    nome_projeto = args.projeto or repositorio.name

    try:
        relatorios = montar_relatorios(
            repositorio,
            nome_projeto=nome_projeto,
            desde=args.desde,
            ate=args.ate,
            autor=args.autor,
            propriedade_resumo=args.propriedade_resumo,
        )
    except git_historico.GitIndisponivelError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    if not relatorios:
        print("Nenhum commit no período informado.")
        return 0

    if args.simular:
        print(f"{len(relatorios)} dia(s) seriam publicados em {nome_projeto}:")
        for relatorio in relatorios:
            primeira_linha = relatorio.corpo_markdown.splitlines()[0]
            print(f"  {relatorio.data}  {primeira_linha}")
        return 0

    resultado = publicar_relatorios(
        args.database_id,
        relatorios,
        propriedade_data=args.propriedade_data,
    )
    for item in resultado.relatorios:
        destino = item.url or item.page_id
        print(f"  {item.data}  {item.acao:<14} {item.blocos_escritos:>3} bloco(s)  {destino}")
    print(f"{resultado.criadas} criada(s), {resultado.complementadas} complementada(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
