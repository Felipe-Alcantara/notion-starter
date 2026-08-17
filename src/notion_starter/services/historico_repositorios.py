"""Caso de uso: reconstruir o dia de trabalho a partir de **vários** repositórios.

``git_historico`` responde por um repositório. Mas um dia real quase nunca cabe
num só: mexe-se na biblioteca, no CLI que a consome e no app que a expõe, e o
relatório do dia precisa contar isso junto — senão o mesmo dia vira três
narrativas soltas que ninguém cruza depois.

Este módulo agrega os históricos, agrupa por data e produz o texto no formato
que os relatórios diários já usam: **hora e duração por repositório**, nunca só
o dia. Um "trabalhei no dia 12" não diz se foram dez minutos ou seis horas.

Continua sendo camada de caso de uso: executa ``git`` e devolve estruturas e
Markdown. Quem publica no Notion é ``relatorios_diarios``.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from notion_starter.git_historico import (
    Commit,
    DiaDeTrabalho,
    GitIndisponivelError,
    coletar_commits,
)

#: Tempo máximo esperando o git de um repositório grande.
_TIMEOUT_SEGUNDOS = 120


@dataclass(frozen=True)
class Repositorio:
    """Um repositório a incluir no histórico.

    Attributes:
        nome: Como ele aparece no relatório — nome de produto, não de pasta.
            "Felixo AI Core" diz mais a quem lê do que "Felixo-AI-Core".
        caminho: Onde o repositório está no disco.
    """

    nome: str
    caminho: Path

    @staticmethod
    def de_par(nome: str, caminho: Path | str) -> Repositorio:
        return Repositorio(nome=nome, caminho=Path(caminho))


@dataclass(frozen=True)
class TrabalhoNoRepositorio:
    """O que um repositório recebeu num dia."""

    repositorio: str
    dia: DiaDeTrabalho
    #: ``hash_curto -> (arquivos, inserções, deleções)``, quando disponível.
    estatisticas: dict[str, tuple[int, int, int]] = field(default_factory=dict)

    @property
    def arquivos_tocados(self) -> int:
        return sum(stat[0] for stat in self.estatisticas.values())

    @property
    def linhas_somadas(self) -> int:
        return sum(stat[1] for stat in self.estatisticas.values())

    @property
    def linhas_removidas(self) -> int:
        return sum(stat[2] for stat in self.estatisticas.values())

    def resumo_de_uma_linha(self) -> str:
        """A frase do padrão de relatórios: quantos commits, entre que horas."""

        plural = "commit" if self.dia.total == 1 else "commits"
        if self.dia.total == 1:
            frase = f"{self.repositorio}: 1 {plural} às {self.dia.primeira_hora}"
        else:
            frase = (
                f"{self.repositorio}: {self.dia.total} {plural} entre "
                f"{self.dia.primeira_hora} e {self.dia.ultima_hora}"
            )
        duracao = self.dia.duracao_por_extenso()
        if duracao:
            frase += f" (duração: {duracao})"
        if self.arquivos_tocados:
            frase += (
                f" — {self.arquivos_tocados} arquivos, "
                f"+{self.linhas_somadas}/-{self.linhas_removidas} linhas"
            )
        return frase + "."


@dataclass(frozen=True)
class DiaConsolidado:
    """Um dia de trabalho somando todos os repositórios tocados nele."""

    data: str
    trabalhos: tuple[TrabalhoNoRepositorio, ...]

    @property
    def total_commits(self) -> int:
        return sum(trabalho.dia.total for trabalho in self.trabalhos)

    @property
    def repositorios(self) -> tuple[str, ...]:
        return tuple(trabalho.repositorio for trabalho in self.trabalhos)

    def data_por_extenso(self) -> str:
        ano, mes, dia = self.data.split("-")
        return f"{dia}/{mes}/{ano}"

    @property
    def primeira_hora(self) -> str:
        return min(t.dia.primeira_hora for t in self.trabalhos) if self.trabalhos else ""

    @property
    def ultima_hora(self) -> str:
        return max(t.dia.ultima_hora for t in self.trabalhos) if self.trabalhos else ""

    def resumo(self) -> str:
        """Texto da coluna "Resumo": uma frase por repositório, com hora e duração."""

        return " | ".join(trabalho.resumo_de_uma_linha() for trabalho in self.trabalhos)

    def o_que_fiz(self) -> str:
        """Texto da coluna "O que fiz": cada commit com hora, agrupado por projeto."""

        partes = []
        for trabalho in self.trabalhos:
            itens = "; ".join(
                f"{commit.hora} {commit.assunto}" for commit in trabalho.dia.commits
            )
            partes.append(f"{trabalho.repositorio} — {itens}")
        return " | ".join(partes)


#: Pastas que nunca contêm repositório de trabalho e custam caro varrer.
_IGNORAR = frozenset({"node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".git"})


def descobrir_repositorios(
    raiz: Path | str,
    *,
    profundidade: int = 3,
) -> list[Repositorio]:
    """Encontra os repositórios git abaixo de ``raiz``.

    Existe para o caso que motivou tudo isto: *achar o dia de trabalho que ficou
    sem registro*. Listar os repositórios à mão só encontra o que já se lembra —
    e o esquecido, por definição, não está nessa lista. A varredura é o que
    transforma "os projetos que eu citei" em "tudo que existe no disco".

    Desce até ``profundidade`` níveis para alcançar submódulos em ``modules/``
    sem varrer a árvore inteira, e não entra em pasta de dependência.

    Args:
        raiz: Pasta a varrer.
        profundidade: Quantos níveis descer a partir da raiz.

    Returns:
        Repositórios em ordem alfabética, com o nome derivado da pasta. Lista
        vazia quando a raiz não existe — varrer um caminho errado não é erro,
        é resultado vazio.
    """

    inicio = Path(raiz)
    if not inicio.is_dir():
        return []

    encontrados: dict[str, Repositorio] = {}

    def varrer(pasta: Path, nivel: int) -> None:
        if nivel > profundidade:
            return
        try:
            filhos = sorted(pasta.iterdir())
        except OSError:
            return
        for filho in filhos:
            if not filho.is_dir() or filho.name in _IGNORAR:
                continue
            # `.git` é diretório no clone comum e arquivo em submódulo/worktree.
            if (filho / ".git").exists():
                encontrados.setdefault(filho.name, Repositorio(filho.name, filho))
            varrer(filho, nivel + 1)

    varrer(inicio, 1)
    return [encontrados[nome] for nome in sorted(encontrados)]


def _estatisticas(
    repositorio: Path, *, desde: str = "", ate: str = ""
) -> dict[str, tuple[int, int, int]]:
    """Lê arquivos/linhas por commit. Falha aqui nunca derruba o relatório.

    O número de linhas é contexto útil ("foi um ajuste ou uma reescrita?"), mas
    não é o conteúdo do relatório. Se o git recusar (repositório raso, commit
    órfão), seguimos sem a estatística em vez de perder o dia inteiro.
    """

    argumentos = [
        "log",
        "--pretty=format:@%h",
        "--shortstat",
        "--no-renames",
    ]
    if desde:
        argumentos.append(f"--since={desde} 00:00:00")
    if ate:
        argumentos.append(f"--until={ate} 23:59:59")

    try:
        saida = subprocess.run(
            ["git", "-C", str(repositorio), *argumentos],
            capture_output=True,
            text=True,
            check=True,
            timeout=_TIMEOUT_SEGUNDOS,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}

    return _parsear_shortstat(saida)


def _parsear_shortstat(saida: str) -> dict[str, tuple[int, int, int]]:
    """Converte a saída de ``--shortstat`` em ``hash -> (arquivos, +, -)``.

    Função separada, e pura, porque o formato do ``--shortstat`` é irregular:
    omite a parte de inserção ou de deleção quando ela é zero, e o commit sem
    alteração nenhuma (merge) não gera linha de estatística.
    """

    estatisticas: dict[str, tuple[int, int, int]] = {}
    atual = ""
    for linha in saida.splitlines():
        texto = linha.strip()
        if texto.startswith("@"):
            atual = texto[1:]
            continue
        if not atual or "changed" not in texto:
            continue
        arquivos = insercoes = delecoes = 0
        for pedaco in texto.split(","):
            pedaco = pedaco.strip()
            numero = pedaco.split(" ", 1)[0]
            if not numero.isdigit():
                continue
            if "file" in pedaco:
                arquivos = int(numero)
            elif "insertion" in pedaco:
                insercoes = int(numero)
            elif "deletion" in pedaco:
                delecoes = int(numero)
        estatisticas[atual] = (arquivos, insercoes, delecoes)
    return estatisticas


def consolidar_dias(
    repositorios: list[Repositorio],
    *,
    desde: str = "",
    ate: str = "",
    autor: str = "",
    com_estatisticas: bool = True,
) -> list[DiaConsolidado]:
    """Lê todos os repositórios e devolve um :class:`DiaConsolidado` por data.

    Repositório inacessível é **pulado**, não fatal: numa lista de quinze, um
    caminho que mudou de lugar não pode custar o histórico dos outros catorze.

    Args:
        repositorios: Repositórios a incluir.
        desde: Data ISO inicial (inclusiva), ou vazio.
        ate: Data ISO final (inclusiva), ou vazio.
        autor: Filtra por autor, como ``git --author``.
        com_estatisticas: Coleta arquivos/linhas por commit (uma chamada extra
            de git por repositório).

    Returns:
        Um dia por data com commit, do mais antigo para o mais recente.
    """

    por_data: dict[str, list[TrabalhoNoRepositorio]] = defaultdict(list)

    for repositorio in repositorios:
        try:
            commits = coletar_commits(
                repositorio.caminho, desde=desde, ate=ate, autor=autor
            )
        except GitIndisponivelError:
            continue
        if not commits:
            continue

        estatisticas = (
            _estatisticas(repositorio.caminho, desde=desde, ate=ate)
            if com_estatisticas
            else {}
        )

        agrupados: dict[str, list[Commit]] = defaultdict(list)
        for commit in commits:
            agrupados[commit.data].append(commit)

        for data, do_dia in agrupados.items():
            por_data[data].append(
                TrabalhoNoRepositorio(
                    repositorio=repositorio.nome,
                    dia=DiaDeTrabalho(data=data, commits=tuple(do_dia)),
                    estatisticas={
                        commit.hash_curto: estatisticas[commit.hash_curto]
                        for commit in do_dia
                        if commit.hash_curto in estatisticas
                    },
                )
            )

    return [
        DiaConsolidado(
            data=data,
            # Mais commits primeiro: o repositório que dominou o dia abre o texto.
            trabalhos=tuple(
                sorted(
                    por_data[data],
                    key=lambda t: (-t.dia.total, t.repositorio),
                )
            ),
        )
        for data in sorted(por_data)
    ]


def corpo_markdown(dia: DiaConsolidado, *, titulo: str = "") -> str:
    """Corpo do relatório de um dia, em Markdown, uma seção por repositório.

    Deliberadamente **factual**: só o que o git afirma, e o texto diz isso de
    saída. O porquê de cada mudança e o que ficou pendente são responsabilidade
    de quem viveu o dia — inventar narrativa a partir de mensagem de commit é o
    jeito mais fácil de povoar um relatório com ficção plausível.
    """

    cabecalho = titulo or f"Histórico do git — {dia.data_por_extenso()}"
    plural = "commit" if dia.total_commits == 1 else "commits"
    projetos = "projeto" if len(dia.trabalhos) == 1 else "projetos"

    linhas = [
        f"## {cabecalho}",
        "",
        (
            f"> Reconstruído a partir do histórico dos repositórios — "
            f"{dia.total_commits} {plural} em {len(dia.trabalhos)} {projetos}, "
            f"das {dia.primeira_hora} às {dia.ultima_hora}. "
            f"É o registro factual do que ficou versionado; decisões e "
            f"pendências que não viraram commit não aparecem aqui."
        ),
        "",
    ]

    for trabalho in dia.trabalhos:
        linhas.append(f"### {trabalho.repositorio}")
        linhas.append("")
        linhas.append(trabalho.resumo_de_uma_linha())
        linhas.append("")
        for commit in trabalho.dia.commits:
            stat = trabalho.estatisticas.get(commit.hash_curto)
            sufixo = ""
            if stat:
                sufixo = f" _({stat[0]} arq., +{stat[1]}/-{stat[2]})_"
            linhas.append(f"- **{commit.hora}** `{commit.hash_curto}` {commit.assunto}{sufixo}")
        linhas.append("")

    return "\n".join(linhas).strip() + "\n"
