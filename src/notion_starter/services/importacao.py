"""Importação em lote com estado de progresso retomável.

Migrações grandes (centenas de linhas) falham no meio em algum momento — rede,
rate limit, queda do processo. Este módulo formaliza o padrão que se repetiu
nas migrações reais: um arquivo JSON local ``{chave: page_id}`` gravado a cada
criação, de modo que reexecutar o import **pula o que já existe** em vez de
duplicar.

Complementa a idempotência por propriedade (upsert por "Origem" em
:mod:`notion_starter.services.ingestao`): o estado local não gasta chamadas de
consulta ao Notion e sobrevive a fontes sem propriedade única.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class EstadoImportacao:
    """Estado local ``{chave: page_id}`` persistido em JSON a cada registro.

    Args:
        caminho: Arquivo JSON de estado. É criado (com as pastas) no primeiro
            registro; se já existe, o progresso anterior é carregado.
    """

    def __init__(self, caminho: str | Path) -> None:
        self._caminho = Path(caminho)
        self._dados: dict[str, str] = {}
        if self._caminho.is_file():
            try:
                bruto = json.loads(self._caminho.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Arquivo de estado inválido: {self._caminho}. "
                    "Corrija ou remova o arquivo para recomeçar."
                ) from exc
            if not isinstance(bruto, dict):
                raise ValueError(
                    f"Arquivo de estado inválido: {self._caminho} não contém um objeto JSON."
                )
            self._dados = {str(k): str(v) for k, v in bruto.items()}

    def __contains__(self, chave: str) -> bool:
        return chave in self._dados

    def __len__(self) -> int:
        return len(self._dados)

    def page_id(self, chave: str) -> str | None:
        """Devolve o ``page_id`` já criado para ``chave``, se houver."""

        return self._dados.get(chave)

    def registrar(self, chave: str, page_id: str) -> None:
        """Registra uma criação e grava o estado em disco imediatamente."""

        self._dados[chave] = page_id
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._caminho.write_text(
            json.dumps(self._dados, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@dataclass
class ResultadoImportacao:
    """Resumo de uma importação em lote retomável."""

    criados: int = 0
    pulados: int = 0
    erros: int = 0
    falhas: list[str] = field(default_factory=list)


def importar_com_estado(
    itens: Iterable[Any],
    *,
    chave: Callable[[Any], str],
    criar: Callable[[Any], str],
    estado: EstadoImportacao,
    parar_no_erro: bool = False,
) -> ResultadoImportacao:
    """Importa ``itens`` pulando os já registrados no ``estado``.

    Para cada item cuja chave ainda não está no estado, chama ``criar`` (que
    deve efetivar a escrita no Notion e devolver o ``page_id``) e registra o
    resultado imediatamente — um crash no meio não perde o progresso.

    Args:
        itens: Iterável de itens a importar (linhas de planilha, arquivos…).
        chave: Extrai a chave estável e única de cada item.
        criar: Cria o item no Notion e devolve o ``page_id``.
        estado: Estado retomável carregado de/gravado em disco.
        parar_no_erro: Quando ``True``, a primeira falha interrompe o lote;
            por padrão a falha é contabilizada e o lote segue.

    Returns:
        Resumo com criados, pulados e erros (as chaves que falharam ficam em
        ``falhas`` para reexecução dirigida).
    """

    resultado = ResultadoImportacao()
    for item in itens:
        chave_item = chave(item)
        if not chave_item:
            raise ValueError("A função de chave devolveu um valor vazio para um item.")
        if chave_item in estado:
            resultado.pulados += 1
            continue
        try:
            page_id = criar(item)
        except Exception:
            resultado.erros += 1
            resultado.falhas.append(chave_item)
            if parar_no_erro:
                raise
            continue
        estado.registrar(chave_item, str(page_id))
        resultado.criados += 1
    return resultado
