"""Adaptador do OpenRouter — catálogo de modelos e provedor de IA plugável.

Espelha os padrões do projeto `Openia <https://github.com/Felipe-Alcantara/Openia>`_:
catálogo com cache de 24 h, agrupamento por empresa, ordenação por preço e chave
fora do repositório (variável de ambiente).

A interface ``ProvedorIA`` é o contrato único que ``services/ia.py`` consome.
Implementações concretas (OpenRouter, assinatura) são registradas de forma
declarativa (Open/Closed): adicionar um provedor novo é registrar mais um, sem
mexer no núcleo.

Segurança: nenhuma chave aparece em código, log ou repr. A chave é lida de
``OPENROUTER_API_KEY`` no ambiente (ou do ``.env`` via ``core.config``).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import requests as http

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MODELS_URL = "https://openrouter.ai/api/v1/models"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_OPENROUTER_KEY = "OPENROUTER_API_KEY"

_CACHE_DIR = Path(__file__).resolve().parent
_CACHE_PATH = _CACHE_DIR / ".openrouter_models_cache.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 h


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class CatalogoErro(RuntimeError):
    """Falha ao obter o catálogo de modelos (rede e cache indisponíveis)."""


class ProvedorErro(RuntimeError):
    """Falha na chamada ao provedor de IA."""


# ---------------------------------------------------------------------------
# Objeto de domínio: Modelo (CONTRATOS.md §1 — reservado para Fase 5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Modelo:
    """Um modelo do catálogo OpenRouter.

    ``id`` é o identificador completo (``empresa/modelo``) usado pela API.
    ``empresa`` é a parte antes da barra; ``nome`` é o rótulo legível.
    ``preco_saida`` é o preço por token de saída (USD), para ordenar por custo.
    """

    id: str
    empresa: str
    nome: str
    preco_saida: float = 0.0


# ---------------------------------------------------------------------------
# Catálogo de modelos (espelha openia/models.py)
# ---------------------------------------------------------------------------


def _preco_saida(item: dict) -> float:
    """Extrai o preço de saída; 0.0 quando ausente ou inválido."""
    try:
        return float((item.get("pricing") or {}).get("completion", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_modelos(payload: dict) -> list[Modelo]:
    """Converte o JSON da API em lista de ``Modelo``, ignorando malformados."""
    modelos: list[Modelo] = []
    for item in payload.get("data", []):
        model_id = (item or {}).get("id", "")
        if not model_id or "/" not in model_id:
            continue
        empresa = model_id.split("/", 1)[0]
        nome = (item.get("name") or model_id).strip()
        modelos.append(
            Modelo(
                id=model_id,
                empresa=empresa,
                nome=nome,
                preco_saida=_preco_saida(item),
            )
        )
    return modelos


def _ler_cache() -> list[Modelo] | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return [Modelo(**m) for m in raw["modelos"]]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _idade_cache_segundos() -> float | None:
    if not _CACHE_PATH.exists():
        return None
    return time.time() - _CACHE_PATH.stat().st_mtime


def _gravar_cache(modelos: list[Modelo]) -> None:
    data = {"modelos": [m.__dict__ for m in modelos]}
    try:
        _CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # Cache é otimização; falha ao gravar não quebra o fluxo.


def _buscar_remoto(timeout: float) -> list[Modelo]:
    resp = http.get(
        MODELS_URL,
        headers={"User-Agent": "automacoes-notion"},
        timeout=timeout,
    )
    resp.raise_for_status()
    modelos = _parse_modelos(resp.json())
    if not modelos:
        raise CatalogoErro("a API do OpenRouter não retornou modelos.")
    return modelos


def carregar_modelos(
    forcar_atualizacao: bool = False,
    timeout: float = 10.0,
) -> list[Modelo]:
    """Retorna o catálogo de modelos do OpenRouter.

    Usa cache local quando fresco (< 24 h); senão tenta a rede e atualiza o cache.
    Se a rede falhar mas houver cache (mesmo vencido), usa o cache. Só levanta
    ``CatalogoErro`` quando não há nem rede nem cache.
    """
    idade = _idade_cache_segundos()
    cache_fresco = idade is not None and idade < _CACHE_TTL_SECONDS

    if not forcar_atualizacao and cache_fresco:
        em_cache = _ler_cache()
        if em_cache:
            return em_cache

    try:
        modelos = _buscar_remoto(timeout=timeout)
        _gravar_cache(modelos)
        return modelos
    except (http.RequestException, ConnectionError, json.JSONDecodeError, CatalogoErro) as exc:
        em_cache = _ler_cache()
        if em_cache:
            return em_cache
        raise CatalogoErro(
            f"não foi possível obter a lista de modelos do OpenRouter (sem rede e sem cache): {exc}"
        ) from exc


def empresas(modelos: list[Modelo]) -> list[str]:
    """Empresas distintas, em ordem alfabética."""
    return sorted({m.empresa for m in modelos})


def modelos_da_empresa(modelos: list[Modelo], empresa: str) -> list[Modelo]:
    """Modelos de uma empresa, do mais caro (saída) para o mais barato.

    Preço alto costuma indicar modelo mais capaz, então premium fica no topo.
    """
    return sorted(
        (m for m in modelos if m.empresa == empresa),
        key=lambda m: (-m.preco_saida, m.nome),
    )


# ---------------------------------------------------------------------------
# Protocolo ProvedorIA (contrato único para services/ia.py)
# ---------------------------------------------------------------------------


@runtime_checkable
class ProvedorIA(Protocol):
    """Contrato que qualquer provedor de IA implementa.

    A camada de serviço (``services/ia.py``) consome apenas este protocolo —
    não conhece OpenRouter, assinatura nem nenhum provedor específico.
    """

    def completar(self, prompt: str, *, modelo: str | None = None) -> str:
        """Envia um prompt e devolve a resposta como texto."""
        ...


# ---------------------------------------------------------------------------
# Implementação: ProvedorOpenRouter
# ---------------------------------------------------------------------------


class ProvedorOpenRouter:
    """Provedor de IA via OpenRouter (pague por uso).

    Usa a API de chat completions (``/api/v1/chat/completions``). A chave é
    lida do ambiente no momento da chamada — nunca armazenada em atributo
    visível, e nunca aparece em repr/log.
    """

    def __init__(
        self,
        modelo_padrao: str = "openai/gpt-4.1-nano",
        timeout: float = 60.0,
    ) -> None:
        self._modelo_padrao = modelo_padrao
        self._timeout = timeout

    def completar(self, prompt: str, *, modelo: str | None = None) -> str:
        """Chama a API de chat do OpenRouter e devolve o texto da resposta."""

        chave = _resolver_chave()
        modelo_id = modelo or self._modelo_padrao

        try:
            resp = http.post(
                CHAT_URL,
                json={
                    "model": modelo_id,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "Authorization": f"Bearer {chave}",
                    "User-Agent": "automacoes-notion",
                    "HTTP-Referer": "https://github.com/Felipe-Alcantara/Automa-es-do-Notion",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except http.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            raise ProvedorErro(
                f"OpenRouter retornou HTTP {code} para o modelo {modelo_id}."
            ) from exc
        except http.RequestException as exc:
            raise ProvedorErro(f"falha de rede ao chamar o OpenRouter: {exc}") from exc

        return _extrair_resposta(resp.json())

    def __repr__(self) -> str:
        return f"ProvedorOpenRouter(modelo_padrao={self._modelo_padrao!r})"


def _resolver_chave() -> str:
    """Resolve a chave do OpenRouter a partir do ambiente.

    Tenta ``OPENROUTER_API_KEY`` direto; se não existir, tenta o ``.env`` via
    ``core.config`` (que já é lido pelo servidor Django).
    """
    import os

    chave = os.environ.get(ENV_OPENROUTER_KEY, "").strip()
    if not chave:
        try:
            from core.config import carregar_env_file

            carregar_env_file()
            chave = os.environ.get(ENV_OPENROUTER_KEY, "").strip()
        except ImportError:
            pass
    if not chave:
        raise ProvedorErro(
            "OPENROUTER_API_KEY não configurada. Defina a variável de ambiente ou adicione ao .env."
        )
    return chave


def _extrair_resposta(body: dict[str, Any]) -> str:
    """Extrai o texto da resposta do formato chat completions."""
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProvedorErro(
            "resposta inesperada do OpenRouter (sem choices/message/content)."
        ) from exc
