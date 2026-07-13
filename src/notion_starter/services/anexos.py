"""Caso de uso: anexar um arquivo local a uma propriedade ``files`` de página.

Orquestra o fluxo completo que as migrações reais repetiam à mão: ler o
arquivo, subir via File Upload API (:meth:`NotionClient.enviar_arquivo`) e
gravar a referência na propriedade da linha, **preservando os anexos já
existentes** por padrão.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from notion_starter import NotionClient, properties


def anexar_arquivo(
    page_id: str,
    caminho: str | Path,
    *,
    propriedade: str = "Arquivos e mídia",
    substituir: bool = False,
    cliente: NotionClient,
) -> dict[str, Any]:
    """Sobe um arquivo local e o anexa à propriedade ``files`` de uma página.

    Args:
        page_id: ID da página (linha de database) que recebe o anexo.
        caminho: Arquivo local a subir (parte única, até 20 MB).
        propriedade: Nome da propriedade ``files`` de destino.
        substituir: Quando ``True``, a propriedade fica só com o novo arquivo;
            por padrão o anexo é **acrescentado** aos existentes.
        cliente: Cliente Notion injetado (camada de serviço não cria clientes).

    Returns:
        Resumo com o ``upload_id``, o nome do arquivo e o total de anexos.

    Raises:
        ValueError: Se o arquivo não existir ou exceder o limite de 20 MB.
    """

    arquivo = Path(caminho)
    if not arquivo.is_file():
        raise ValueError(f"Arquivo não encontrado: {arquivo}")

    content_type = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
    upload_id = cliente.enviar_arquivo(arquivo.read_bytes(), arquivo.name, content_type)
    valor = properties.arquivo_enviado(upload_id, arquivo.name)

    if not substituir:
        existentes = _anexos_existentes(cliente.obter_pagina(page_id), propriedade)
        valor = {"files": existentes + valor["files"]}

    cliente.atualizar_pagina(page_id, {propriedade: valor})
    return {
        "page_id": page_id,
        "propriedade": propriedade,
        "arquivo": arquivo.name,
        "upload_id": upload_id,
        "total_anexos": len(valor["files"]),
    }


def _anexos_existentes(pagina: dict[str, Any], propriedade: str) -> list[dict[str, Any]]:
    """Extrai os anexos atuais de uma propriedade ``files``, re-referenciáveis.

    Arquivos hospedados pelo Notion (``type: file``) não podem ser reenviados
    com a URL temporária; a API aceita re-referenciá-los apenas por nome +
    URL, então preservamos os itens ``external`` e ``file_upload`` e
    reenviamos os ``file`` como ``external`` com a URL vigente.
    """

    valor = (pagina.get("properties") or {}).get(propriedade) or {}
    anexos: list[dict[str, Any]] = []
    for item in valor.get("files") or []:
        tipo = item.get("type")
        if tipo in ("external", "file_upload"):
            anexos.append({k: v for k, v in item.items() if k in ("type", "name", tipo)})
        elif tipo == "file":
            url = (item.get("file") or {}).get("url")
            if url:
                anexos.append(
                    {
                        "type": "external",
                        "name": item.get("name", ""),
                        "external": {"url": url},
                    }
                )
    return anexos
