"""Onde e como gravar os backups em JSON que as operações destrutivas deixam.

Um backup guarda **conteúdo do workspace** (texto dos blocos, IDs de quem
criou). Por isso ele nunca vai para o diretório corrente: quem roda a CLI de
dentro de um repositório git acabava versionando — e publicando — esses JSON.
A pasta padrão fica no diretório de estado do usuário, fora de qualquer
repositório, e é criada só para o dono (``0o700``; arquivos ``0o600`` em
sistemas POSIX).

Ordem de resolução da pasta:

1. a variável de ambiente ``NOTION_AUTOMACOES_BACKUP_DIR``;
2. no Windows, ``%LOCALAPPDATA%`` (ou ``%APPDATA%``) ``\\notion-automacoes\\backups``;
3. nos demais, ``${XDG_STATE_HOME:-~/.local/state}/notion-automacoes/backups``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Variável de ambiente que escolhe a pasta de backups explicitamente.
VARIAVEL_DIRETORIO_BACKUP = "NOTION_AUTOMACOES_BACKUP_DIR"

_PASTA_APP = "notion-automacoes"


def resolver_diretorio_backup(
    ambiente: Mapping[str, str],
    *,
    windows: bool,
    home: Path,
) -> Path:
    """Regra pura de escolha da pasta de backups (ver o docstring do módulo).

    Args:
        ambiente: Variáveis de ambiente a considerar.
        windows: Se a plataforma é Windows.
        home: Pasta pessoal do usuário (fallback final).

    Returns:
        A pasta absoluta onde os backups devem ser gravados.
    """

    explicita = (ambiente.get(VARIAVEL_DIRETORIO_BACKUP) or "").strip()
    if explicita:
        return Path(explicita).expanduser().resolve()
    if windows:
        base_windows = ambiente.get("LOCALAPPDATA") or ambiente.get("APPDATA")
        if base_windows:
            return (Path(base_windows) / _PASTA_APP / "backups").resolve()
    estado = (ambiente.get("XDG_STATE_HOME") or "").strip()
    base = Path(estado) if estado else home / ".local" / "state"
    return (base / _PASTA_APP / "backups").resolve()


def diretorio_backup_padrao() -> Path:
    """A pasta de backups deste usuário, resolvida na hora da chamada."""

    return resolver_diretorio_backup(os.environ, windows=os.name == "nt", home=Path.home())


def salvar_backup_json(
    dados: Any,
    *,
    prefixo: str,
    diretorio: Path | str | None = None,
) -> Path:
    """Grava ``dados`` como JSON num arquivo novo e devolve o caminho **absoluto**.

    Args:
        dados: Conteúdo serializável (ex.: o bloco lido da API).
        prefixo: Início do nome do arquivo (ex.: ``bloco-<id>``).
        diretorio: Pasta explícita; ``None`` usa :func:`diretorio_backup_padrao`.

    Returns:
        O caminho absoluto do arquivo gravado.
    """

    pasta = Path(diretorio).expanduser() if diretorio is not None else diretorio_backup_padrao()
    pasta = pasta.resolve()
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    caminho = pasta / f"{prefixo}-{carimbo}.json"
    sequencia = 1
    while caminho.exists():
        sequencia += 1
        caminho = pasta / f"{prefixo}-{carimbo}-{sequencia}.json"
    descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(dados, ensure_ascii=False, indent=2))
    return caminho
