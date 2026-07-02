"""Constantes compartilhadas do ``notion_starter``."""

from __future__ import annotations

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

#: Versão da API exigida pelos endpoints de *data sources* (databases com o
#: modelo novo, multi-fonte, introduzido pelo Notion em 2025). É enviada apenas
#: nas chamadas de data source, sem alterar a versão padrão das demais rotas.
NOTION_DATA_SOURCE_VERSION = "2025-09-03"

NOTION_TIMEOUT_SECONDS = 15

#: Variável de ambiente lida por padrão quando nenhum token é passado explicitamente.
NOTION_TOKEN_ENV = "NOTION_TOKEN"

#: Prefixo com que todo token de integração atual do Notion começa.
NOTION_TOKEN_PREFIX = "ntn_"

#: Número padrão de retentativas em erros retentáveis (429, 5xx, rede).
NOTION_MAX_RETRIES = 3

#: Base do backoff exponencial entre retentativas, em segundos.
NOTION_BACKOFF_BASE = 1.0

#: Rate limit e sobrecarga: o Notion confirma que a chamada deve ser repetida.
NOTION_RATE_LIMIT_STATUS_CODES = frozenset({429, 529})

#: Status que a documentação do Notion orienta tentar novamente.
NOTION_RETRYABLE_STATUS_CODES = frozenset({409, 429, 500, 502, 503, 504, 529})

#: TTL padrão do cache de schema (get_database), em segundos.
NOTION_SCHEMA_CACHE_TTL = 300
