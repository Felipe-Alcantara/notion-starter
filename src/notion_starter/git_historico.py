"""Leitura do histórico de um repositório git, agrupado por dia.

Módulo **puro**: não conhece Notion nem rede — só executa ``git`` e devolve
estruturas de dados. Isso mantém a coleta testável sem workspace e permite
reaproveitar o mesmo histórico para outros destinos (relatório em arquivo,
planilha, e-mail) sem arrastar junto a camada de publicação.

O caso de uso que motivou o módulo é reconstruir o que foi feito em cada dia de
trabalho a partir do que ficou registrado no repositório — útil quando o
relatório é escrito depois, e a memória do dia já se perdeu.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

#: Separador improvável de aparecer em uma mensagem de commit.
_CAMPO = "\x1f"
_LINHA = "\x1e"
#: Um repositório grande pode ter histórico longo; o teto evita varreduras
#: acidentais de anos inteiros quando nenhum recorte é informado.
_TIMEOUT_SEGUNDOS = 120


class GitIndisponivelError(RuntimeError):
    """O caminho não é um repositório git válido ou o binário não existe."""


@dataclass(frozen=True)
class Commit:
    """Um commit, reduzido ao que interessa para escrever um relatório."""

    hash_curto: str
    data: str  # ISO (AAAA-MM-DD), no fuso local do commit
    hora: str  # HH:MM
    autor: str
    assunto: str

    @property
    def descricao(self) -> str:
        return f"{self.hora} {self.assunto}"


@dataclass(frozen=True)
class DiaDeTrabalho:
    """Todos os commits de um mesmo dia, em ordem cronológica."""

    data: str  # ISO (AAAA-MM-DD)
    commits: tuple[Commit, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.commits)

    @property
    def primeira_hora(self) -> str:
        return self.commits[0].hora if self.commits else ""

    @property
    def ultima_hora(self) -> str:
        return self.commits[-1].hora if self.commits else ""

    @property
    def autores(self) -> tuple[str, ...]:
        vistos = dict.fromkeys(commit.autor for commit in self.commits)
        return tuple(vistos)

    def data_por_extenso(self) -> str:
        """``2026-07-24`` vira ``24/07/2026`` — o formato usado nos relatórios."""
        ano, mes, dia = self.data.split("-")
        return f"{dia}/{mes}/{ano}"


def _executar_git(repositorio: Path, argumentos: list[str]) -> str:
    try:
        resultado = subprocess.run(
            ["git", "-C", str(repositorio), *argumentos],
            capture_output=True,
            text=True,
            check=True,
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except FileNotFoundError as erro:  # git não instalado
        raise GitIndisponivelError("O binário 'git' não está disponível no PATH.") from erro
    except subprocess.CalledProcessError as erro:
        detalhe = (erro.stderr or "").strip()[:300]
        raise GitIndisponivelError(f"git falhou em {repositorio}: {detalhe}") from erro
    except subprocess.SubprocessError as erro:
        raise GitIndisponivelError(f"git não respondeu em {repositorio}: {erro}") from erro
    return resultado.stdout


def coletar_commits(
    repositorio: Path | str,
    *,
    desde: str = "",
    ate: str = "",
    autor: str = "",
) -> list[Commit]:
    """Lê os commits do repositório, do mais antigo para o mais recente.

    Args:
        repositorio: Caminho do repositório git.
        desde: Data ISO inicial (inclusiva), ou vazio para não limitar.
        ate: Data ISO final (inclusiva), ou vazio para não limitar.
        autor: Filtra por autor (casamento parcial, como ``git --author``).

    Raises:
        GitIndisponivelError: Caminho inválido, sem git, ou comando falhou.
    """
    caminho = Path(repositorio)
    formato = _CAMPO.join(["%h", "%ad", "%an", "%s"]) + _LINHA
    argumentos = ["log", "--reverse", f"--pretty=format:{formato}", "--date=format:%Y-%m-%d %H:%M"]
    if desde:
        argumentos.append(f"--since={desde} 00:00:00")
    if ate:
        argumentos.append(f"--until={ate} 23:59:59")
    if autor:
        argumentos.append(f"--author={autor}")

    saida = _executar_git(caminho, argumentos)
    commits: list[Commit] = []
    for registro in saida.split(_LINHA):
        if not registro.strip():
            continue
        # O assunto é o último campo e pode conter o próprio separador (nada
        # impede um commit de trazer bytes de controle na mensagem): limitar as
        # divisões mantém a mensagem inteira em vez de descartar o registro.
        partes = registro.strip().split(_CAMPO, 3)
        if len(partes) != 4:  # linha truncada: ignora em vez de derrubar a leitura
            continue
        hash_curto, timestamp, autor_commit, assunto = partes
        data, _, hora = timestamp.partition(" ")
        commits.append(
            Commit(
                hash_curto=hash_curto,
                data=data,
                hora=hora,
                autor=autor_commit,
                assunto=assunto,
            )
        )
    return commits


def agrupar_por_dia(commits: list[Commit]) -> list[DiaDeTrabalho]:
    """Agrupa commits por data, em ordem cronológica."""
    por_data: dict[str, list[Commit]] = defaultdict(list)
    for commit in commits:
        por_data[commit.data].append(commit)
    return [DiaDeTrabalho(data=data, commits=tuple(por_data[data])) for data in sorted(por_data)]


def dias_de_trabalho(
    repositorio: Path | str,
    *,
    desde: str = "",
    ate: str = "",
    autor: str = "",
) -> list[DiaDeTrabalho]:
    """Atalho para :func:`coletar_commits` + :func:`agrupar_por_dia`."""
    return agrupar_por_dia(coletar_commits(repositorio, desde=desde, ate=ate, autor=autor))


def resumo_markdown(dia: DiaDeTrabalho, *, titulo: str = "") -> str:
    """Markdown com a lista de commits do dia, para servir de rascunho.

    É deliberadamente factual — só o que o git afirma. A narrativa do dia (por
    que algo foi feito, o que ficou pendente) é responsabilidade de quem escreve
    o relatório; este texto existe para não partir de uma página em branco.
    """
    cabecalho = titulo or f"Commits de {dia.data_por_extenso()}"
    linhas = [f"## {cabecalho}", ""]
    plural = "commit" if dia.total == 1 else "commits"
    if dia.total:
        linhas.append(f"{dia.total} {plural}, das {dia.primeira_hora} às {dia.ultima_hora}.")
        linhas.append("")
    for commit in dia.commits:
        linhas.append(f"- `{commit.hash_curto}` {commit.descricao}")
    return "\n".join(linhas).strip() + "\n"


def hoje_iso() -> str:
    """Data de hoje em ISO — isolada para facilitar o teste de quem depende dela."""
    return _date.today().isoformat()
