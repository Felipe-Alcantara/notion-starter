"""Trabalha com um database de tarefas do Notion pela camada de alto nível.

Mostra o fluxo da :class:`TaskList`, que troca o JSON cru da API por um objeto
``Tarefa`` simples — a forma que um front ou um sistema de IA consome:

1. Cria um ``NotionClient`` (token vindo da env var ``NOTION_TOKEN``).
2. Abre uma ``TaskList`` sobre o database de tarefas.
3. Lista as tarefas, cria uma nova e atualiza o status dela.

Os nomes das colunas variam entre workspaces; ajuste ``CamposTarefa`` ao seu
database (ou use o padrão se ele já segue ``Nome`` / ``Status`` / ``Próximo prazo``).
Os valores de status abaixo (``"00. Inbox"``, ``"06. Feito"``) são exemplos —
troque pelos status que existem no seu database.

Execução:
    export NOTION_TOKEN=ntn_xxx
    python examples/gerenciar_tarefas.py <DATABASE_ID>
"""

from __future__ import annotations

import sys

from notion_starter import CamposTarefa, NotionClient, TaskList, configure_logging

# Ajuste para os nomes reais das colunas do seu database de tarefas. O padrão
# de CamposTarefa já cobre um database "Nome / Status / Próximo prazo".
CAMPOS = CamposTarefa(nome="Nome", status="Status", prazo="Próximo prazo")

# Status de exemplo — substitua pelos que existem no seu database.
STATUS_INICIAL = "00. Inbox"
STATUS_CONCLUIDO = "06. Feito"


def main(database_id: str) -> None:
    configure_logging()  # logging opcional em console para um script
    tarefas = TaskList(NotionClient(), database_id, campos=CAMPOS)

    print("Tarefas atuais:")
    existentes = tarefas.listar()
    if not existentes:
        print("  (nenhuma tarefa encontrada)")
    for tarefa in existentes:
        prazo = f" — prazo {tarefa.prazo}" if tarefa.prazo else ""
        print(f"  • {tarefa.nome} [{tarefa.status or 'sem status'}]{prazo}")

    print(f"\nCriando uma tarefa de exemplo em '{STATUS_INICIAL}'...")
    nova = tarefas.criar(
        "Tarefa de exemplo (criada pelo gerenciar_tarefas.py)",
        status=STATUS_INICIAL,
    )
    print(f"  criada: {nova.nome} [{nova.status}] id={nova.id}")

    print(f"\nMarcando a tarefa como '{STATUS_CONCLUIDO}'...")
    concluida = tarefas.concluir(nova.id, STATUS_CONCLUIDO)
    print(f"  agora: {concluida.nome} [{concluida.status}]")

    print("\nConcluído.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python examples/gerenciar_tarefas.py <DATABASE_ID>", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1])
