"""A pasta de backups sai do diretório corrente e segue a convenção de cada SO."""

from __future__ import annotations

from pathlib import Path

from notion_starter.services.backups import resolver_diretorio_backup, salvar_backup_json


def test_variavel_de_ambiente_vence(tmp_path):
    pasta = resolver_diretorio_backup(
        {"NOTION_AUTOMACOES_BACKUP_DIR": str(tmp_path / "x"), "XDG_STATE_HOME": "/nao"},
        windows=False,
        home=tmp_path,
    )
    assert pasta == (tmp_path / "x").resolve()


def test_xdg_state_home_no_posix(tmp_path):
    pasta = resolver_diretorio_backup(
        {"XDG_STATE_HOME": str(tmp_path / "estado")}, windows=False, home=tmp_path
    )
    assert pasta == (tmp_path / "estado" / "notion-automacoes" / "backups").resolve()


def test_padrao_posix_em_local_state(tmp_path):
    pasta = resolver_diretorio_backup({}, windows=False, home=tmp_path)
    assert pasta == (tmp_path / ".local" / "state" / "notion-automacoes" / "backups").resolve()


def test_windows_usa_localappdata(tmp_path):
    pasta = resolver_diretorio_backup(
        {"LOCALAPPDATA": str(tmp_path / "Local")}, windows=True, home=tmp_path
    )
    assert pasta == (tmp_path / "Local" / "notion-automacoes" / "backups").resolve()


def test_salvar_nao_sobrescreve_backup_do_mesmo_segundo(tmp_path):
    primeiro = salvar_backup_json({"a": 1}, prefixo="bloco-x", diretorio=tmp_path)
    segundo = salvar_backup_json({"a": 2}, prefixo="bloco-x", diretorio=tmp_path)

    assert primeiro != segundo
    assert Path(primeiro).is_absolute() and Path(segundo).is_file()
