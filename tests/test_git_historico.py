"""Testes da leitura do histórico git agrupado por dia."""

from __future__ import annotations

import subprocess

import pytest

from notion_starter import git_historico as gh


def _git(repositorio, *argumentos, env=None):
    subprocess.run(
        ["git", "-C", str(repositorio), *argumentos],
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def repositorio(tmp_path):
    """Repositório real com commits em dois dias distintos."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    _git(raiz, "init", "-q")
    _git(raiz, "config", "user.email", "dev@example.com")
    _git(raiz, "config", "user.name", "Dev de Teste")

    import os

    def commit(mensagem: str, quando: str, arquivo: str) -> None:
        (raiz / arquivo).write_text(mensagem, encoding="utf-8")
        _git(raiz, "add", arquivo)
        ambiente = {
            **os.environ,
            "GIT_AUTHOR_DATE": quando,
            "GIT_COMMITTER_DATE": quando,
        }
        _git(raiz, "commit", "-q", "-m", mensagem, env=ambiente)

    commit("feat: primeiro", "2026-07-20T09:00:00", "a.txt")
    commit("fix: segundo", "2026-07-20T14:30:00", "b.txt")
    commit("docs: outro dia", "2026-07-22T08:15:00", "c.txt")
    return raiz


class TestColetarCommits:
    def test_le_commits_do_mais_antigo_para_o_mais_recente(self, repositorio):
        commits = gh.coletar_commits(repositorio)
        assert [c.assunto for c in commits] == [
            "feat: primeiro",
            "fix: segundo",
            "docs: outro dia",
        ]

    def test_extrai_data_hora_e_autor(self, repositorio):
        primeiro = gh.coletar_commits(repositorio)[0]
        assert primeiro.data == "2026-07-20"
        assert primeiro.hora == "09:00"
        assert primeiro.autor == "Dev de Teste"
        assert primeiro.hash_curto

    def test_recorta_por_intervalo_de_datas(self, repositorio):
        commits = gh.coletar_commits(repositorio, desde="2026-07-22", ate="2026-07-22")
        assert [c.assunto for c in commits] == ["docs: outro dia"]

    def test_filtra_por_autor(self, repositorio):
        assert gh.coletar_commits(repositorio, autor="Dev de Teste")
        assert gh.coletar_commits(repositorio, autor="Ninguém") == []

    def test_caminho_sem_repositorio_git_falha_com_erro_claro(self, tmp_path):
        with pytest.raises(gh.GitIndisponivelError):
            gh.coletar_commits(tmp_path)

    def test_mensagem_com_caractere_especial_nao_quebra_o_parsing(self, repositorio):
        _git(repositorio, "commit", "-q", "--allow-empty", "-m", "fix: usa | pipe e \x1f byte")
        assuntos = [c.assunto for c in gh.coletar_commits(repositorio)]
        assert any("pipe" in assunto for assunto in assuntos)


class TestAgruparPorDia:
    def test_agrupa_commits_por_data_em_ordem(self, repositorio):
        dias = gh.dias_de_trabalho(repositorio)
        assert [d.data for d in dias] == ["2026-07-20", "2026-07-22"]
        assert [d.total for d in dias] == [2, 1]

    def test_expoe_primeira_e_ultima_hora_do_dia(self, repositorio):
        dia = gh.dias_de_trabalho(repositorio)[0]
        assert dia.primeira_hora == "09:00"
        assert dia.ultima_hora == "14:30"

    def test_lista_autores_sem_repeticao(self, repositorio):
        assert gh.dias_de_trabalho(repositorio)[0].autores == ("Dev de Teste",)

    def test_sem_commits_devolve_lista_vazia(self):
        assert gh.agrupar_por_dia([]) == []

    def test_data_por_extenso_usa_formato_brasileiro(self):
        dia = gh.DiaDeTrabalho(data="2026-07-24")
        assert dia.data_por_extenso() == "24/07/2026"


class TestResumoMarkdown:
    def test_lista_os_commits_com_hora_e_hash(self, repositorio):
        markdown = gh.resumo_markdown(gh.dias_de_trabalho(repositorio)[0])
        assert "## Commits de 20/07/2026" in markdown
        assert "2 commits, das 09:00 às 14:30." in markdown
        assert "09:00 feat: primeiro" in markdown

    def test_aceita_titulo_personalizado(self, repositorio):
        markdown = gh.resumo_markdown(gh.dias_de_trabalho(repositorio)[0], titulo="Meu projeto")
        assert markdown.startswith("## Meu projeto")

    def test_dia_com_um_commit_usa_singular(self, repositorio):
        markdown = gh.resumo_markdown(gh.dias_de_trabalho(repositorio)[1])
        assert "1 commit," in markdown
