"""Camada ``services`` — casos de uso (regra de negócio).

Orquestra a tasklist, a ingestão e as sincronizações, **finos sobre o
``notion_starter``** via ``integrations``. Não conhece HTTP (isso é da ``api``) nem
o formato cru do Notion (isso é do ``notion_starter``).

O Agente Backend preenche ``services/tarefas.py`` (listar/criar/mover/concluir) e o
Agente Integrações adiciona ``ingestao.py`` e ``sincronizar_github.py``.
"""
