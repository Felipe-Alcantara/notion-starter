"""Cliente HTTP para a API do Notion."""

from __future__ import annotations

import json
import os
import random
import time
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlencode

import requests

from .utils import safe_json_dumps

try:  # ``NotRequired`` só existe em ``typing`` a partir do 3.11.
    from typing import NotRequired, TypedDict
except ImportError:  # pragma: no cover - fallback para Python 3.10
    from typing_extensions import NotRequired, TypedDict

from .constants import (
    NOTION_BACKOFF_BASE,
    NOTION_BACKOFF_MAXIMO,
    NOTION_BASE_URL,
    NOTION_DATA_SOURCE_VERSION,
    NOTION_JITTER,
    NOTION_MAX_RETRIES,
    NOTION_RATE_LIMIT_STATUS_CODES,
    NOTION_RETRYABLE_STATUS_CODES,
    NOTION_SCHEMA_CACHE_TTL,
    NOTION_TIMEOUT_SECONDS,
    NOTION_TOKEN_ENV,
    NOTION_TOKEN_PREFIX,
    NOTION_UPLOAD_MAX_BYTES,
    NOTION_VERSION,
)
from .content import planejar_lotes
from .exceptions import (
    NotionAPIError,
    NotionConfigurationError,
    NotionConnectionError,
    NotionEscritaSalvaError,
    NotionHTTPError,
    NotionInvalidResponseError,
)
from .logging import get_logger

logger = get_logger()


class DatabaseParentPayload(TypedDict):
    """Payload do parent de um database."""

    type: str
    page_id: str


class DatabaseTitleTextPayload(TypedDict):
    """Payload de texto do título de um database."""

    content: str


class DatabaseTitleItemPayload(TypedDict):
    """Item do título de um database."""

    type: str
    text: DatabaseTitleTextPayload


class DatabaseCreatePayload(TypedDict):
    """Payload para criação de database."""

    parent: DatabaseParentPayload
    title: list[DatabaseTitleItemPayload]
    properties: dict[str, dict[str, object]]
    is_inline: NotRequired[bool]
    icon: NotRequired[dict[str, object]]
    description: NotRequired[list[dict[str, object]]]


class DatabaseUpdatePayload(TypedDict):
    """Payload para atualização de database."""

    title: NotRequired[list[DatabaseTitleItemPayload]]
    properties: NotRequired[dict[str, dict[str, object]]]


class DatabaseQueryPayload(TypedDict):
    """Payload para consulta de database."""

    page_size: int
    filter: NotRequired[dict[str, object]]
    start_cursor: NotRequired[str]


class DataSourceQueryPayload(TypedDict):
    """Payload para consulta de um *data source* (modelo novo de database)."""

    page_size: int
    filter: NotRequired[dict[str, object]]
    start_cursor: NotRequired[str]


class SearchPayload(TypedDict):
    """Payload para busca no workspace via ``/search``."""

    page_size: int
    query: NotRequired[str]
    filter: NotRequired[dict[str, object]]
    start_cursor: NotRequired[str]


class PageParentPayload(TypedDict):
    """Parent de página vinculada a um database."""

    database_id: str


class PageCreatePayload(TypedDict):
    """Payload para criação de página."""

    parent: PageParentPayload
    properties: dict[str, dict[str, object]]


class PageUpdatePayload(TypedDict):
    """Payload para atualização de página."""

    properties: dict[str, dict[str, object]]


class PageArchivePayload(TypedDict):
    """Payload para arquivamento de página."""

    archived: bool


class PosicaoInicioPayload(TypedDict):
    """``position`` que insere os blocos no **início** da lista de filhos."""

    type: Literal["start"]


class AncoraBlocoPayload(TypedDict):
    """Bloco irmão usado como âncora de ``position: after_block``."""

    id: str


class PosicaoAposBlocoPayload(TypedDict):
    """``position`` que insere os blocos logo **depois** de um bloco irmão."""

    type: Literal["after_block"]
    after_block: AncoraBlocoPayload


#: As posições que :meth:`NotionClient.anexar_blocos` sabe montar. A terceira
#: (``{"type": "end"}``) é o padrão da API e corresponde a omitir ``position``.
PosicaoAnexoPayload = PosicaoInicioPayload | PosicaoAposBlocoPayload


class BlocksAppendPayload(TypedDict, total=False):
    """Payload para anexar blocos filhos a uma página ou bloco."""

    children: list[dict[str, object]]
    position: PosicaoAnexoPayload


class BlockRestorePayload(TypedDict):
    """Payload que tira um bloco da lixeira (``in_trash: false``)."""

    in_trash: bool


class BlockArchivePayload(TypedDict):
    """Payload para arquivar um bloco (delete reversível do Notion)."""

    archived: bool


def _eh_leitura(metodo: str, path: str) -> bool:
    """GET, ou POST que só consulta (``/search`` e ``.../query``)."""

    rota = path.split("?", 1)[0]
    if metodo.upper() == "GET":
        return True
    return metodo.upper() == "POST" and (rota == "/search" or rota.endswith("/query"))


def _escrita_foi_salva(dados_adicionais: dict[str, Any]) -> bool:
    """O 503 de uma escrita diz que ela foi salva?

    Primeiro os campos estruturados (``committed_resource_id``,
    ``committed_child_ids``); o texto de ``retry_guidance`` ("Do not repeat
    the write") é só reserva — num update de objeto existente é o único sinal.
    """

    if dados_adicionais.get("committed_resource_id") or dados_adicionais.get(
        "committed_child_ids"
    ):
        return True
    orientacao = dados_adicionais.get("retry_guidance")
    textos = orientacao if isinstance(orientacao, list) else [orientacao]
    return any("do not repeat the write" in str(texto).lower() for texto in textos if texto)


def deve_retentar(
    *,
    metodo: str,
    path: str,
    status_code: int,
    idempotente: bool,
    dados_adicionais: dict[str, Any],
) -> bool:
    """Regra única de retentativa (também usada no upload), conforme a documentação.

    https://developers.notion.com/reference/request-limits:

    - 429 e 529 se repetem — **exceto** 429 com ``rate_limit_reason``
      ``public_api_request_blocked`` (acesso bloqueado; repetir não adianta);
    - 409/500/502/504 só em operação idempotente;
    - 503 só em **leitura**: uma escrita pode ter sido salva mesmo com 503, e a
      documentação pede para conferir o estado antes de repetir.

    Args:
        metodo: Método HTTP.
        path: Caminho relativo da chamada.
        status_code: Status recebido.
        idempotente: Se repetir a operação preserva o efeito.
        dados_adicionais: ``additional_data`` do corpo do erro.

    Returns:
        Se a chamada pode ser repetida (ainda sujeita ao limite de tentativas).
    """

    if status_code == 429 and (
        dados_adicionais.get("rate_limit_reason") == "public_api_request_blocked"
    ):
        return False
    if status_code in NOTION_RATE_LIMIT_STATUS_CODES:
        return True
    if status_code not in NOTION_RETRYABLE_STATUS_CODES:
        return False
    if status_code == 503 and not _eh_leitura(metodo, path):
        return False
    return idempotente


def _validar_identificador(identificador: str, nome_campo: str) -> str:
    """Valida um identificador obrigatório do Notion.

    Args:
        identificador: Valor bruto recebido.
        nome_campo: Nome lógico do campo, usado na mensagem de erro.

    Returns:
        O identificador limpo.

    Raises:
        NotionConfigurationError: Se o identificador estiver vazio.
    """

    limpo = (identificador or "").strip()
    if not limpo:
        raise NotionConfigurationError(f"{nome_campo} não pode estar vazio.")
    return limpo


class NotionClient:
    """Wrapper fino e tipado sobre a API REST do Notion.

    Exemplo:
        >>> client = NotionClient(token="ntn_...")
        >>> client.criar_pagina(database_id, {"Nome": {"title": [{"text": {"content": "Oi"}}]}})

    Args:
        token: Token de integração do Notion. Quando omitido, é lido da
            variável de ambiente ``NOTION_TOKEN``.
        base_url: Sobrescreve a URL base da API (útil para testes).
        timeout: Timeout por requisição, em segundos.
        version: Valor enviado no header ``Notion-Version``.
        max_retries: Número de retentativas em operações idempotentes após
            erros transitórios. ``0`` desabilita o retry.
        backoff_base: Base do backoff exponencial entre retentativas, em
            segundos. O tempo de espera é ``backoff_base * 2^tentativa``,
            exceto em 429 com ``Retry-After``, que tem prioridade.
        cache_ttl: TTL do cache de schema (``get_database``), em segundos.
            ``0`` desabilita o cache.
        jitter: Fração aleatória somada a cada espera (``0.25`` = até +25%),
            para processos paralelos não repetirem no mesmo instante. ``0``
            deixa as esperas exatas.

    Raises:
        NotionConfigurationError: Se nenhum token válido puder ser resolvido.
        ValueError: Se a configuração de retry/cache for negativa.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = NOTION_BASE_URL,
        timeout: int = NOTION_TIMEOUT_SECONDS,
        version: str = NOTION_VERSION,
        max_retries: int = NOTION_MAX_RETRIES,
        backoff_base: float = NOTION_BACKOFF_BASE,
        cache_ttl: int = NOTION_SCHEMA_CACHE_TTL,
        jitter: float = NOTION_JITTER,
    ) -> None:
        self._token = self._resolver_token(token)
        if max_retries < 0:
            raise ValueError("max_retries não pode ser negativo.")
        if backoff_base < 0:
            raise ValueError("backoff_base não pode ser negativo.")
        if jitter < 0:
            raise ValueError("jitter não pode ser negativo.")
        self._jitter = jitter
        if cache_ttl < 0:
            raise ValueError("cache_ttl não pode ser negativo.")

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._version = version
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._cache_ttl = cache_ttl
        self._cache_schema: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _resolver_token(token: str | None) -> str:
        """Resolve e valida o token de integração.

        Args:
            token: Token explícito, ou ``None`` para ler do ambiente.

        Returns:
            O token validado.

        Raises:
            NotionConfigurationError: Se o token estiver ausente ou malformado.
        """

        bruto = token if token is not None else os.environ.get(NOTION_TOKEN_ENV, "")
        limpo = str(bruto).strip()
        if not limpo:
            raise NotionConfigurationError(
                f"Token do Notion ausente. Passe token=... ou defina a "
                f"variável de ambiente {NOTION_TOKEN_ENV}."
            )
        if not limpo.startswith(NOTION_TOKEN_PREFIX):
            raise NotionConfigurationError(
                f"Token do Notion inválido: ele deve começar com '{NOTION_TOKEN_PREFIX}'."
            )
        return limpo

    def _headers(self, version: str | None = None) -> dict[str, str]:
        """Monta os headers padrão autenticados.

        Args:
            version: Quando informado, sobrescreve o ``Notion-Version`` padrão
                apenas nesta chamada (usado pelos endpoints de *data sources*,
                que exigem uma versão mais nova da API).
        """

        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Notion-Version": version or self._version,
        }

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        idempotente: bool,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Executa uma requisição JSON contra a API do Notion.

        Operações idempotentes são retentadas em erros transitórios e falhas de
        rede, com backoff exponencial e jitter. Em criações, o retry fica
        restrito a respostas 429/529, nas quais o Notion orienta aguardar e
        repetir; falhas ambíguas de rede ou 5xx não são repetidas para evitar
        duplicatas. Respostas com ``Retry-After`` têm prioridade. A regra toda
        está em :func:`deve_retentar`: 429 "bloqueado" nunca se repete e 503
        numa **escrita** também não — se o corpo disser que a escrita foi
        salva, sobe :class:`~notion_starter.exceptions.NotionEscritaSalvaError`.

        Args:
            method: Método HTTP.
            path: Caminho relativo à URL base.
            payload: Corpo JSON opcional.
            idempotente: Se repetir a operação preserva o mesmo efeito.
            version: ``Notion-Version`` específico desta chamada (opcional).

        Returns:
            A resposta JSON decodificada.

        Raises:
            NotionHTTPError: Se a API responder com 4xx/5xx após esgotadas
                as retentativas.
            NotionEscritaSalvaError: 503 numa escrita que o Notion salvou.
            NotionConnectionError: Em falha de rede ou timeout após esgotadas
                as retentativas.
            NotionInvalidResponseError: Se a resposta não for JSON válido.
        """

        url = f"{self._base_url}{path}"
        total_tentativas = self._max_retries + 1

        for tentativa in range(total_tentativas):
            try:
                # Usar serialização JSON segura para prevenir erros de surrogate
                json_payload = safe_json_dumps(payload) if payload else None

                resp = requests.request(
                    method=method,
                    url=url,
                    json=json.loads(json_payload) if json_payload else None,
                    headers=self._headers(version),
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if idempotente and tentativa + 1 < total_tentativas:
                    espera = self._espera_exponencial(tentativa)
                    logger.warning(
                        "Retentativa %d/%d após erro de conexão",
                        tentativa + 1,
                        self._max_retries,
                        extra={"path": path, "error": str(exc)},
                    )
                    time.sleep(espera)
                    continue
                logger.error(
                    "Erro de conexão com o Notion",
                    extra={"path": path, "error": str(exc)},
                )
                raise NotionConnectionError(str(exc)) from exc

            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError as exc:
                    logger.error("Resposta JSON inválida do Notion", extra={"path": path})
                    raise NotionInvalidResponseError(
                        "A API do Notion retornou um JSON inválido."
                    ) from exc

            erro = NotionHTTPError(resp.status_code, resp.text)
            if (
                resp.status_code == 503
                and not _eh_leitura(method, path)
                and _escrita_foi_salva(erro.dados_adicionais)
            ):
                logger.error(
                    "Escrita salva pelo Notion apesar do 503; não será repetida",
                    extra={"path": path},
                )
                raise NotionEscritaSalvaError(resp.status_code, resp.text)
            if (
                deve_retentar(
                    metodo=method,
                    path=path,
                    status_code=resp.status_code,
                    idempotente=idempotente,
                    dados_adicionais=erro.dados_adicionais,
                )
                and tentativa + 1 < total_tentativas
            ):
                espera = self._calcular_espera(resp, tentativa)
                logger.warning(
                    "Retentativa %d/%d após HTTP %d",
                    tentativa + 1,
                    self._max_retries,
                    resp.status_code,
                    extra={"path": path},
                )
                time.sleep(espera)
                continue

            logger.error(
                "Erro HTTP do Notion",
                extra={"status_code": resp.status_code, "path": path},
            )
            raise erro

        raise RuntimeError("Fluxo de requisição terminou sem resposta.")

    def _calcular_espera(self, resp: requests.Response, tentativa: int) -> float:
        """Calcula o tempo de espera respeitando ``Retry-After``.

        Se a resposta contém o header ``Retry-After`` (comum em 429), usa esse
        valor. Caso contrário, usa backoff exponencial:
        ``backoff_base * 2^tentativa`` (com teto). As duas levam jitter.
        """

        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return self._com_jitter(max(float(retry_after), 0.0))
            except ValueError:
                pass
        return self._espera_exponencial(tentativa)

    def _espera_exponencial(self, tentativa: int) -> float:
        """``backoff_base * 2^tentativa``, com teto de 30 s e jitter."""

        return self._com_jitter(min(self._backoff_base * (2**tentativa), NOTION_BACKOFF_MAXIMO))

    def _com_jitter(self, espera: float) -> float:
        if self._jitter <= 0 or espera <= 0:
            return espera
        return espera + random.uniform(0, espera * self._jitter)

    # -- Busca -------------------------------------------------------------

    def buscar(
        self,
        query: str | None = None,
        page_size: int = 100,
        buscar_todos: bool = False,
        filtro: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca páginas e databases compartilhados com a integração.

        Percorre o endpoint ``/search`` do Notion, que retorna apenas os itens
        que a integração tem permissão de ver. Sem ``query``, lista tudo o que é
        visível — útil para inventariar o workspace.

        Args:
            query: Texto para casar com o título dos itens. ``None`` retorna tudo.
            page_size: Quantidade de itens por página.
            buscar_todos: Quando verdadeiro, percorre toda a paginação.
            filtro: Filtro Notion opcional (ex.: só páginas ou só databases).

        Returns:
            A lista de itens (páginas e/ou databases) retornados pela API.

        Raises:
            ValueError: Se ``page_size`` for menor que 1.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        if page_size < 1:
            raise ValueError("page_size deve ser maior que zero.")

        payload: SearchPayload = {"page_size": page_size}
        if query:
            payload["query"] = query
        if filtro:
            payload["filter"] = filtro

        resultados: list[dict[str, Any]] = []

        while True:
            data = self._request_json(
                method="POST",
                path="/search",
                payload=payload,
                idempotente=True,
            )
            resultados.extend(data.get("results", []))

            if not buscar_todos or not data.get("has_more"):
                break

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break
            payload["start_cursor"] = next_cursor

        return resultados

    # -- Databases ---------------------------------------------------------

    def get_database(self, database_id: str) -> dict[str, Any]:
        """Busca os metadados de um database Notion.

        Usa cache em memória quando ``cache_ttl > 0`` — o schema de um database
        muda raramente, então evitar chamadas repetidas reduz latência e
        consumo de rate limit. Falha no cache nunca quebra o fluxo.

        Args:
            database_id: ID do database.

        Returns:
            A resposta JSON do database solicitado.
        """

        limpo = _validar_identificador(database_id, "database_id")

        if self._cache_ttl > 0 and limpo in self._cache_schema:
            instante, dados = self._cache_schema[limpo]
            if time.monotonic() - instante < self._cache_ttl:
                return deepcopy(dados)
            self._cache_schema.pop(limpo, None)

        resultado = self._request_json(
            method="GET",
            path=f"/databases/{limpo}",
            idempotente=True,
        )

        if self._cache_ttl > 0:
            self._cache_schema[limpo] = (time.monotonic(), deepcopy(resultado))

        return resultado

    def invalidar_cache(self, database_id: str | None = None) -> None:
        """Invalida o cache de schema.

        Args:
            database_id: ID específico para invalidar. ``None`` limpa todo
                o cache.
        """

        if database_id is None:
            self._cache_schema.clear()
        else:
            limpo = _validar_identificador(database_id, "database_id")
            self._cache_schema.pop(limpo, None)

    def criar_database(
        self,
        pagina_id: str,
        titulo: str,
        propriedades: dict[str, dict[str, object]],
        *,
        is_inline: bool = False,
        icone: str | None = None,
        descricao: str | None = None,
        prefixo_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria um novo database como filho de uma página.

        Args:
            pagina_id: ID da página pai.
            titulo: Título do database.
            propriedades: Schema do database no formato da API.
            is_inline: Quando ``True``, cria o database embutido no corpo da
                página (inline) em vez de página cheia.
            icone: Emoji usado como ícone do database, quando informado.
            descricao: Descrição textual do database, quando informada.
            prefixo_id: Atalho para numeração automática: adiciona uma
                propriedade ``ID`` do tipo ``unique_id`` com este prefixo.
                **Atenção**: o prefixo de ``unique_id`` é único por workspace —
                use um prefixo distinto por database, ou a API rejeita a criação.

        Returns:
            A resposta JSON do database criado.

        Raises:
            ValueError: Se ``prefixo_id`` for usado e ``propriedades`` já
                definir uma propriedade ``ID``.
        """

        pagina_limpa = _validar_identificador(pagina_id, "pagina_id")
        titulo_limpo = _validar_identificador(titulo, "titulo")
        payload: DatabaseCreatePayload = {
            "parent": {"type": "page_id", "page_id": pagina_limpa},
            "title": [{"type": "text", "text": {"content": titulo_limpo}}],
            "properties": dict(propriedades),
        }
        if prefixo_id is not None:
            prefixo_limpo = _validar_identificador(prefixo_id, "prefixo_id")
            if "ID" in payload["properties"]:
                raise ValueError(
                    "prefixo_id adiciona a propriedade 'ID' automaticamente; "
                    "remova a propriedade 'ID' de propriedades ou o atalho."
                )
            payload["properties"]["ID"] = {"unique_id": {"prefix": prefixo_limpo}}
        if is_inline:
            payload["is_inline"] = True
        if icone is not None:
            payload["icon"] = {"type": "emoji", "emoji": icone}
        if descricao is not None:
            payload["description"] = [
                {"type": "text", "text": {"content": descricao}}
            ]
        return self._request_json(
            method="POST",
            path="/databases",
            payload=payload,
            idempotente=False,
        )

    def atualizar_database(
        self,
        database_id: str,
        *,
        titulo: str | None = None,
        propriedades: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        """Atualiza metadados e schema de um database.

        Args:
            database_id: ID do database.
            titulo: Novo título do database, quando informado.
            propriedades: Alterações de schema por propriedade.

        Returns:
            A resposta JSON do database atualizado.

        Raises:
            ValueError: Se nenhum campo for informado.
        """

        limpo = _validar_identificador(database_id, "database_id")
        payload: DatabaseUpdatePayload = {}
        if titulo is not None:
            titulo_limpo = _validar_identificador(titulo, "titulo")
            payload["title"] = [{"type": "text", "text": {"content": titulo_limpo}}]
        if propriedades is not None:
            payload["properties"] = propriedades
        if not payload:
            raise ValueError("Informe titulo ou propriedades para atualizar o database.")

        resultado = self._request_json(
            method="PATCH",
            path=f"/databases/{limpo}",
            payload=payload,
            idempotente=True,
        )
        self.invalidar_cache(limpo)
        return resultado

    def consultar_database(
        self,
        database_id: str,
        page_size: int = 100,
        buscar_todos: bool = False,
        filtro: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        """Consulta as páginas de um database com suporte a paginação.

        Args:
            database_id: ID do database.
            page_size: Quantidade de registros por página.
            buscar_todos: Quando verdadeiro, percorre toda a paginação.
            filtro: Filtro Notion opcional.

        Returns:
            A lista de páginas retornadas pela API.

        Raises:
            NotionConfigurationError: Se ``database_id`` for inválido.
            ValueError: Se ``page_size`` for menor que 1.
        """

        limpo = _validar_identificador(database_id, "database_id")
        if page_size < 1:
            raise ValueError("page_size deve ser maior que zero.")

        payload: DatabaseQueryPayload = {"page_size": page_size}
        if filtro:
            payload["filter"] = filtro

        resultados: list[dict[str, Any]] = []

        while True:
            data = self._request_json(
                method="POST",
                path=f"/databases/{limpo}/query",
                payload=payload,
                idempotente=True,
            )
            resultados.extend(data.get("results", []))

            if not buscar_todos or not data.get("has_more"):
                break

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break
            payload["start_cursor"] = next_cursor

        return resultados

    # -- Data sources (databases do modelo novo) ---------------------------

    def listar_data_sources(self, database_id: str) -> list[dict[str, Any]]:
        """Lista os *data sources* (fontes de dados) de um database.

        O Notion introduziu em 2025 o modelo multi-fonte: um database pode
        conter um ou mais *data sources*, e as linhas passam a ser consultadas
        por fonte, não mais pelo database. Este método lê esse índice usando a
        versão de API exigida, sem alterar a versão padrão das demais rotas.

        Args:
            database_id: ID do database.

        Returns:
            A lista de ``{"id", "name", ...}`` de cada fonte. Vazia se o
            database não expõe fontes a esta integração.

        Raises:
            NotionConfigurationError: Se ``database_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(database_id, "database_id")
        data = self._request_json(
            method="GET",
            path=f"/databases/{limpo}",
            idempotente=True,
            version=NOTION_DATA_SOURCE_VERSION,
        )
        fontes = data.get("data_sources")
        return fontes if isinstance(fontes, list) else []

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        """Lê o schema (propriedades) de um *data source*.

        Args:
            data_source_id: ID da fonte de dados.

        Returns:
            O objeto ``data_source`` com ``properties``.

        Raises:
            NotionConfigurationError: Se ``data_source_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(data_source_id, "data_source_id")
        return self._request_json(
            method="GET",
            path=f"/data_sources/{limpo}",
            idempotente=True,
            version=NOTION_DATA_SOURCE_VERSION,
        )

    def atualizar_data_source(
        self,
        data_source_id: str,
        *,
        propriedades: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """Atualiza o schema (propriedades) de um *data source*.

        No modelo novo do Notion as colunas vivem no *data source*, não no
        database. Criar/alterar propriedades — inclusive opções de ``status``,
        ``select`` e alvos de ``relation`` — exige a versão 2025-09-03 e o
        endpoint ``PATCH /data_sources/{id}``.

        Args:
            data_source_id: ID da fonte de dados.
            propriedades: Alterações de schema por propriedade.

        Returns:
            O objeto ``data_source`` atualizado, com ``properties``.

        Raises:
            NotionConfigurationError: Se ``data_source_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(data_source_id, "data_source_id")
        return self._request_json(
            method="PATCH",
            path=f"/data_sources/{limpo}",
            payload={"properties": propriedades},
            idempotente=True,
            version=NOTION_DATA_SOURCE_VERSION,
        )

    def criar_pagina_em_fonte(
        self,
        data_source_id: str,
        propriedades: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """Cria uma página (linha) dentro de um *data source*.

        Equivalente de ``criar_pagina`` para o modelo novo: o ``parent`` passa
        a ser ``data_source_id`` em vez de ``database_id``.

        Args:
            data_source_id: ID da fonte de dados de destino.
            propriedades: Propriedades da nova página.

        Returns:
            A resposta JSON da página criada.

        Raises:
            NotionConfigurationError: Se ``data_source_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(data_source_id, "data_source_id")
        return self._request_json(
            method="POST",
            path="/pages",
            payload={
                "parent": {"type": "data_source_id", "data_source_id": limpo},
                "properties": propriedades,
            },
            idempotente=False,
            version=NOTION_DATA_SOURCE_VERSION,
        )

    def consultar_data_source(
        self,
        data_source_id: str,
        page_size: int = 100,
        buscar_todos: bool = False,
        filtro: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        """Consulta as linhas (páginas) de um *data source*, com paginação.

        É o equivalente de ``consultar_database`` para o modelo novo: a query
        migrou de ``/databases/{id}/query`` para ``/data_sources/{id}/query``.

        Args:
            data_source_id: ID da fonte de dados.
            page_size: Quantidade de registros por página.
            buscar_todos: Quando verdadeiro, percorre toda a paginação.
            filtro: Filtro Notion opcional.

        Returns:
            A lista de páginas (linhas) retornadas pela API.

        Raises:
            NotionConfigurationError: Se ``data_source_id`` for inválido.
            ValueError: Se ``page_size`` for menor que 1.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(data_source_id, "data_source_id")
        if page_size < 1:
            raise ValueError("page_size deve ser maior que zero.")

        payload: DataSourceQueryPayload = {"page_size": page_size}
        if filtro:
            payload["filter"] = filtro

        resultados: list[dict[str, Any]] = []

        while True:
            data = self._request_json(
                method="POST",
                path=f"/data_sources/{limpo}/query",
                payload=payload,
                idempotente=True,
                version=NOTION_DATA_SOURCE_VERSION,
            )
            resultados.extend(data.get("results", []))

            if not buscar_todos or not data.get("has_more"):
                break

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break
            payload["start_cursor"] = next_cursor

        return resultados

    # -- Páginas -----------------------------------------------------------

    def criar_pagina(
        self,
        database_id: str,
        propriedades: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """Cria uma nova página dentro de um database.

        Args:
            database_id: ID do database de destino.
            propriedades: Propriedades da nova página.

        Returns:
            A resposta JSON da página criada.
        """

        limpo = _validar_identificador(database_id, "database_id")
        payload: PageCreatePayload = {
            "parent": {"database_id": limpo},
            "properties": propriedades,
        }
        return self._request_json(
            method="POST",
            path="/pages",
            payload=payload,
            idempotente=False,
        )

    def criar_subpagina(
        self,
        pagina_pai_id: str,
        titulo: str,
        *,
        blocos: list[dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        """Cria uma página filha (subpágina) dentro de outra página.

        Diferente de ``criar_pagina`` (que cria uma linha num database), esta
        cria uma página solta como filha de ``pagina_pai_id`` — útil para
        organizar conteúdo em subpáginas, como um README aninhado dentro da
        página de um projeto.

        Cada requisição aceita no máximo 100 blocos de topo, 1000 elementos de
        bloco (contando os filhos, como linhas de tabela) e 500 KB; o primeiro
        lote que cabe entra na criação e o restante é anexado em lotes
        (:func:`~notion_starter.content.planejar_lotes`), de forma transparente
        para o chamador.

        Args:
            pagina_pai_id: ID da página que receberá a subpágina.
            titulo: Título da subpágina (vira o ``title`` da nova página).
            blocos: Conteúdo opcional, no formato de blocos da API do Notion.

        Returns:
            A resposta JSON da subpágina criada.

        Raises:
            NotionConfigurationError: Se ``pagina_pai_id`` for inválido.
            ValueError: Se ``titulo`` for vazio.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(pagina_pai_id, "pagina_pai_id")
        titulo_limpo = _validar_identificador(titulo, "titulo")
        todos = list(blocos or [])
        payload: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": limpo},
            "properties": {
                "title": [{"type": "text", "text": {"content": titulo_limpo}}]
            },
        }
        lotes = planejar_lotes(todos) if todos else []
        if lotes:
            payload["children"] = lotes[0]

        resposta = self._request_json(
            method="POST",
            path="/pages",
            payload=payload,
            idempotente=False,
        )

        if len(lotes) > 1:
            page_id = str(resposta.get("id") or "")
            for lote in lotes[1:]:
                self.anexar_blocos(page_id, lote)

        return resposta

    def obter_pagina(self, page_id: str) -> dict[str, Any]:
        """Busca uma página existente pelo ID.

        A resposta traz cada propriedade já com o seu ``type``, o que permite
        editar valores sem consultar o schema do database à parte.

        Args:
            page_id: ID da página.

        Returns:
            A resposta JSON da página.
        """

        limpo = _validar_identificador(page_id, "page_id")
        return self._request_json(
            method="GET",
            path=f"/pages/{limpo}",
            idempotente=True,
        )

    def ler_itens_de_propriedade(self, page_id: str, property_id: str) -> list[dict[str, Any]]:
        """Lê o valor **completo** de uma propriedade, percorrendo a paginação.

        ``GET /pages/{id}`` corta propriedades longas: numa ``relation`` vêm no
        máximo 25 referências, com ``has_more: true`` avisando que há mais
        (https://developers.notion.com/reference/page-property-values). O valor
        inteiro só sai por ``GET /pages/{page_id}/properties/{property_id}``
        (https://developers.notion.com/reference/retrieve-a-page-property),
        lido página a página até ``has_more`` ser falso.

        Args:
            page_id: ID da página.
            property_id: ID da propriedade **exatamente como a API o devolve**
                no objeto da página (já codificado para URL, ex.: ``%3AAbc``);
                não é codificado de novo aqui.

        Returns:
            Os *property items* na ordem da API. Propriedades paginadas
            (relation, rich_text, title, people, rollup) devolvem um item por
            elemento (ex.: ``{"type": "relation", "relation": {"id": ...}}``);
            as demais, um item só.

        Raises:
            NotionConfigurationError: Se ``page_id`` ou ``property_id`` forem vazios.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        pagina = _validar_identificador(page_id, "page_id")
        propriedade = _validar_identificador(property_id, "property_id")
        itens: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {"page_size": "100"}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request_json(
                method="GET",
                path=f"/pages/{pagina}/properties/{propriedade}?{urlencode(params)}",
                idempotente=True,
            )
            if data.get("object") != "list":
                itens.append(data)
                break
            itens.extend(item for item in data.get("results", []) if isinstance(item, dict))
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
        return itens

    def atualizar_pagina(
        self,
        page_id: str,
        propriedades: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """Atualiza as propriedades de uma página existente.

        Args:
            page_id: ID da página.
            propriedades: Propriedades atualizadas.

        Returns:
            A resposta JSON da página atualizada.
        """

        limpo = _validar_identificador(page_id, "page_id")
        payload: PageUpdatePayload = {"properties": propriedades}
        return self._request_json(
            method="PATCH",
            path=f"/pages/{limpo}",
            payload=payload,
            idempotente=True,
        )

    def arquivar_pagina(self, page_id: str) -> dict[str, Any]:
        """Arquiva uma página do Notion.

        Args:
            page_id: ID da página.

        Returns:
            A resposta JSON da API.
        """

        limpo = _validar_identificador(page_id, "page_id")
        payload: PageArchivePayload = {"archived": True}
        return self._request_json(
            method="PATCH",
            path=f"/pages/{limpo}",
            payload=payload,
            idempotente=True,
        )

    def mover_pagina(
        self,
        page_id: str,
        novo_pai_id: str,
        *,
        tipo_pai: str = "page_id",
    ) -> dict[str, Any]:
        """Re-parenteia (move) uma página para outra página ou database.

        A API do Notion aceita alterar o ``parent`` de uma página via ``PATCH``,
        o que efetivamente a move de lugar sem recriá-la — preservando conteúdo,
        propriedades e links. Útil para consolidar/reorganizar uma workspace.

        Observação importante: mover uma página que **contém databases** é
        aceito pela API (``200``) mas silenciosamente ignorado; nesse caso, mova
        as databases uma a uma com :meth:`mover_database` e descarte a página
        vazia.

        Args:
            page_id: ID da página a mover.
            novo_pai_id: ID do novo pai (página ou database).
            tipo_pai: ``"page_id"`` (padrão) ou ``"database_id"``.

        Returns:
            A resposta JSON da página atualizada.

        Raises:
            NotionConfigurationError: Se algum identificador for inválido.
            ValueError: Se ``tipo_pai`` não for reconhecido.
        """

        limpo = _validar_identificador(page_id, "page_id")
        pai_limpo = _validar_identificador(novo_pai_id, "novo_pai_id")
        if tipo_pai not in ("page_id", "database_id"):
            raise ValueError("tipo_pai deve ser 'page_id' ou 'database_id'.")
        payload = {"parent": {"type": tipo_pai, tipo_pai: pai_limpo}}
        return self._request_json(
            method="PATCH",
            path=f"/pages/{limpo}",
            payload=payload,
            idempotente=True,
        )

    def mover_database(self, database_id: str, novo_pai_id: str) -> dict[str, Any]:
        """Re-parenteia (move) um database para outra página.

        Move um database inteiro — com todas as suas linhas — para outra página,
        sem recriá-lo. Diferente de :meth:`mover_pagina`, a rota de databases
        exige a versão de API 2025-09-03 (a mesma dos *data sources*); a versão
        padrão das demais chamadas não é alterada.

        Args:
            database_id: ID do database a mover.
            novo_pai_id: ID da página que receberá o database.

        Returns:
            A resposta JSON do database atualizado.

        Raises:
            NotionConfigurationError: Se algum identificador for inválido.
        """

        limpo = _validar_identificador(database_id, "database_id")
        pai_limpo = _validar_identificador(novo_pai_id, "novo_pai_id")
        payload = {"parent": {"type": "page_id", "page_id": pai_limpo}}
        return self._request_json(
            method="PATCH",
            path=f"/databases/{limpo}",
            payload=payload,
            idempotente=True,
            version=NOTION_DATA_SOURCE_VERSION,
        )

    def renomear_database(self, database_id: str, novo_titulo: str) -> dict[str, Any]:
        """Troca o título de um database, sem tocar no schema nem nas linhas.

        :meth:`atualizar_database` também aceita ``titulo``, mas usa a versão
        padrão da API; no modelo novo do Notion o ``PATCH /databases`` só aceita
        a troca de título na versão 2025-09-03 — a mesma dos *data sources*.
        Este método fixa essa versão, sem alterar a das demais chamadas.

        Args:
            database_id: ID do database a renomear.
            novo_titulo: Novo título.

        Returns:
            A resposta JSON do database atualizado.

        Raises:
            NotionConfigurationError: Se ``database_id`` for inválido.
            ValueError: Se ``novo_titulo`` for vazio.
        """

        limpo = _validar_identificador(database_id, "database_id")
        titulo = (novo_titulo or "").strip()
        if not titulo:
            raise ValueError("novo_titulo é obrigatório.")

        resultado = self._request_json(
            method="PATCH",
            path=f"/databases/{limpo}",
            payload={"title": [{"type": "text", "text": {"content": titulo}}]},
            idempotente=True,
            version=NOTION_DATA_SOURCE_VERSION,
        )
        self.invalidar_cache(limpo)
        return resultado

    def enviar_arquivo(
        self,
        conteudo: bytes,
        nome_arquivo: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Envia um arquivo (upload direto) e devolve o ``file_upload`` id.

        Implementa o fluxo de dois passos da *File Upload API* do Notion para
        arquivos de parte única (até 20 MB): (1) cria um ``file_upload`` e
        (2) envia os bytes por ``multipart/form-data``. O id retornado pode ser
        anexado a uma propriedade ``files`` ou a um bloco, via
        :func:`notion_starter.properties.arquivo_enviado`.

        Args:
            conteudo: Bytes do arquivo.
            nome_arquivo: Nome do arquivo (com extensão).
            content_type: MIME type do arquivo.

        Returns:
            O ``id`` do ``file_upload`` pronto para ser referenciado.

        Raises:
            ValueError: Se o arquivo exceder o limite de parte única (20 MB).
            NotionHTTPError: Se a criação ou o envio falharem após esgotadas
                as retentativas.
            NotionConnectionError: Em falha de rede ou timeout no envio após
                esgotadas as retentativas.
        """

        nome_limpo = _validar_identificador(nome_arquivo, "nome_arquivo")
        if len(conteudo) > NOTION_UPLOAD_MAX_BYTES:
            raise ValueError(
                f"Arquivo '{nome_limpo}' tem {len(conteudo)} bytes e excede o "
                f"limite de {NOTION_UPLOAD_MAX_BYTES} bytes (20 MB) do upload "
                f"em parte única da File Upload API."
            )
        criado = self._request_json(
            method="POST",
            path="/file_uploads",
            payload={"filename": nome_limpo, "content_type": content_type},
            idempotente=False,
        )
        upload_id = str(criado["id"])
        self._enviar_multipart(
            path=f"/file_uploads/{upload_id}/send",
            files={"file": (nome_limpo, conteudo, content_type)},
        )
        return upload_id

    def _enviar_multipart(
        self,
        *,
        path: str,
        files: dict[str, tuple[str, bytes, str]],
    ) -> None:
        """Executa um POST ``multipart/form-data`` com retry e backoff.

        Espelha a política de resiliência de :meth:`_request_json` para o
        passo de envio da File Upload API, que não é JSON: enquanto o envio
        não é concluído com sucesso, repeti-lo preserva o mesmo efeito, então
        erros transitórios (429/5xx e falhas de rede) são retentados com
        backoff exponencial, respeitando ``Retry-After`` — pela mesma regra
        de :func:`deve_retentar` (o envio é escrita: 503 não se repete).

        Args:
            path: Caminho relativo à URL base.
            files: Mapeamento ``campo -> (nome, conteúdo, content_type)`` no
                formato aceito pelo ``requests``.

        Raises:
            NotionHTTPError: Se a API responder 4xx/5xx após esgotadas as
                retentativas.
            NotionConnectionError: Em falha de rede ou timeout após esgotadas
                as retentativas.
        """

        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self._version,
        }
        total_tentativas = self._max_retries + 1

        for tentativa in range(total_tentativas):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    files=files,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if tentativa + 1 < total_tentativas:
                    espera = self._espera_exponencial(tentativa)
                    logger.warning(
                        "Retentativa %d/%d após erro de conexão no upload",
                        tentativa + 1,
                        self._max_retries,
                        extra={"path": path, "error": str(exc)},
                    )
                    time.sleep(espera)
                    continue
                logger.error(
                    "Erro de conexão com o Notion no upload",
                    extra={"path": path, "error": str(exc)},
                )
                raise NotionConnectionError(str(exc)) from exc

            if resp.status_code < 400:
                return

            erro = NotionHTTPError(resp.status_code, resp.text)
            if resp.status_code == 503 and _escrita_foi_salva(erro.dados_adicionais):
                raise NotionEscritaSalvaError(resp.status_code, resp.text)
            if (
                deve_retentar(
                    metodo="POST",
                    path=path,
                    status_code=resp.status_code,
                    idempotente=True,
                    dados_adicionais=erro.dados_adicionais,
                )
                and tentativa + 1 < total_tentativas
            ):
                espera = self._calcular_espera(resp, tentativa)
                logger.warning(
                    "Retentativa %d/%d após HTTP %d no upload",
                    tentativa + 1,
                    self._max_retries,
                    resp.status_code,
                    extra={"path": path},
                )
                time.sleep(espera)
                continue

            logger.error(
                "Erro HTTP do Notion no upload",
                extra={"status_code": resp.status_code, "path": path},
            )
            raise erro

        raise RuntimeError("Fluxo de upload terminou sem resposta.")

    # -- Blocos (conteúdo) -------------------------------------------------

    def ler_blocos(
        self,
        block_id: str,
        page_size: int = 100,
        buscar_todos: bool = False,
        recursivo: bool = False,
    ) -> list[dict[str, Any]]:
        """Lê os blocos filhos de uma página ou bloco, com paginação.

        Cada página do Notion é um bloco; seus parágrafos, títulos, listas e
        demais conteúdos são blocos filhos. Este método os devolve crus — a
        conversão para texto/markdown fica a cargo de quem chama (camada de
        conteúdo), preservando a separação de responsabilidades.

        Args:
            block_id: ID da página ou do bloco pai.
            page_size: Quantidade de blocos por página da API.
            buscar_todos: Quando verdadeiro, percorre toda a paginação.
            recursivo: Quando verdadeiro, desce nos blocos que têm filhos
                (colunas, toggles, blocos sincronizados…) e os aninha sob a
                chave ``_filhos`` de cada bloco-pai. Sem ele, lê só um nível —
                o conteúdo dentro de colunas/toggles fica invisível.

        Returns:
            A lista de blocos filhos retornados pela API. Com ``recursivo``,
            cada bloco que tem filhos ganha a chave ``_filhos`` com a sublista.

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            ValueError: Se ``page_size`` for menor que 1.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(block_id, "block_id")
        if page_size < 1:
            raise ValueError("page_size deve ser maior que zero.")

        resultados: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, str] = {"page_size": str(page_size)}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request_json(
                method="GET",
                path=f"/blocks/{limpo}/children?{urlencode(params)}",
                idempotente=True,
            )
            resultados.extend(data.get("results", []))

            if not buscar_todos or not data.get("has_more"):
                break

            cursor = data.get("next_cursor")
            if not cursor:
                break

        if recursivo:
            for bloco in resultados:
                # ``child_database`` "tem filhos" (as linhas), mas elas não são
                # blocos — são lidas por consultar_data_source. Não descemos nele.
                if bloco.get("has_children") and bloco.get("type") != "child_database":
                    bloco["_filhos"] = self.ler_blocos(
                        bloco["id"],
                        page_size=page_size,
                        buscar_todos=buscar_todos,
                        recursivo=True,
                    )

        return resultados

    def anexar_blocos(
        self,
        block_id: str,
        blocos: list[dict[str, object]],
        *,
        apos_bloco_id: str | None = None,
        no_inicio: bool = False,
    ) -> dict[str, Any]:
        """Anexa blocos filhos a uma página ou bloco.

        Sem posição, os blocos entram no **fim** da lista de filhos (o padrão
        ``{"type": "end"}`` da API). O parâmetro ``position`` do endpoint
        (https://developers.notion.com/reference/patch-block-children) aceita
        ``start``, ``end`` e ``after_block``; o antigo ``after`` está
        *deprecated* e foi removido na versão ``2026-03-11`` — por isso nunca é
        usado aqui. Pela política de versionamento do Notion
        (https://developers.notion.com/reference/versioning), parâmetros
        opcionais novos valem para todas as versões, inclusive a ``2022-06-28``
        fixada neste cliente; isso foi conferido no workspace real em
        2026-09-25 (``start`` e ``after_block`` respeitados; ``type`` inválido
        recusado com a lista ``after_block``/``start``/``end``).

        **Resposta com posição:** a documentação diz que a resposta traz "os
        filhos de primeiro nível recém-criados", mas medido em 2026-09-25 (nas
        versões 2022-06-28 e 2025-09-03), quando há ``position`` a lista
        ``results`` traz os blocos novos **seguidos de todos os irmãos
        posteriores**. Quem precisa só dos criados deve usar
        ``results[:len(blocos)]``.

        Args:
            block_id: ID da página ou do bloco pai.
            blocos: Lista de blocos no formato da API do Notion (no máximo 100,
                com até dois níveis de ``children`` aninhados por requisição).
            apos_bloco_id: Quando informado, insere os novos blocos logo após
                este bloco irmão (``position: after_block``).
            no_inicio: Quando verdadeiro, insere os novos blocos no **início**
                da lista de filhos (``position: start``). Exclusivo com
                ``apos_bloco_id``.

        Returns:
            A resposta JSON da API (ver a nota sobre ``results`` com posição).

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            ValueError: Se ``blocos`` estiver vazio, ou se ``no_inicio`` e
                ``apos_bloco_id`` vierem juntos.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(block_id, "block_id")
        if not blocos:
            raise ValueError("Informe ao menos um bloco para anexar.")
        if no_inicio and apos_bloco_id:
            raise ValueError("Use no_inicio ou apos_bloco_id, não os dois ao mesmo tempo.")

        payload: BlocksAppendPayload = {"children": blocos}
        if no_inicio:
            payload["position"] = {"type": "start"}
        elif apos_bloco_id:
            payload["position"] = {
                "type": "after_block",
                "after_block": {"id": _validar_identificador(apos_bloco_id, "apos_bloco_id")},
            }
        # Anexar não é idempotente: repetir duplicaria o conteúdo.
        return self._request_json(
            method="PATCH",
            path=f"/blocks/{limpo}/children",
            payload=payload,
            idempotente=False,
        )

    def atualizar_bloco(
        self,
        block_id: str,
        conteudo: dict[str, object],
    ) -> dict[str, Any]:
        """Atualiza o conteúdo de um bloco existente.

        Args:
            block_id: ID do bloco.
            conteudo: Payload do tipo do bloco (ex.: ``{"paragraph": {...}}``).

        Returns:
            A resposta JSON do bloco atualizado.

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            ValueError: Se ``conteudo`` estiver vazio.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(block_id, "block_id")
        if not conteudo:
            raise ValueError("Informe o conteúdo do bloco a atualizar.")

        return self._request_json(
            method="PATCH",
            path=f"/blocks/{limpo}",
            payload=dict(conteudo),
            idempotente=True,
        )

    def obter_bloco(self, block_id: str) -> dict[str, Any]:
        """Lê **um** bloco pelo ID (``GET /v1/blocks/{block_id}``).

        Devolve o objeto do bloco com ``type``, o corpo do tipo, ``has_children``,
        ``in_trash``, ``parent`` e os carimbos de criação/edição — mas **não**
        os filhos: quando ``has_children`` é verdadeiro, eles se leem com
        :meth:`ler_blocos` (https://developers.notion.com/reference/retrieve-a-block).

        Args:
            block_id: ID do bloco.

        Returns:
            O objeto JSON do bloco.

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(block_id, "block_id")
        return self._request_json(
            method="GET",
            path=f"/blocks/{limpo}",
            idempotente=True,
        )

    def restaurar_bloco(self, block_id: str) -> dict[str, Any]:
        """Tira um bloco da lixeira (``PATCH /v1/blocks/{id}`` com ``in_trash: false``).

        É o caminho documentado para desfazer :meth:`excluir_bloco`
        (https://developers.notion.com/reference/delete-a-block: "To restore
        the block with the API, use the Update a block"). ``in_trash`` é o campo
        que a referência de Update a block lista; medido em 2026-09-26 que a
        versão 2022-06-28 fixada aqui também o aceita. O bloco volta com o
        mesmo ID e os filhos, mas **não** na posição original: no mesmo teste
        ele reapareceu no **fim** da lista de filhos do pai.

        Args:
            block_id: ID do bloco arquivado.

        Returns:
            A resposta JSON do bloco restaurado.

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx.
        """

        limpo = _validar_identificador(block_id, "block_id")
        payload: BlockRestorePayload = {"in_trash": False}
        return self._request_json(
            method="PATCH",
            path=f"/blocks/{limpo}",
            payload=dict(payload),
            idempotente=True,
        )

    def excluir_bloco(self, block_id: str) -> dict[str, Any]:
        """Exclui (arquiva) um bloco do Notion.

        O Notion trata ``DELETE`` de bloco como arquivamento reversível: o bloco
        sai da página e ganha ``in_trash: true``; volta com
        :meth:`restaurar_bloco` (é preciso guardar o ID). É a operação
        destrutiva de conteúdo — quem expõe (CLI/MCP) deve pedir confirmação.

        **Idempotente de verdade:** o ``DELETE`` é retentado em falha de rede ou
        5xx, e medido no workspace real o segundo ``DELETE`` de um bloco já
        arquivado responde HTTP 400 ("Can't edit block that is archived"). Uma
        exclusão que deu certo no servidor mas perdeu a resposta viraria erro e
        abortaria no meio quem apaga em laço. Por isso, diante de um 400, o
        bloco é relido: se já está na lixeira, o estado pedido foi alcançado e
        o objeto lido é devolvido como sucesso. Consequência deliberada: apagar
        um bloco que **já estava** na lixeira antes da chamada também é sucesso.

        Args:
            block_id: ID do bloco a excluir.

        Returns:
            A resposta JSON do bloco arquivado (ou, no caso acima, o bloco
            relido, já com ``in_trash: true``).

        Raises:
            NotionConfigurationError: Se ``block_id`` for inválido.
            NotionHTTPError: Se a API responder com 4xx/5xx e o bloco não
                estiver na lixeira.
        """

        limpo = _validar_identificador(block_id, "block_id")
        try:
            return self._request_json(
                method="DELETE",
                path=f"/blocks/{limpo}",
                idempotente=True,
            )
        except NotionHTTPError as erro:
            if erro.status_code != 400:
                raise
            bloco = self._bloco_se_ja_arquivado(limpo)
            if bloco is None:
                raise
            logger.warning(
                "DELETE respondeu 400, mas o bloco já está na lixeira; tratado como sucesso",
                extra={"block_id": limpo},
            )
            return bloco

    def _bloco_se_ja_arquivado(self, block_id: str) -> dict[str, Any] | None:
        """Relê o bloco e o devolve só se ele já estiver arquivado/na lixeira."""

        try:
            bloco = self.obter_bloco(block_id)
        except NotionAPIError:
            return None
        if bloco.get("in_trash") or bloco.get("archived"):
            return bloco
        return None
