"""Casos de uso para investigar e replicar a *forma* de páginas de projeto.

O workspace "Central pessoal" (ver ``DESIGN-WORKSPACE-NOTION.md`` no hub
Automações do Notion) segue um padrão fixo por projeto: README + tópico
"Acompanhamento" (4 subpáginas) + tópico "Planejamento e documentação" (2
databases). Investigar esse padrão manualmente — abrindo blocos e subpáginas
uma a uma — é lento e não deixa rastro reutilizável. Este módulo cobre dois
casos de uso complementares:

- :func:`inspecionar_estrutura` — **lê** recursivamente a árvore de uma
  página de referência (subpáginas e databases filhos, até uma profundidade
  configurável), sem tocar em nada.
- :func:`clonar_estrutura_projeto` — **copia a forma** de uma página de
  referência para uma página destino: recria os mesmos títulos de subpágina
  (vazias) e o mesmo schema dos databases filhos (sem linhas), sem herdar o
  conteúdo específico do projeto de origem.
- :func:`montar_estrutura_projeto` — aplica diretamente o padrão documentado
  (Acompanhamento + Planejamento e documentação) numa página, sem precisar de
  uma referência existente no workspace.

Como as demais camadas de serviço, não conhece HTTP e aceita um
:class:`NotionClient` injetado (testável sem token nem rede).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notion_starter import NotionClient
from notion_starter.services.clonagem import clonar_database
from notion_starter.services.conteudo import criar_subpagina

#: Profundidade padrão de descida em subpáginas ao inspecionar uma estrutura.
_PROFUNDIDADE_PADRAO = 3

#: Títulos das subpáginas do tópico "## Acompanhamento", nesta ordem.
SUBPAGINAS_ACOMPANHAMENTO: tuple[str, ...] = (
    "Estado atual",
    "Trabalho em andamento",
    "Problemas encontrados",
    "Decisões e registros",
)

#: Schema de cada database do tópico "## Planejamento e documentação", na
#: ordem em que são criados. Nomes e tipos de coluna vêm do padrão observado
#: no workspace "Central pessoal" (ver DESIGN-WORKSPACE-NOTION.md).
DATABASES_PLANEJAMENTO: dict[str, dict[str, dict[str, object]]] = {
    "Próximos passos": {
        "Tarefa": {"title": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "A fazer", "color": "default"},
                    {"name": "Em andamento", "color": "yellow"},
                    {"name": "Feito", "color": "green"},
                ]
            }
        },
        "Prioridade": {
            "select": {
                "options": [
                    {"name": "Alta", "color": "red"},
                    {"name": "Média", "color": "yellow"},
                    {"name": "Baixa", "color": "gray"},
                ]
            }
        },
        "Concluída": {"checkbox": {}},
        "Observações": {"rich_text": {}},
    },
    "Documentações": {
        "Documento": {"title": {}},
        "Tipo": {
            "select": {
                "options": [
                    {"name": "Referência", "color": "blue"},
                    {"name": "Checklist", "color": "orange"},
                    {"name": "Relatório", "color": "purple"},
                ]
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Atualizado", "color": "green"},
                    {"name": "Desatualizado", "color": "yellow"},
                ]
            }
        },
        "Criado em": {"date": {}},
        "Atualizado em": {"date": {}},
        "URL": {"url": {}},
        "Observações": {"rich_text": {}},
    },
}


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do servidor (import tardio)."""

    from integrations.notion import criar_cliente

    return criar_cliente()


@dataclass
class NoEstrutura:
    """Um nó da árvore de blocos de uma página, para inspeção read-only."""

    id: str
    tipo: str
    titulo: str = ""
    filhos: list[NoEstrutura] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "titulo": self.titulo,
            "filhos": [filho.para_dict() for filho in self.filhos],
        }


def _titulo_bloco(bloco: dict[str, Any]) -> str:
    tipo = bloco.get("type", "")
    if tipo == "child_page":
        return str(bloco.get("child_page", {}).get("title") or "")
    if tipo == "child_database":
        return str(bloco.get("child_database", {}).get("title") or "")
    conteudo = bloco.get(tipo, {}) if isinstance(bloco.get(tipo), dict) else {}
    rich = conteudo.get("rich_text") if isinstance(conteudo, dict) else None
    if isinstance(rich, list):
        return "".join(p.get("plain_text", "") for p in rich)
    return ""


def inspecionar_estrutura(
    pagina_id: str,
    *,
    profundidade: int = _PROFUNDIDADE_PADRAO,
    cliente: NotionClient | None = None,
) -> NoEstrutura:
    """Lê recursivamente a árvore de blocos/subpáginas/databases de uma página.

    Desce em ``child_page`` (subpáginas) até ``profundidade`` níveis; para
    ``child_database`` mostra o nó (título) mas não lista linhas — o objetivo é
    entender a **forma** do projeto (que subpáginas e databases existem, em que
    ordem), não os dados. Útil para investigar o padrão de uma página de
    referência antes de replicá-lo (ver :func:`clonar_estrutura_projeto`).

    Args:
        pagina_id: ID da página raiz a inspecionar.
        profundidade: Quantos níveis de subpágina descer (1 = só os blocos
            diretos da página, sem entrar nas subpáginas).
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        A árvore como :class:`NoEstrutura` (use ``.para_dict()`` para JSON).

    Raises:
        ValueError: Se ``pagina_id`` for vazio ou ``profundidade`` menor que 1.
    """

    pagina_id = (pagina_id or "").strip()
    if not pagina_id:
        raise ValueError("pagina_id é obrigatório.")
    if profundidade < 1:
        raise ValueError("profundidade deve ser maior ou igual a 1.")

    cli = cliente or _cliente_padrao()
    raiz = NoEstrutura(id=pagina_id, tipo="page")
    raiz.filhos = _inspecionar_filhos(cli, pagina_id, profundidade)
    return raiz


def _inspecionar_filhos(
    cliente: NotionClient, block_id: str, profundidade_restante: int
) -> list[NoEstrutura]:
    nos: list[NoEstrutura] = []
    for bloco in cliente.ler_blocos(block_id, buscar_todos=True):
        tipo = bloco.get("type", "")
        no = NoEstrutura(
            id=str(bloco.get("id") or ""), tipo=tipo, titulo=_titulo_bloco(bloco)
        )
        if tipo == "child_page" and profundidade_restante > 1 and no.id:
            no.filhos = _inspecionar_filhos(cliente, no.id, profundidade_restante - 1)
        nos.append(no)
    return nos


@dataclass
class ResumoClone:
    """Resultado de :func:`clonar_estrutura_projeto`."""

    subpaginas_criadas: list[str] = field(default_factory=list)
    databases_clonados: list[str] = field(default_factory=list)
    ignorados: list[str] = field(default_factory=list)


def clonar_estrutura_projeto(
    pagina_referencia_id: str,
    pagina_destino_id: str,
    *,
    profundidade: int = 1,
    cliente: NotionClient | None = None,
) -> ResumoClone:
    """Copia a *forma* de uma página de projeto para outra página.

    Percorre os filhos diretos (``profundidade=1``) da página de referência:
    para cada ``child_page`` cria uma subpágina de mesmo título (vazia) na
    página destino; para cada ``child_database`` clona o schema (sem linhas,
    via :func:`~notion_starter.services.clonagem.clonar_database`) para a
    página destino. Headings, dividers e demais blocos são copiados como texto
    simples, preservando a moldura visual (tópicos) sem o conteúdo específico
    do projeto de origem.

    Args:
        pagina_referencia_id: ID da página de projeto usada como modelo.
        pagina_destino_id: ID da página que recebe a estrutura clonada.
        profundidade: Repassado a subpáginas aninhadas, se houver (padrão: só
            o primeiro nível — o suficiente para o padrão de Acompanhamento).
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        :class:`ResumoClone` com o que foi criado e o que foi ignorado (blocos
        sem equivalente direto, como imagens ou embeds).
    """

    pagina_referencia_id = (pagina_referencia_id or "").strip()
    pagina_destino_id = (pagina_destino_id or "").strip()
    if not pagina_referencia_id:
        raise ValueError("pagina_referencia_id é obrigatório.")
    if not pagina_destino_id:
        raise ValueError("pagina_destino_id é obrigatório.")

    cli = cliente or _cliente_padrao()
    resumo = ResumoClone()

    for bloco in cli.ler_blocos(pagina_referencia_id, buscar_todos=True):
        tipo = bloco.get("type", "")
        titulo = _titulo_bloco(bloco)

        if tipo == "child_page":
            criar_subpagina(pagina_destino_id, titulo or "(sem título)", cliente=cli)
            resumo.subpaginas_criadas.append(titulo)
        elif tipo == "child_database":
            database_id = str(bloco.get("id") or "")
            if not database_id:
                resumo.ignorados.append(f"database sem id ({titulo})")
                continue
            clonar_database(
                database_id,
                titulo=titulo or None,
                pagina_destino=pagina_destino_id,
                com_linhas=False,
                cliente=cli,
            )
            resumo.databases_clonados.append(titulo)
        elif tipo in {"heading_1", "heading_2", "heading_3"}:
            cli.anexar_blocos(pagina_destino_id, [bloco_texto_simples(tipo, titulo)])
        elif tipo == "divider":
            cli.anexar_blocos(pagina_destino_id, [{"type": "divider", "divider": {}}])
        else:
            resumo.ignorados.append(f"{tipo} ({titulo})" if titulo else tipo)

    return resumo


def bloco_texto_simples(tipo: str, texto: str) -> dict[str, Any]:
    """Monta um bloco de heading simples, sem depender do conversor de Markdown."""

    return {
        "type": tipo,
        tipo: {"rich_text": [{"type": "text", "text": {"content": texto}}]},
    }


@dataclass
class ResumoEstruturaProjeto:
    """Resultado de :func:`montar_estrutura_projeto`."""

    subpaginas_criadas: list[str] = field(default_factory=list)
    databases_criados: list[str] = field(default_factory=list)


def montar_estrutura_projeto(
    pagina_id: str,
    *,
    cliente: NotionClient | None = None,
) -> ResumoEstruturaProjeto:
    """Aplica o padrão fixo de projeto (Acompanhamento + Planejamento) numa página.

    Escreve ``## Acompanhamento`` + divisória, cria as 4 subpáginas de
    :data:`SUBPAGINAS_ACOMPANHAMENTO` (vazias), escreve
    ``## Planejamento e documentação`` + divisória e cria os 2 databases de
    :data:`DATABASES_PLANEJAMENTO`, cada um com o schema real observado no
    workspace de referência (Tarefa/Status/Prioridade/Concluída/Observações em
    "Próximos passos"; Documento/Tipo/Status/datas/URL/Observações em
    "Documentações"). É a
    forma "do zero" de aplicar o padrão; para copiar de um projeto existente
    (com eventuais variações), use :func:`clonar_estrutura_projeto`.

    Args:
        pagina_id: ID da página de projeto que recebe a estrutura.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        :class:`ResumoEstruturaProjeto` com os títulos criados.
    """

    pagina_id = (pagina_id or "").strip()
    if not pagina_id:
        raise ValueError("pagina_id é obrigatório.")

    cli = cliente or _cliente_padrao()
    resumo = ResumoEstruturaProjeto()

    cli.anexar_blocos(
        pagina_id,
        [
            bloco_texto_simples("heading_2", "Acompanhamento"),
            {"type": "divider", "divider": {}},
        ],
    )
    for titulo in SUBPAGINAS_ACOMPANHAMENTO:
        criar_subpagina(pagina_id, titulo, cliente=cli)
        resumo.subpaginas_criadas.append(titulo)

    cli.anexar_blocos(
        pagina_id,
        [
            bloco_texto_simples("heading_2", "Planejamento e documentação"),
            {"type": "divider", "divider": {}},
        ],
    )
    for titulo, propriedades in DATABASES_PLANEJAMENTO.items():
        cli.criar_database(pagina_id, titulo, propriedades=propriedades)
        resumo.databases_criados.append(titulo)

    return resumo
