"""Caso de uso: baixar o corpo (Markdown) das páginas do inventário, retomável.

Ler o corpo recursivo de ~1.800 páginas levou ~30 min (medido em 2026-09-27, ~1
página/s com 3 threads, pelo limite de taxa do Notion). Um trabalho desse
tamanho precisa sobreviver a interrupção e mostrar o mais útil primeiro:

* cada página vira ``<destino>/<id>.md``: um cabeçalho de metadados (título,
  caminho, datas, colunas) num comentário HTML, seguido do corpo;
* arquivo existente é pulado, então rodar de novo **continua de onde parou**;
* a gravação é atômica (``.parcial`` + troca de nome): uma interrupção nunca
  deixa um arquivo truncado com o nome final, que seria pulado para sempre;
* :func:`ordenar_por_prioridade` põe primeiro as páginas soltas e as linhas de
  databases pequenos, depois as que casam com um padrão, e por último o resto
  dos databases volumosos (tarefas, relatórios).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_starter import NotionClient
from notion_starter.services.inventario_workspace import (
    RegistroWorkspace,
    gravar_texto_atomico,
)

#: Paralelismo modesto: o Notion limita a ~3 requisições/s por integração e o
#: cliente já espera nos 429 — mais threads só gerariam retentativas.
TRABALHADORES_PADRAO = 3

#: A partir de quantas linhas um database é "volumoso" na priorização.
LIMITE_VOLUMOSO_PADRAO = 100

#: Abertura do cabeçalho de metadados de cada arquivo baixado.
MARCA_META = "<!-- meta\n"


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


@dataclass(frozen=True)
class ResultadoDownload:
    """Resumo de uma rodada de download.

    Attributes:
        destino: Pasta dos arquivos.
        selecionadas: Páginas pedidas nesta rodada.
        baixados: Arquivos gravados agora.
        pulados: Já existiam (rodada anterior).
        adiados: Ficaram para a próxima rodada por causa do ``limite``.
        falhas: ``{page_id: erro}``; rode de novo para tentar outra vez.
    """

    destino: str
    selecionadas: int
    baixados: int
    pulados: int
    adiados: int = 0
    falhas: dict[str, str] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON)."""

        return {
            "destino": self.destino,
            "selecionadas": self.selecionadas,
            "baixados": self.baixados,
            "pulados": self.pulados,
            "adiados": self.adiados,
            "falhas": dict(self.falhas),
        }


def _chave(identificador: str | None) -> str:
    return str(identificador or "").replace("-", "").lower()


def selecionar_paginas(
    registros: Iterable[RegistroWorkspace],
    *,
    ignorar_caminhos: Iterable[str] = (),
    ignorar_databases: Iterable[str] = (),
    somente_databases: Iterable[str] | None = None,
    incluir_arquivados: bool = False,
) -> list[RegistroWorkspace]:
    """Filtra as páginas cujo corpo vale baixar.

    Args:
        registros: Inventário completo.
        ignorar_caminhos: Prefixos de caminho a pular, com " / " entre os
            níveis (ex.: ``"Arquivo"`` ou ``"Estudo / Programação"``); o próprio
            título conta como último nível.
        ignorar_databases: Databases cujas linhas não interessam.
        somente_databases: Quando informado, só linhas destes databases.
        incluir_arquivados: Também baixa itens arquivados/na lixeira.

    Returns:
        Só as páginas (não databases) fora das exclusões, na ordem de entrada.
    """

    prefixos = [
        tuple(parte.strip() for parte in p.split(" / ") if parte.strip())
        for p in ignorar_caminhos
    ]
    prefixos = [p for p in prefixos if p]
    bloqueados = {_chave(d) for d in ignorar_databases}
    somente = {_chave(d) for d in somente_databases} if somente_databases is not None else None
    escolhidas: list[RegistroWorkspace] = []
    for registro in registros:
        if registro.objeto != "page":
            continue
        if registro.arquivado and not incluir_arquivados:
            continue
        pai = _chave(registro.pai_id) if registro.pai_tipo == "database_id" else ""
        if pai and pai in bloqueados:
            continue
        if somente is not None and pai not in somente:
            continue
        completo = registro.caminho_completo
        if any(completo[: len(p)] == p for p in prefixos):
            continue
        escolhidas.append(registro)
    return escolhidas


def ordenar_por_prioridade(
    paginas: list[RegistroWorkspace],
    *,
    priorizar: re.Pattern[str] | None = None,
    limite_volumoso: int = LIMITE_VOLUMOSO_PADRAO,
) -> list[RegistroWorkspace]:
    """Ordena o download para o mais provável de interessar vir primeiro.

    Prioridades (a ordem de entrada se mantém dentro de cada grupo):

    0. páginas soltas e linhas de databases com menos de ``limite_volumoso``
       linhas (notas, rascunhos, ideias);
    1. linhas de databases volumosos cujo título ou colunas casam com
       ``priorizar``;
    2. o resto dos databases volumosos.
    """

    linhas_por_pai: dict[str, int] = {}
    for pagina in paginas:
        if pagina.pai_tipo == "database_id":
            chave = _chave(pagina.pai_id)
            linhas_por_pai[chave] = linhas_por_pai.get(chave, 0) + 1

    def texto_de(pagina: RegistroWorkspace) -> str:
        valores = " ".join(str(v) for v in pagina.propriedades.values())
        return f"{pagina.titulo} {valores}"

    def prioridade(pagina: RegistroWorkspace) -> int:
        volumosa = (
            pagina.pai_tipo == "database_id"
            and linhas_por_pai.get(_chave(pagina.pai_id), 0) >= limite_volumoso
        )
        if not volumosa:
            return 0
        return 1 if priorizar is not None and priorizar.search(texto_de(pagina)) else 2

    return sorted(paginas, key=prioridade)


def caminho_do_corpo(destino: Path, page_id: str) -> Path:
    """Onde o corpo de ``page_id`` fica gravado."""

    return Path(destino) / f"{page_id}.md"


def cabecalho(registro: RegistroWorkspace) -> str:
    """Metadados legíveis no topo do arquivo, num comentário HTML."""

    meta = {
        "id": registro.id,
        "titulo": registro.titulo,
        "caminho": " / ".join(registro.caminho),
        "criado_em": registro.criado_em,
        "editado_em": registro.editado_em,
        "url": registro.url,
        "propriedades": registro.propriedades,
    }
    texto = json.dumps(meta, ensure_ascii=False, indent=1, default=str)
    # "-->" fecharia o comentário antes da hora; o escape JSON mantém o valor.
    return MARCA_META + texto.replace("-->", "--\\u003e") + "\n-->\n\n"


def baixar_corpos(
    paginas: list[RegistroWorkspace],
    destino: Path | str,
    *,
    trabalhadores: int = TRABALHADORES_PADRAO,
    limite: int | None = None,
    ao_progredir: Callable[[int, int], None] | None = None,
    cliente: NotionClient | None = None,
) -> ResultadoDownload:
    """Grava ``destino/<id>.md`` para cada página ainda não baixada.

    Args:
        paginas: Páginas a baixar, já na ordem desejada.
        destino: Pasta de saída (criada se faltar).
        trabalhadores: Threads simultâneas (mínimo 1).
        limite: No máximo quantas páginas baixar nesta rodada; o resto fica
            ``adiado`` para a próxima.
        ao_progredir: Callback ``(feitas, total)`` para mostrar progresso.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        O :class:`ResultadoDownload`.

    Raises:
        ValueError: ``trabalhadores`` ou ``limite`` menores que 1.
    """

    if trabalhadores < 1:
        raise ValueError("trabalhadores deve ser pelo menos 1.")
    if limite is not None and limite < 1:
        raise ValueError("limite deve ser pelo menos 1.")
    from notion_starter.services.conteudo import ler_conteudo

    cli = cliente or _cliente_padrao()
    pasta = Path(destino)
    pasta.mkdir(parents=True, exist_ok=True)
    pendentes = [p for p in paginas if not caminho_do_corpo(pasta, p.id).exists()]
    pulados = len(paginas) - len(pendentes)
    adiados = 0
    if limite is not None and len(pendentes) > limite:
        adiados = len(pendentes) - limite
        pendentes = pendentes[:limite]
    falhas: dict[str, str] = {}

    def baixar(registro: RegistroWorkspace) -> None:
        corpo = ler_conteudo(registro.id, cliente=cli)
        gravar_texto_atomico(caminho_do_corpo(pasta, registro.id), cabecalho(registro) + corpo)

    with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
        futuros = {pool.submit(baixar, p): p for p in pendentes}
        for feitas, futuro in enumerate(as_completed(futuros), start=1):
            erro = futuro.exception()
            if erro is not None:
                falhas[futuros[futuro].id] = f"{type(erro).__name__}: {erro}"
            if ao_progredir is not None:
                ao_progredir(feitas, len(pendentes))
    return ResultadoDownload(
        destino=str(pasta),
        selecionadas=len(paginas),
        baixados=len(pendentes) - len(falhas),
        pulados=pulados,
        adiados=adiados,
        falhas=falhas,
    )
