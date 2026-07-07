"""Caso de uso de IA — linguagem natural → operação de tasklist (modo copiloto).

O fluxo é **copiloto que sugere e a pessoa confirma**:

1. O usuário digita uma frase em linguagem natural (ex.: "cria uma tarefa pra
   revisar o artigo amanhã").
2. ``interpretar_comando`` envia a frase ao provedor de IA, que devolve uma
   ``AcaoSugerida`` estruturada (operação + parâmetros + descrição legível).
3. A camada que chamou (API, MCP, CLI) **apresenta a sugestão ao usuário**.
4. Se o usuário confirmar, ``executar_acao`` delega para ``services.tarefas``.

Guarda-corpos:
- Nenhuma escrita no Notion sem confirmação explícita.
- A IA **não** acessa o Notion diretamente — apenas interpreta texto.
- O provedor é injetável (``ProvedorIA``); testes usam um mock, sem rede.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from notion_starter.openrouter import ProvedorIA

from notion_starter import Tarefa, TaskList

# ---------------------------------------------------------------------------
# Objeto de domínio: ação sugerida
# ---------------------------------------------------------------------------

# Operações válidas que o provedor pode sugerir.
OPERACOES_VALIDAS = frozenset(
    {
        "listar_tarefas",
        "criar_tarefa",
        "mover_status",
        "concluir_tarefa",
    }
)


@dataclass
class AcaoSugerida:
    """Sugestão estruturada que a IA devolve ao usuário para confirmação.

    Attributes:
        operacao: Nome da operação (``listar_tarefas``, ``criar_tarefa``,
            ``mover_status``, ``concluir_tarefa``).
        parametros: Argumentos para a operação (ex.: ``{"nome": "...", "prazo": "..."}``).
        descricao: Explicação legível do que será feito, para o usuário ler antes de
            confirmar.
    """

    operacao: str
    parametros: dict[str, Any] = field(default_factory=dict)
    descricao: str = ""


# ---------------------------------------------------------------------------
# Prompt de sistema (instrução fixa para o provedor)
# ---------------------------------------------------------------------------

_PROMPT_SISTEMA = """\
Você é um assistente que converte frases em linguagem natural em operações \
estruturadas sobre uma lista de tarefas do Notion.

Operações disponíveis (use exatamente estes nomes):
- listar_tarefas: lista tarefas. Parâmetros opcionais: {"status": "nome do status"}.
- criar_tarefa: cria uma tarefa. Parâmetros: {"nome": "título" (obrigatório), \
"status": "nome" (opcional), "prazo": "AAAA-MM-DD" (opcional)}.
- mover_status: muda o status de uma tarefa. Parâmetros: {"task_id": "id", \
"status": "novo status"}.
- concluir_tarefa: marca uma tarefa como concluída. Parâmetros: {"task_id": "id", \
"status_concluido": "nome do status de conclusão"}.

Responda APENAS com JSON válido, sem texto extra, no formato:
{"operacao": "nome_da_operacao", "parametros": {...}, "descricao": "frase legível \
explicando o que será feito"}

Se a frase não corresponder a nenhuma operação, responda:
{"operacao": "desconhecida", "parametros": {}, "descricao": "explicação do motivo"}
"""


# ---------------------------------------------------------------------------
# Interpretar comando (NL → AcaoSugerida)
# ---------------------------------------------------------------------------


class InterpretacaoErro(ValueError):
    """A resposta do provedor não pôde ser interpretada como ação válida."""


def interpretar_comando(
    texto: str,
    *,
    provedor: ProvedorIA,
    modelo: str | None = None,
) -> AcaoSugerida:
    """Converte uma frase em linguagem natural em uma ``AcaoSugerida``.

    Args:
        texto: Frase do usuário (ex.: "cria uma tarefa pra estudar IA amanhã").
        provedor: Instância de ``ProvedorIA`` (OpenRouter, mock, etc.).
        modelo: ID do modelo a usar (opcional; o provedor tem um padrão).

    Returns:
        Uma ``AcaoSugerida`` com operação, parâmetros e descrição legível.

    Raises:
        InterpretacaoErro: Se a resposta do provedor não for JSON válido ou não
            contiver os campos esperados.
    """

    prompt = f"{_PROMPT_SISTEMA}\n\nFrase do usuário: {texto}"
    resposta_bruta = provedor.completar(prompt, modelo=modelo)
    return _parse_resposta(resposta_bruta)


def _parse_resposta(resposta: str) -> AcaoSugerida:
    """Converte a resposta JSON do provedor em ``AcaoSugerida``."""

    # Limpa possíveis marcadores de bloco de código.
    limpa = resposta.strip()
    if limpa.startswith("```"):
        linhas = limpa.splitlines()
        # Remove primeira e última linha (```json e ```)
        linhas = [ln for ln in linhas if not ln.strip().startswith("```")]
        limpa = "\n".join(linhas).strip()

    try:
        dados = json.loads(limpa)
    except json.JSONDecodeError as exc:
        raise InterpretacaoErro(f"a resposta do provedor não é JSON válido: {resposta!r}") from exc

    operacao = dados.get("operacao", "")
    if not isinstance(operacao, str) or not operacao:
        raise InterpretacaoErro("campo 'operacao' ausente ou inválido na resposta.")

    parametros = dados.get("parametros", {})
    if not isinstance(parametros, dict):
        parametros = {}

    descricao = dados.get("descricao", "")
    if not isinstance(descricao, str):
        descricao = ""

    return AcaoSugerida(operacao=operacao, parametros=parametros, descricao=descricao)


# ---------------------------------------------------------------------------
# Executar ação confirmada (AcaoSugerida → Tarefa)
# ---------------------------------------------------------------------------


def executar_acao(
    acao: AcaoSugerida,
    *,
    tasklist: TaskList | None = None,
) -> Tarefa | list[Tarefa]:
    """Executa uma ação **já confirmada pelo usuário**.

    Delega para ``services.tarefas``, que é fino sobre a ``TaskList``.
    A ``tasklist`` é injetável para testes.

    Raises:
        ValueError: Se a operação não for reconhecida ou faltar parâmetro obrigatório.
    """

    from notion_starter.services import tarefas as svc

    op = acao.operacao
    p = acao.parametros

    if op == "listar_tarefas":
        return svc.listar_tarefas(status=p.get("status"), tasklist=tasklist)

    if op == "criar_tarefa":
        nome = p.get("nome", "").strip()
        if not nome:
            raise ValueError("a operação 'criar_tarefa' exige o parâmetro 'nome'.")
        return svc.criar_tarefa(
            nome,
            status=p.get("status"),
            prazo=p.get("prazo"),
            tasklist=tasklist,
        )

    if op == "mover_status":
        task_id = p.get("task_id", "").strip()
        status = p.get("status", "").strip()
        if not task_id or not status:
            raise ValueError("a operação 'mover_status' exige 'task_id' e 'status'.")
        return svc.mover_status(task_id, status, tasklist=tasklist)

    if op == "concluir_tarefa":
        task_id = p.get("task_id", "").strip()
        status_c = p.get("status_concluido", "").strip()
        if not task_id or not status_c:
            raise ValueError("a operação 'concluir_tarefa' exige 'task_id' e 'status_concluido'.")
        return svc.concluir_tarefa(task_id, status_c, tasklist=tasklist)

    raise ValueError(f"operação desconhecida: {op!r}")
