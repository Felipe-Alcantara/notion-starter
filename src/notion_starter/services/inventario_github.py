"""Caso de uso: inventário de repositórios GitHub em um database do Notion.

Diferente de :mod:`services.sincronizar_github` (que é orientado a *tarefas*),
este serviço materializa um **inventário** — um database com uma página por
repositório, com propriedades ricas (estrelas, linguagem, licença, datas...) e o
**README exportado numa subpágina filha** ``README`` de cada página.

Duas operações:

- :func:`exportar_repos` — popula o database (cria páginas, escreve README só nas
  novas). Bom para a carga inicial.
- :func:`atualizar_repos` — re-sincroniza tudo: adiciona repositórios novos,
  atualiza as propriedades dos existentes e **substitui a subpágina README quando
  o conteúdo mudou** (detecção barata por hash gravado na própria página).

Camadas: a coleta vem do :class:`GitHubClient` (HTTP/normalização), a escrita vai
pelo :class:`NotionClient`; a conversão Markdown → blocos fica em
:mod:`services.conteudo`. Aqui mora só a regra de negócio do inventário.

Pontos de extensão (Open/Closed):
- :class:`CamposGitHub` permite renomear as colunas sem tocar no mapeamento.
- :data:`construir_schema` define o schema do database de forma isolada.
- A lista de contas é um parâmetro, não um valor fixo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from notion_starter import NotionClient, properties
from notion_starter.github import GitHubClient, RepoInfo
from notion_starter.readers import ler_date, ler_rich_text

# Limite defensivo do tamanho do README importado (Markdown bruto).
MAX_README_CHARS = 100_000

# Título da subpágina que guarda o README dentro da página de cada repositório.
TITULO_README = "README"


@dataclass(frozen=True)
class CamposGitHub:
    """Nomes das propriedades do database de inventário GitHub.

    Configurável para que workspaces com colunas em outro idioma/nome reusem o
    serviço sem alterar o mapeamento.
    """

    nome: str = "Nome"
    dono: str = "Conta"
    descricao: str = "Descrição"
    url: str = "URL"
    homepage: str = "Homepage"
    linguagem: str = "Linguagem"
    topicos: str = "Tópicos"
    licenca: str = "Licença"
    estrelas: str = "Estrelas"
    forks: str = "Forks"
    issues: str = "Issues abertas"
    tamanho_kb: str = "Tamanho (KB)"
    privado: str = "Privado"
    fork: str = "Fork"
    arquivado: str = "Arquivado"
    criado_em: str = "Criado em"
    atualizado_em: str = "Atualizado em"
    enviado_em: str = "Último push"
    readme_hash: str = "README hash"


@dataclass
class ResumoInventario:
    """Resultado de uma exportação/atualização de inventário."""

    repos_encontrados: int = 0
    paginas_criadas: int = 0
    paginas_atualizadas: int = 0
    paginas_puladas: int = 0
    readmes_escritos: int = 0
    readmes_atualizados: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def total_erros(self) -> int:
        return len(self.erros)


def construir_schema(campos: CamposGitHub | None = None) -> dict[str, dict[str, object]]:
    """Monta o schema (definição de colunas) do database de inventário.

    Retorna o formato cru da API do Notion esperado por
    :meth:`NotionClient.criar_database`. A coluna ``nome`` é o ``title``.
    """

    c = campos or CamposGitHub()
    return {
        c.nome: {"title": {}},
        c.dono: {"select": {}},
        c.descricao: {"rich_text": {}},
        c.url: {"url": {}},
        c.homepage: {"url": {}},
        c.linguagem: {"select": {}},
        c.topicos: {"multi_select": {}},
        c.licenca: {"select": {}},
        c.estrelas: {"number": {}},
        c.forks: {"number": {}},
        c.issues: {"number": {}},
        c.tamanho_kb: {"number": {}},
        c.privado: {"checkbox": {}},
        c.fork: {"checkbox": {}},
        c.arquivado: {"checkbox": {}},
        c.criado_em: {"date": {}},
        c.atualizado_em: {"date": {}},
        c.enviado_em: {"date": {}},
        c.readme_hash: {"rich_text": {}},
    }


def _parse_data(valor: str | None) -> datetime | None:
    """Converte uma data ISO 8601 (com ``Z`` ou offset) em ``datetime`` aware.

    Tolera o ``Z`` do GitHub e o offset ``+00:00`` que o Notion devolve; datas
    sem fuso são assumidas em UTC. Retorna ``None`` quando não dá para parsear.
    """

    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _repo_mudou_desde_pagina(
    repo: RepoInfo,
    existente: dict[str, Any] | None,
    campos: CamposGitHub,
) -> bool:
    """Indica se o repositório mudou desde o último sync (``updated_at`` mais novo).

    Compara o ``updated_at`` do GitHub com a data gravada na coluna
    :attr:`CamposGitHub.atualizado_em` da página. Na dúvida (repo sem data, página
    sem data, ou formato ilegível) retorna ``True`` para não pular por engano —
    o modo incremental só deve poupar quando tem certeza de que nada mudou.
    """

    nova = _parse_data(repo.atualizado_em)
    if nova is None:
        return True
    props = existente.get("properties", {}) if existente else {}
    antiga = _parse_data(ler_date(props.get(campos.atualizado_em)))
    if antiga is None:
        return True
    return nova > antiga


def _hash_readme(readme: str | None) -> str:
    """Hash curto e estável do README, para detectar mudança sem reler blocos."""

    texto = (readme or "").strip()
    if not texto:
        return ""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _propriedades_pagina(
    repo: RepoInfo,
    campos: CamposGitHub,
    *,
    readme_hash: str | None = None,
) -> dict[str, Any]:
    """Mapeia um :class:`RepoInfo` para as propriedades da página.

    Quando ``readme_hash`` é informado, grava-o na coluna de hash para que a
    próxima atualização saiba se o README mudou sem precisar reler a subpágina.
    """

    props: dict[str, Any] = {
        campos.nome: properties.title(repo.nome_completo or repo.nome),
        campos.estrelas: properties.number(repo.estrelas),
        campos.forks: properties.number(repo.forks),
        campos.issues: properties.number(repo.issues_abertas),
        campos.tamanho_kb: properties.number(repo.tamanho_kb),
        campos.privado: properties.checkbox(repo.privado),
        campos.fork: properties.checkbox(repo.fork),
        campos.arquivado: properties.checkbox(repo.arquivado),
    }
    if repo.dono:
        props[campos.dono] = properties.select(repo.dono)
    if repo.descricao:
        props[campos.descricao] = properties.rich_text(repo.descricao[:2000])
    if repo.url_html:
        props[campos.url] = properties.url(repo.url_html)
    if repo.homepage:
        props[campos.homepage] = properties.url(repo.homepage)
    if repo.linguagem:
        props[campos.linguagem] = properties.select(repo.linguagem)
    if repo.topicos:
        props[campos.topicos] = properties.multi_select(repo.topicos)
    if repo.licenca:
        props[campos.licenca] = properties.select(repo.licenca)
    if repo.criado_em:
        props[campos.criado_em] = properties.date(repo.criado_em)
    if repo.atualizado_em:
        props[campos.atualizado_em] = properties.date(repo.atualizado_em)
    if repo.enviado_em:
        props[campos.enviado_em] = properties.date(repo.enviado_em)
    if readme_hash is not None:
        props[campos.readme_hash] = properties.rich_text(readme_hash)
    return props


def garantir_database(
    pagina_id: str,
    *,
    titulo: str = "GITHUB",
    cliente: NotionClient,
    campos: CamposGitHub | None = None,
) -> str:
    """Cria o database de inventário sob ``pagina_id`` e devolve o ID.

    Não tenta deduplicar databases existentes: a busca do Notion não filtra por
    página-pai de forma confiável, e criar o database é a operação que o chamador
    pede explicitamente. Para reusar um database já criado, passe o ID dele pelo
    chamador em vez de chamar esta função.
    """

    campos = campos or CamposGitHub()
    resposta = cliente.criar_database(
        pagina_id=pagina_id,
        titulo=titulo,
        propriedades=construir_schema(campos),
    )
    database_id = str(resposta.get("id") or "")
    if not database_id:
        raise ValueError("O Notion não retornou o ID do database criado.")
    return database_id


def garantir_coluna_hash(
    database_id: str,
    *,
    cliente: NotionClient,
    campos: CamposGitHub | None = None,
) -> bool:
    """Garante que a coluna de hash do README exista no database.

    Databases criados antes desta coluna não a têm, e gravar o hash falharia.
    Esta função a adiciona quando falta, sem mexer em nada se já existe. Usa o
    *data source* (modelo novo do Notion) quando o database expõe um; cai para o
    endpoint clássico de database caso contrário. Devolve ``True`` se criou a
    coluna, ``False`` se já existia.
    """

    campos = campos or CamposGitHub()
    nova = {campos.readme_hash: {"rich_text": {}}}

    fontes = cliente.listar_data_sources(database_id)
    if fontes:
        data_source_id = str(fontes[0].get("id") or "")
        fonte = cliente.get_data_source(data_source_id)
        if campos.readme_hash in fonte.get("properties", {}):
            return False
        cliente.atualizar_data_source(data_source_id, propriedades=nova)
        return True

    database = cliente.get_database(database_id)
    if campos.readme_hash in database.get("properties", {}):
        return False
    cliente.atualizar_database(database_id, propriedades=nova)
    return True


def _pagina_existente(
    cliente: NotionClient,
    database_id: str,
    repo: RepoInfo,
    campos: CamposGitHub,
) -> dict[str, Any] | None:
    """Procura uma página do repositório por URL (ou nome, se faltar URL)."""

    if repo.url_html:
        filtro: dict[str, object] = {
            "property": campos.url,
            "url": {"equals": repo.url_html},
        }
    else:
        filtro = {
            "property": campos.nome,
            "title": {"equals": repo.nome_completo or repo.nome},
        }
    paginas = cliente.consultar_database(database_id, page_size=1, filtro=filtro)
    return paginas[0] if paginas else None


def _escrever_readme(
    cliente: NotionClient,
    page_id: str,
    readme: str,
) -> bool:
    """Cria uma subpágina ``README`` dentro da página do projeto.

    O conteúdo do README (Markdown) é convertido em blocos e vai para uma
    **página filha** chamada ``README`` — não para o corpo da própria linha do
    database —, deixando a linha limpa e fácil de organizar depois. A quebra em
    lotes ≤100 blocos é responsabilidade de :meth:`NotionClient.criar_subpagina`.

    Retorna ``True`` se a subpágina foi criada com conteúdo.
    """

    from notion_starter.services.conteudo import markdown_para_blocos

    texto = (readme or "").strip()
    if not texto:
        return False

    blocos = markdown_para_blocos(texto[:MAX_README_CHARS])
    if not blocos:
        return False

    cliente.criar_subpagina(page_id, TITULO_README, blocos=blocos)
    return True


def _localizar_subpaginas_readme(cliente: NotionClient, page_id: str) -> list[str]:
    """Devolve os IDs de **todas** as subpáginas ``README`` da página.

    Retorna uma lista (não só a primeira) porque execuções anteriores com
    retries podem ter deixado READMEs duplicados — todos devem ser removidos
    antes de recriar, senão a página acumula cópias.
    """

    ids: list[str] = []
    for bloco in cliente.ler_blocos(page_id):
        if bloco.get("type") != "child_page":
            continue
        if bloco.get("child_page", {}).get("title", "") == TITULO_README:
            bloco_id = str(bloco.get("id") or "")
            if bloco_id:
                ids.append(bloco_id)
    return ids


def _sincronizar_readme(
    cliente: NotionClient,
    page_id: str,
    readme: str | None,
    *,
    hash_atual: str,
    hash_novo: str,
) -> bool:
    """Substitui a subpágina ``README`` quando o conteúdo mudou (por hash).

    Idempotente: se ``hash_novo == hash_atual`` não faz nada. Se mudou, apaga a
    subpágina README antiga (quando existe) e recria com o conteúdo novo. Devolve
    ``True`` se a subpágina foi (re)escrita.
    """

    if hash_novo == hash_atual:
        return False

    for antiga in _localizar_subpaginas_readme(cliente, page_id):
        cliente.excluir_bloco(antiga)
    if not hash_novo:
        return False  # README ficou vazio: removeu as antigas, nada a recriar
    return _escrever_readme(cliente, page_id, readme or "")


def exportar_repos(
    contas: list[str],
    database_id: str,
    *,
    github_client: GitHubClient,
    notion_client: NotionClient,
    campos: CamposGitHub | None = None,
    incluir_readme: bool = True,
    ignorar_arquivados: bool = False,
) -> ResumoInventario:
    """Exporta os repositórios das ``contas`` para o ``database_id``.

    Faz *upsert* por repositório (cria a página ou atualiza a existente) e, quando
    ``incluir_readme`` é verdadeiro, busca os detalhes do repo e escreve o README
    no corpo da página recém-criada. READMEs só são escritos em páginas novas,
    para não duplicar o conteúdo em execuções repetidas.

    Quando ``ignorar_arquivados`` é verdadeiro, repositórios arquivados no GitHub
    são pulados.

    Erros por repositório são acumulados em :attr:`ResumoInventario.erros` e não
    interrompem a exportação dos demais.
    """

    if not contas:
        raise ValueError("Informe ao menos uma conta do GitHub.")
    if not database_id:
        raise ValueError("database_id é obrigatório.")

    campos = campos or CamposGitHub()
    resumo = ResumoInventario()

    for repo in _coletar_repos(
        contas, github_client, resumo, ignorar_arquivados=ignorar_arquivados
    ):
        _exportar_repo(
            repo,
            database_id,
            github_client=github_client,
            notion_client=notion_client,
            campos=campos,
            incluir_readme=incluir_readme,
            resumo=resumo,
        )

    return resumo


def _coletar_repos(
    contas: list[str],
    github_client: GitHubClient,
    resumo: ResumoInventario,
    *,
    ignorar_arquivados: bool = False,
):
    """Itera os repositórios de todas as ``contas``, sem duplicar entre elas.

    Conta `repos_encontrados` e registra falhas de listagem em ``resumo.erros``,
    seguindo para as demais contas. É a coleta compartilhada por
    :func:`exportar_repos` e :func:`atualizar_repos`.

    Quando ``ignorar_arquivados`` é verdadeiro, repositórios arquivados no GitHub
    são pulados (não entram na contagem de ``repos_encontrados``), útil para
    manter a database só com projetos ativos.
    """

    vistos: set[str] = set()
    for conta in contas:
        try:
            repos = github_client.listar_repos(conta)
        except Exception as exc:  # noqa: BLE001 — registramos e seguimos
            resumo.erros.append(f"listar {conta}: {exc}")
            continue
        for repo in repos:
            if ignorar_arquivados and repo.arquivado:
                continue
            chave = repo.url_html or repo.nome_completo
            if chave in vistos:
                continue
            vistos.add(chave)
            resumo.repos_encontrados += 1
            yield repo


def _exportar_repo(
    repo: RepoInfo,
    database_id: str,
    *,
    github_client: GitHubClient,
    notion_client: NotionClient,
    campos: CamposGitHub,
    incluir_readme: bool,
    resumo: ResumoInventario,
) -> None:
    """Cria/atualiza a página de um repositório e escreve o README se for nova."""

    try:
        props = _propriedades_pagina(repo, campos)
        existente = _pagina_existente(notion_client, database_id, repo, campos)
        if existente and existente.get("id"):
            notion_client.atualizar_pagina(str(existente["id"]), props)
            resumo.paginas_atualizadas += 1
            return

        criada = notion_client.criar_pagina(database_id, props)
        resumo.paginas_criadas += 1
    except Exception as exc:  # noqa: BLE001 — registramos e seguimos
        resumo.erros.append(f"{repo.nome_completo}: {exc}")
        return

    if not incluir_readme:
        return

    page_id = str(criada.get("id") or "")
    if not page_id:
        return
    try:
        detalhado = github_client.detalhar_repo(repo.nome_completo)
        if detalhado.readme and _escrever_readme(notion_client, page_id, detalhado.readme):
            resumo.readmes_escritos += 1
            # Grava o hash para que a próxima atualização detecte mudanças.
            notion_client.atualizar_pagina(
                page_id,
                {campos.readme_hash: properties.rich_text(_hash_readme(detalhado.readme))},
            )
    except Exception as exc:  # noqa: BLE001 — README é best-effort
        resumo.erros.append(f"readme {repo.nome_completo}: {exc}")


def atualizar_repos(
    contas: list[str],
    database_id: str,
    *,
    github_client: GitHubClient,
    notion_client: NotionClient,
    campos: CamposGitHub | None = None,
    sincronizar_readme: bool = True,
    ignorar_arquivados: bool = False,
    apenas_mudancas: bool = False,
) -> ResumoInventario:
    """Re-sincroniza o inventário das ``contas`` no ``database_id``.

    Para cada repositório: cria a página se for novo, atualiza as propriedades se
    já existir e — quando ``sincronizar_readme`` — substitui a subpágina README se
    o conteúdo mudou (detectado por hash gravado na página, sem reler os blocos).
    Repositórios renomeados são tratados pelo *match* por URL, que não muda quando
    o nome muda.

    Quando ``ignorar_arquivados`` é verdadeiro, repositórios arquivados no GitHub
    são pulados — a database fica só com projetos ativos.

    Quando ``apenas_mudancas`` é verdadeiro, repositórios já existentes cujo
    ``updated_at`` não avançou desde o último sync são pulados sem reescrita nem
    busca de README (contados em :attr:`ResumoInventario.paginas_puladas`),
    economizando chamadas. Repositórios novos entram normalmente.

    Erros por repositório são acumulados em :attr:`ResumoInventario.erros` e não
    interrompem a atualização dos demais.
    """

    if not contas:
        raise ValueError("Informe ao menos uma conta do GitHub.")
    if not database_id:
        raise ValueError("database_id é obrigatório.")

    campos = campos or CamposGitHub()
    resumo = ResumoInventario()

    # Databases antigos podem não ter a coluna de hash; garante antes de gravar.
    if sincronizar_readme:
        try:
            garantir_coluna_hash(database_id, cliente=notion_client, campos=campos)
        except Exception as exc:  # noqa: BLE001 — segue; a 1ª escrita avisaria de novo
            resumo.erros.append(f"garantir coluna README hash: {exc}")

    for repo in _coletar_repos(
        contas, github_client, resumo, ignorar_arquivados=ignorar_arquivados
    ):
        _atualizar_repo(
            repo,
            database_id,
            github_client=github_client,
            notion_client=notion_client,
            campos=campos,
            sincronizar_readme=sincronizar_readme,
            apenas_mudancas=apenas_mudancas,
            resumo=resumo,
        )

    return resumo


def _atualizar_repo(
    repo: RepoInfo,
    database_id: str,
    *,
    github_client: GitHubClient,
    notion_client: NotionClient,
    campos: CamposGitHub,
    sincronizar_readme: bool,
    resumo: ResumoInventario,
    apenas_mudancas: bool = False,
) -> None:
    """Cria ou atualiza a página de um repositório e re-sincroniza o README."""

    existente = None
    try:
        existente = _pagina_existente(notion_client, database_id, repo, campos)
    except Exception as exc:  # noqa: BLE001
        resumo.erros.append(f"{repo.nome_completo}: {exc}")
        return

    # Modo incremental: se a página já existe e o repo não mudou desde o último
    # sync, pula sem reescrever nem buscar README (economiza chamadas).
    if (
        apenas_mudancas
        and existente
        and existente.get("id")
        and not _repo_mudou_desde_pagina(repo, existente, campos)
    ):
        resumo.paginas_puladas += 1
        return

    # Repo novo: cai no fluxo de criação (escreve README + grava hash).
    if not (existente and existente.get("id")):
        _exportar_repo(
            repo,
            database_id,
            github_client=github_client,
            notion_client=notion_client,
            campos=campos,
            incluir_readme=sincronizar_readme,
            resumo=resumo,
        )
        return

    page_id = str(existente["id"])

    # Busca o README atual (para hash) só quando vamos sincronizá-lo.
    readme: str | None = None
    hash_novo = ""
    if sincronizar_readme:
        try:
            readme = github_client.detalhar_repo(repo.nome_completo).readme
            hash_novo = _hash_readme(readme)
        except Exception as exc:  # noqa: BLE001 — README é best-effort
            resumo.erros.append(f"readme {repo.nome_completo}: {exc}")

    try:
        readme_hash = hash_novo if sincronizar_readme else None
        props = _propriedades_pagina(repo, campos, readme_hash=readme_hash)
        notion_client.atualizar_pagina(page_id, props)
        resumo.paginas_atualizadas += 1
    except Exception as exc:  # noqa: BLE001
        resumo.erros.append(f"{repo.nome_completo}: {exc}")
        return

    if not sincronizar_readme:
        return

    hash_atual = ler_rich_text(existente.get("properties", {}).get(campos.readme_hash))
    try:
        if _sincronizar_readme(
            notion_client, page_id, readme, hash_atual=hash_atual, hash_novo=hash_novo
        ):
            resumo.readmes_atualizados += 1
    except Exception as exc:  # noqa: BLE001 — README é best-effort
        resumo.erros.append(f"readme {repo.nome_completo}: {exc}")
