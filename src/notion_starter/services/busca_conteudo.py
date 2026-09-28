"""Caso de uso: procurar uma expressão regular no **texto completo** baixado.

O ``/search`` do Notion casa só o título. Para achar a ideia escondida no corpo
de uma página de título genérico, baixa-se o corpo com
:mod:`notion_starter.services.corpos` e procura-se aqui, sem rede. A busca
devolve trechos com contexto para uma pessoa (ou IA) decidir — não decide
sozinha.

Por padrão a comparação ignora acentos e maiúsculas (``"publicação"`` casa com
``"publicacao"``), mas os trechos são cortados do texto **original**, para
preservar a escrita de quem anotou.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_starter.services.corpos import MARCA_META

_RE_META = re.compile(r"\A" + re.escape(MARCA_META) + r"(.*?)\n-->\n\n", re.DOTALL)


@dataclass
class Ocorrencia:
    """Página cujo texto casa com a expressão procurada.

    Attributes:
        id: ID da página.
        titulo: Título (do cabeçalho de metadados).
        caminho: Caminho de ancestrais.
        criado_em: Data de criação da página.
        url: Link da página.
        total: Quantas vezes a expressão casou.
        termos: Contagem por texto casado (normalizado).
        trechos: Até ``max_trechos`` trechos do original ao redor dos casamentos.
        palavras: Tamanho do corpo, em palavras.
        arquivo: Arquivo ``.md`` lido.
    """

    id: str
    titulo: str
    caminho: str
    criado_em: str | None
    url: str | None
    total: int
    termos: dict[str, int] = field(default_factory=dict)
    trechos: list[str] = field(default_factory=list)
    palavras: int = 0
    arquivo: str = ""

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {
            "id": self.id,
            "titulo": self.titulo,
            "caminho": self.caminho,
            "criado_em": self.criado_em,
            "url": self.url,
            "total": self.total,
            "termos": dict(self.termos),
            "trechos": list(self.trechos),
            "palavras": self.palavras,
            "arquivo": self.arquivo,
        }


def separar_meta(conteudo: str) -> tuple[dict[str, Any], str]:
    """Separa o cabeçalho gravado por ``corpos.baixar_corpos`` do corpo em si."""

    casamento = _RE_META.match(conteudo)
    if not casamento:
        return {}, conteudo
    try:
        meta = json.loads(casamento.group(1))
    except ValueError:
        return {}, conteudo
    return (meta if isinstance(meta, dict) else {}), conteudo[casamento.end():]


def sem_acentos(texto: str) -> tuple[str, list[int]]:
    """Tira os acentos e devolve, para cada caractere novo, o índice no original.

    O mapa permite achar no texto original o trecho casado no normalizado,
    mesmo quando a normalização muda o comprimento (ligaduras, por exemplo).
    """

    saida: list[str] = []
    mapa: list[int] = []
    for indice, caractere in enumerate(texto):
        for decomposto in unicodedata.normalize("NFKD", caractere):
            if not unicodedata.combining(decomposto):
                saida.append(decomposto)
                mapa.append(indice)
    return "".join(saida), mapa


def compilar(padrao: str, *, ignorar_acentos: bool = True, ignorar_caixa: bool = True):
    """Compila ``padrao`` com as mesmas regras aplicadas ao texto.

    Raises:
        ValueError: Expressão vazia ou inválida (com a posição do erro).
    """

    if not padrao or not padrao.strip():
        raise ValueError("Informe a expressão a procurar.")
    fonte = sem_acentos(padrao)[0] if ignorar_acentos else padrao
    try:
        return re.compile(fonte, re.IGNORECASE if ignorar_caixa else 0)
    except re.error as exc:
        raise ValueError(f"Expressão regular inválida: {exc}") from exc


def procurar_no_texto(
    corpo: str,
    expressao: re.Pattern[str],
    *,
    ignorar_acentos: bool = True,
    contexto: int = 90,
    max_trechos: int = 4,
) -> tuple[dict[str, int], list[str]]:
    """Conta os casamentos e devolve trechos do original ao redor deles."""

    if ignorar_acentos:
        alvo, mapa = sem_acentos(corpo)
    else:
        alvo, mapa = corpo, list(range(len(corpo)))
    termos: dict[str, int] = {}
    trechos: list[str] = []
    for casamento in expressao.finditer(alvo):
        if casamento.end() == casamento.start():
            continue
        termo = casamento.group(0).casefold()
        termos[termo] = termos.get(termo, 0) + 1
        if len(trechos) < max_trechos:
            inicio = mapa[casamento.start()]
            fim = mapa[casamento.end() - 1] + 1
            pedaco = corpo[max(0, inicio - contexto): fim + contexto]
            trechos.append(" ".join(pedaco.split()))
    return termos, trechos


def buscar_no_conteudo(
    pasta: Path | str,
    padrao: str,
    *,
    ignorar_acentos: bool = True,
    ignorar_caixa: bool = True,
    contexto: int = 90,
    max_trechos: int = 4,
    limite: int | None = None,
) -> list[Ocorrencia]:
    """Procura ``padrao`` em todos os ``.md`` baixados e devolve as páginas que casam.

    Args:
        pasta: Pasta gravada por ``corpos.baixar_corpos``.
        padrao: Expressão regular (sintaxe do módulo ``re``).
        ignorar_acentos: Compara sem acentos (padrão).
        ignorar_caixa: Compara sem diferenciar maiúsculas (padrão).
        contexto: Caracteres de contexto de cada lado do trecho.
        max_trechos: Trechos por página.
        limite: No máximo quantas páginas devolver (as de mais casamentos).

    Returns:
        As ocorrências, da página com mais casamentos para a com menos; no
        empate, a criada primeiro.

    Raises:
        ValueError: Pasta inexistente ou expressão inválida.
    """

    pasta = Path(pasta)
    if not pasta.is_dir():
        raise ValueError(f"Pasta não encontrada: {pasta}")
    expressao = compilar(padrao, ignorar_acentos=ignorar_acentos, ignorar_caixa=ignorar_caixa)
    ocorrencias: list[Ocorrencia] = []
    for arquivo in sorted(pasta.glob("*.md")):
        meta, corpo = separar_meta(arquivo.read_text(encoding="utf-8"))
        termos, trechos = procurar_no_texto(
            corpo,
            expressao,
            ignorar_acentos=ignorar_acentos,
            contexto=contexto,
            max_trechos=max_trechos,
        )
        if not termos:
            continue
        ocorrencias.append(
            Ocorrencia(
                id=str(meta.get("id") or arquivo.stem),
                titulo=str(meta.get("titulo") or ""),
                caminho=str(meta.get("caminho") or ""),
                criado_em=meta.get("criado_em"),
                url=meta.get("url"),
                total=sum(termos.values()),
                termos=termos,
                trechos=trechos,
                palavras=len(corpo.split()),
                arquivo=str(arquivo),
            )
        )
    ocorrencias.sort(key=lambda o: (-o.total, o.criado_em or ""))
    return ocorrencias[:limite] if limite is not None else ocorrencias
