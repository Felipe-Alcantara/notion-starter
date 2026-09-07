"""Camada ``services`` — casos de uso (regra de negócio).

Orquestra a tasklist, a ingestão e as sincronizações, **finos sobre o
``notion_starter``** via ``integrations``. Não conhece HTTP (isso é da ``api``) nem
o formato cru do Notion (isso é do ``notion_starter``).

Os helpers públicos leves também podem ser importados diretamente daqui; a
implementação continua organizada no módulo especializado.

O Agente Backend preenche ``services/tarefas.py`` (listar/criar/mover/concluir) e o
Agente Integrações adiciona ``ingestao.py`` e ``sincronizar_github.py``.
"""

from .classificacao import (
    AplicadorClassificacao,
    ClassificacaoLinha,
    LinhaClassificada,
    MontadorPropriedade,
    RegraClassificacao,
    ResultadoClassificacao,
    ValorClassificacao,
    aplicar_classificacoes,
    classificar_em_lote,
)

__all__ = [
    "AplicadorClassificacao",
    "ClassificacaoLinha",
    "LinhaClassificada",
    "MontadorPropriedade",
    "RegraClassificacao",
    "ResultadoClassificacao",
    "ValorClassificacao",
    "aplicar_classificacoes",
    "classificar_em_lote",
]
