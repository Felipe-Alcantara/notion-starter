"""Compara um database Notion remoto com um schema esperado."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import NotionSchemaError

#: Um schema é um mapeamento de nome de coluna para o tipo de propriedade
#: Notion esperado, ex.: ``{"Nome": "title", "Email": "email", "Cadastro": "date"}``.
Schema = dict[str, str]


@dataclass
class SchemaComparison:
    """Resultado da comparação de um database com um schema esperado.

    Attributes:
        ok: Colunas presentes com o tipo esperado, como ``(nome, tipo)``.
        faltando: Colunas esperadas ausentes no database, como ``(nome, tipo)``.
        tipo_errado: Colunas com tipo inesperado, como
            ``(nome, esperado, encontrado)``.
    """

    ok: list[tuple[str, str]] = field(default_factory=list)
    faltando: list[tuple[str, str]] = field(default_factory=list)
    tipo_errado: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def compativel(self) -> bool:
        """Se o database satisfaz o schema esperado."""

        return not self.faltando and not self.tipo_errado

    def levantar_se_incompativel(self) -> None:
        """Levanta :class:`NotionSchemaError` se o database for incompatível.

        Raises:
            NotionSchemaError: Se alguma coluna estiver faltando ou com tipo errado.
        """

        if self.compativel:
            return
        raise NotionSchemaError(
            faltando=[nome for nome, _ in self.faltando],
            tipo_errado=self.tipo_errado,
        )


def extrair_tipos_propriedades(database: dict[str, Any]) -> dict[str, str]:
    """Mapeia nome de coluna para tipo de propriedade a partir de ``get_database``.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.

    Returns:
        Um mapeamento de nome de coluna para o ``type`` da propriedade Notion.
    """

    propriedades = database.get("properties", {})
    return {nome: info.get("type", "?") for nome, info in propriedades.items()}


def comparar_schema(database: dict[str, Any], esperado: Schema) -> SchemaComparison:
    """Compara a resposta de um database com um schema esperado.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.
        esperado: Mapeamento de nome de coluna para tipo de propriedade esperado.

    Returns:
        Um :class:`SchemaComparison` descrevendo as diferenças.
    """

    atual = extrair_tipos_propriedades(database)
    comparacao = SchemaComparison()

    for coluna, tipo_esperado in esperado.items():
        if coluna not in atual:
            comparacao.faltando.append((coluna, tipo_esperado))
            continue
        tipo_atual = atual[coluna]
        if tipo_atual == tipo_esperado:
            comparacao.ok.append((coluna, tipo_atual))
        else:
            comparacao.tipo_errado.append((coluna, tipo_esperado, tipo_atual))

    return comparacao


#: Tipos que o Notion calcula sozinho: aparecem na leitura, mas um PATCH neles
#: é rejeitado. Saber disso **antes** de montar o payload evita a ida perdida à
#: API — é a mesma lista que ``services/propriedades`` usa para recusar edição.
TIPOS_SOMENTE_LEITURA = frozenset(
    {
        "formula",
        "rollup",
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "unique_id",
    }
)

#: Tipos cujos valores válidos são fechados pelo schema: escrever fora da lista
#: devolve "Invalid select option" da API, não um erro de validação amigável.
_TIPOS_COM_OPCOES = ("select", "multi_select", "status")


@dataclass(frozen=True)
class Relacao:
    """Como uma coluna de relação está configurada do lado do Notion.

    Attributes:
        database_id: Database apontado pela relação.
        bidirecional: ``True`` para ``dual_property`` — há coluna espelho
            declarada no alvo e o Notion sincroniza os dois lados. ``False``
            para ``single_property``, que **não garante** o espelho: pode ser
            preciso gravar as duas pontas. Ver :attr:`aviso`.
        coluna_espelho: Nome da coluna espelho no database alvo, quando a
            relação é bidirecional.
        auto_referente: A relação aponta para o próprio database (subtarefas,
            tarefas relacionadas, dependências).
    """

    database_id: str
    bidirecional: bool
    coluna_espelho: str | None = None
    auto_referente: bool = False

    @property
    def aviso(self) -> str | None:
        """Frase pronta sobre o que a configuração exige de quem escreve.

        ``single_property`` **não é promessa de nada** em nenhuma das direções,
        e este é o detalhe que custa caro descobrir tarde. Medido no workspace
        real em 2026-08-17, numa relação auto-referente que as versões de API
        ``2022-06-28`` e ``2025-09-03`` reportam como ``single_property``:
        gravar só a ponta A **fez** a ponta B enxergar A, sem segunda escrita.
        Já entre databases diferentes não existe coluna de volta para gravar.

        Ou seja: pelo tipo declarado não dá para saber se o espelho acontece. O
        único caminho seguro é **conferir a outra ponta depois de escrever** —
        que é o que :func:`notion_starter.services.relacoes.relacionar` faz, em
        vez de assumir.
        """

        if self.bidirecional:
            return None
        return (
            "Relação declarada como single_property: o espelho NÃO é garantido "
            "pelo tipo. Não assuma nem que grava os dois lados nem que grava só "
            "um — escreva com 'relacionar', que confere a outra ponta e só grava "
            "o que faltar."
        )


@dataclass(frozen=True)
class Coluna:
    """Uma coluna de database, com o que é preciso saber para escrever nela.

    Attributes:
        nome: Nome exato da coluna, como a API espera receber.
        tipo: ``type`` da propriedade Notion.
        editavel: Se aceita escrita (``False`` para os tipos calculados).
        e_titulo: Se é a coluna ``title`` — a única obrigatória ao criar linha.
        opcoes: Valores aceitos, para ``select``/``multi_select``/``status``.
        relacao: Configuração da relação, quando ``tipo == "relation"``.
    """

    nome: str
    tipo: str
    editavel: bool
    e_titulo: bool = False
    opcoes: tuple[str, ...] = ()
    relacao: Relacao | None = None


@dataclass(frozen=True)
class DescricaoDatabase:
    """Schema legível de um database: o que existe e como escrever em cada coluna.

    Attributes:
        database_id: ID do database descrito.
        titulo: Título em texto puro.
        colunas: Todas as colunas, ordenadas com o título primeiro e o resto em
            ordem alfabética — leitura estável entre execuções.
    """

    database_id: str
    titulo: str
    colunas: tuple[Coluna, ...]

    @property
    def coluna_titulo(self) -> Coluna | None:
        """A coluna ``title``, se houver."""

        return next((coluna for coluna in self.colunas if coluna.e_titulo), None)

    @property
    def editaveis(self) -> tuple[Coluna, ...]:
        """Só as colunas em que dá para escrever."""

        return tuple(coluna for coluna in self.colunas if coluna.editavel)

    @property
    def avisos(self) -> tuple[str, ...]:
        """Avisos acionáveis do schema, prontos para exibir a quem for escrever."""

        return tuple(
            f"{coluna.nome}: {coluna.relacao.aviso}"
            for coluna in self.colunas
            if coluna.relacao is not None and coluna.relacao.aviso
        )

    def para_dict(self) -> dict[str, Any]:
        """Forma serializável, para a saída ``--json`` das bordas."""

        return {
            "database_id": self.database_id,
            "titulo": self.titulo,
            "colunas": [
                {
                    "nome": coluna.nome,
                    "tipo": coluna.tipo,
                    "editavel": coluna.editavel,
                    "titulo": coluna.e_titulo,
                    **({"opcoes": list(coluna.opcoes)} if coluna.opcoes else {}),
                    **(
                        {
                            "relacao": {
                                "database_id": coluna.relacao.database_id,
                                "bidirecional": coluna.relacao.bidirecional,
                                "coluna_espelho": coluna.relacao.coluna_espelho,
                                "auto_referente": coluna.relacao.auto_referente,
                            }
                        }
                        if coluna.relacao
                        else {}
                    ),
                }
                for coluna in self.colunas
            ],
            "avisos": list(self.avisos),
        }


def _texto_do_titulo(database: dict[str, Any]) -> str:
    """Extrai o título do database do array de rich_text."""

    partes = database.get("title") or []
    texto = "".join(parte.get("plain_text", "") for parte in partes if isinstance(parte, dict))
    return texto.strip() or "(sem título)"


def _relacao_de(info: dict[str, Any], database_id: str) -> Relacao | None:
    """Lê a configuração de relação de uma propriedade, se for uma."""

    bruto = info.get("relation")
    if not isinstance(bruto, dict):
        return None
    alvo = str(bruto.get("database_id", ""))
    dupla = bruto.get("dual_property")
    return Relacao(
        database_id=alvo,
        bidirecional=bruto.get("type") == "dual_property",
        coluna_espelho=(
            dupla.get("synced_property_name") if isinstance(dupla, dict) else None
        ),
        auto_referente=_sem_hifens(alvo) == _sem_hifens(database_id),
    )


def _sem_hifens(identificador: str) -> str:
    """Compara IDs do Notion ignorando hífens — a API aceita as duas formas."""

    return identificador.replace("-", "").lower()


def descrever_database(database: dict[str, Any]) -> DescricaoDatabase:
    """Traduz o JSON de um database no schema legível de :class:`DescricaoDatabase`.

    Função pura: recebe o que :meth:`NotionClient.get_database` devolveu e não
    fala com a rede. O que ela resolve é a pergunta que antecede **toda** escrita
    num database desconhecido — quais colunas existem, quais aceitam escrita,
    que valores são válidos e quais relações precisam ser gravadas nos dois lados.

    Args:
        database: O JSON retornado por :meth:`NotionClient.get_database`.

    Returns:
        A :class:`DescricaoDatabase` correspondente.
    """

    database_id = str(database.get("id", ""))
    colunas: list[Coluna] = []

    for nome, info in (database.get("properties") or {}).items():
        if not isinstance(info, dict):
            continue
        tipo = info.get("type", "?")
        opcoes: tuple[str, ...] = ()
        if tipo in _TIPOS_COM_OPCOES:
            bruto = info.get(tipo)
            if isinstance(bruto, dict):
                opcoes = tuple(
                    str(opcao.get("name", ""))
                    for opcao in bruto.get("options", [])
                    if isinstance(opcao, dict)
                )
        colunas.append(
            Coluna(
                nome=nome,
                tipo=tipo,
                editavel=tipo not in TIPOS_SOMENTE_LEITURA,
                e_titulo=tipo == "title",
                opcoes=opcoes,
                relacao=_relacao_de(info, database_id) if tipo == "relation" else None,
            )
        )

    # Título primeiro (é a coluna obrigatória de qualquer linha nova), o resto em
    # ordem alfabética: a mesma entrada sai sempre na mesma ordem.
    colunas.sort(key=lambda coluna: (not coluna.e_titulo, coluna.nome.lower()))

    return DescricaoDatabase(
        database_id=database_id,
        titulo=_texto_do_titulo(database),
        colunas=tuple(colunas),
    )
