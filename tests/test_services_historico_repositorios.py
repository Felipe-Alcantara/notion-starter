"""Um dia de trabalho quase nunca cabe num repositório só.

Estes testes fixam o que o relatório precisa: hora e duração por projeto (não
só a data), tolerância a repositório que sumiu do disco, e o aviso de que o
texto é factual — reconstruído do git, não a narrativa do dia.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from notion_starter.git_historico import Commit, DiaDeTrabalho
from notion_starter.services.historico_repositorios import (
    DiaConsolidado,
    Repositorio,
    TrabalhoNoRepositorio,
    _parsear_shortstat,
    consolidar_dias,
    corpo_markdown,
)


def _commit(hora: str, assunto: str, hash_curto: str = "abc1234") -> Commit:
    return Commit(
        hash_curto=hash_curto,
        data="2026-08-17",
        hora=hora,
        autor="Felipe Martin",
        assunto=assunto,
    )


def _trabalho(nome: str, *commits: Commit, estatisticas=None) -> TrabalhoNoRepositorio:
    return TrabalhoNoRepositorio(
        repositorio=nome,
        dia=DiaDeTrabalho(data="2026-08-17", commits=commits),
        estatisticas=estatisticas or {},
    )


# ------------------------------------------------------- resumo por repositório


def test_resumo_traz_hora_e_duracao_nao_so_o_dia():
    """'Trabalhei no dia 17' não diz se foram dez minutos ou seis horas."""

    trabalho = _trabalho("notion-starter", _commit("05:37", "a"), _commit("06:13", "b"))

    assert trabalho.resumo_de_uma_linha() == (
        "notion-starter: 2 commits entre 05:37 e 06:13 (duração: 36 min)."
    )


def test_commit_unico_informa_a_hora_e_omite_duracao():
    trabalho = _trabalho("hub", _commit("05:38", "a"))

    assert trabalho.resumo_de_uma_linha() == "hub: 1 commit às 05:38."


def test_duracao_longa_sai_em_horas():
    trabalho = _trabalho("app", _commit("09:50", "a"), _commit("11:25", "b"))

    assert "(duração: 1h35)" in trabalho.resumo_de_uma_linha()


def test_estatisticas_entram_no_resumo_quando_existem():
    trabalho = _trabalho(
        "app",
        _commit("10:00", "a", "aaa"),
        estatisticas={"aaa": (39, 2790, 33)},
    )

    assert "39 arquivos, +2790/-33 linhas" in trabalho.resumo_de_uma_linha()


# ----------------------------------------------------------- dia consolidado


def _dia() -> DiaConsolidado:
    return DiaConsolidado(
        data="2026-08-17",
        trabalhos=(
            _trabalho("cli", _commit("05:38", "feat: x"), _commit("06:14", "fix: y")),
            _trabalho("hub", _commit("05:40", "docs: z")),
        ),
    )


def test_dia_soma_os_commits_de_todos_os_repositorios():
    assert _dia().total_commits == 3


def test_janela_do_dia_atravessa_repositorios():
    dia = _dia()

    assert dia.primeira_hora == "05:38"
    assert dia.ultima_hora == "06:14"


def test_resumo_do_dia_tem_uma_frase_por_repositorio():
    resumo = _dia().resumo()

    assert resumo.count(" | ") == 1
    assert "cli: 2 commits" in resumo
    assert "hub: 1 commit" in resumo


def test_o_que_fiz_lista_cada_commit_com_hora():
    texto = _dia().o_que_fiz()

    assert "cli — 05:38 feat: x; 06:14 fix: y" in texto
    assert "hub — 05:40 docs: z" in texto


def test_data_por_extenso_usa_o_formato_dos_relatorios():
    assert _dia().data_por_extenso() == "17/08/2026"


# ------------------------------------------------------------------ markdown


def test_corpo_avisa_que_e_reconstruido_e_factual():
    """Sem o aviso, o leitor toma commit por narrativa completa do dia."""

    corpo = corpo_markdown(_dia())

    assert "Reconstruído a partir do histórico" in corpo
    assert "não viraram commit não aparecem" in corpo


def test_corpo_tem_uma_secao_por_repositorio_com_os_commits():
    corpo = corpo_markdown(_dia())

    assert "### cli" in corpo
    assert "### hub" in corpo
    assert "**05:38** `abc1234` feat: x" in corpo


def test_repositorio_com_mais_commits_abre_o_dia():
    dia = DiaConsolidado(
        data="2026-08-17",
        trabalhos=tuple(
            sorted(
                [
                    _trabalho("pouco", _commit("09:00", "a")),
                    _trabalho("muito", _commit("08:00", "a"), _commit("10:00", "b")),
                ],
                key=lambda t: (-t.dia.total, t.repositorio),
            )
        ),
    )

    assert dia.trabalhos[0].repositorio == "muito"


# ------------------------------------------------------------- shortstat


def test_parseia_shortstat_completo():
    saida = "@abc1234\n 39 files changed, 2790 insertions(+), 33 deletions(-)\n"

    assert _parsear_shortstat(saida) == {"abc1234": (39, 2790, 33)}


def test_shortstat_sem_delecao_nao_quebra():
    """O git omite a metade que é zero — formato irregular por natureza."""

    saida = "@abc1234\n 1 file changed, 25 insertions(+)\n"

    assert _parsear_shortstat(saida) == {"abc1234": (1, 25, 0)}


def test_commit_sem_estatistica_e_ignorado_em_vez_de_virar_zero_falso():
    saida = "@merge01\n@abc1234\n 2 files changed, 3 insertions(+)\n"

    resultado = _parsear_shortstat(saida)

    assert "merge01" not in resultado
    assert resultado["abc1234"] == (2, 3, 0)


# ------------------------------------------------------------- integração


def test_repositorio_inacessivel_e_pulado_e_nao_derruba_os_outros(tmp_path):
    """Numa lista de quinze, um caminho que mudou não pode custar os catorze."""

    real = tmp_path / "repo"
    real.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=real, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=real, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=real, check=True)
    (real / "a.txt").write_text("oi")
    subprocess.run(["git", "add", "-A"], cwd=real, check=True)
    subprocess.run(["git", "commit", "-qm", "feat: primeiro"], cwd=real, check=True)

    dias = consolidar_dias(
        [
            Repositorio.de_par("some", Path(tmp_path / "nao-existe")),
            Repositorio.de_par("real", real),
        ]
    )

    assert len(dias) == 1
    assert dias[0].repositorios == ("real",)


def test_lista_vazia_devolve_nenhum_dia():
    assert consolidar_dias([]) == []


def test_repositorio_sem_commit_no_recorte_nao_vira_dia(tmp_path):
    repo = tmp_path / "vazio"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    assert consolidar_dias([Repositorio.de_par("vazio", repo)]) == []


@pytest.mark.parametrize("com_estatisticas", [True, False])
def test_coleta_funciona_com_e_sem_estatisticas(tmp_path, com_estatisticas):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a.txt").write_text("uma linha\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feat: x"], cwd=repo, check=True)

    dias = consolidar_dias(
        [Repositorio.de_par("repo", repo)], com_estatisticas=com_estatisticas
    )

    assert dias[0].total_commits == 1
    tem_stat = bool(dias[0].trabalhos[0].estatisticas)
    assert tem_stat is com_estatisticas


# ------------------------------------------------------------- descoberta


def test_descoberta_acha_repositorio_e_submodulo(tmp_path):
    """Listar à mão só acha o que já se lembra; o esquecido não está na lista."""

    from notion_starter.services.historico_repositorios import descobrir_repositorios

    (tmp_path / "projeto-a" / ".git").mkdir(parents=True)
    (tmp_path / "hub" / "modules" / "lib" / ".git").mkdir(parents=True)
    (tmp_path / "hub" / ".git").mkdir(parents=True)

    nomes = [repo.nome for repo in descobrir_repositorios(tmp_path)]

    assert nomes == ["hub", "lib", "projeto-a"]


def test_descoberta_ignora_pasta_de_dependencia(tmp_path):
    from notion_starter.services.historico_repositorios import descobrir_repositorios

    (tmp_path / "node_modules" / "pacote" / ".git").mkdir(parents=True)
    (tmp_path / "meu-app" / ".git").mkdir(parents=True)

    nomes = [repo.nome for repo in descobrir_repositorios(tmp_path)]

    assert nomes == ["meu-app"]


def test_descoberta_respeita_a_profundidade(tmp_path):
    from notion_starter.services.historico_repositorios import descobrir_repositorios

    (tmp_path / "a" / "b" / "c" / "fundo" / ".git").mkdir(parents=True)

    assert descobrir_repositorios(tmp_path, profundidade=3) == []
    assert len(descobrir_repositorios(tmp_path, profundidade=4)) == 1


def test_descoberta_de_pasta_inexistente_e_lista_vazia_nao_erro(tmp_path):
    from notion_starter.services.historico_repositorios import descobrir_repositorios

    assert descobrir_repositorios(tmp_path / "nao-existe") == []


def test_git_como_arquivo_tambem_conta_como_repositorio(tmp_path):
    """Submódulo e worktree têm `.git` como ARQUIVO, não pasta."""

    from notion_starter.services.historico_repositorios import descobrir_repositorios

    (tmp_path / "submodulo").mkdir()
    (tmp_path / "submodulo" / ".git").write_text("gitdir: ../.git/modules/sub")

    assert [r.nome for r in descobrir_repositorios(tmp_path)] == ["submodulo"]
