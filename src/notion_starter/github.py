"""Adaptador resiliente para a API REST do GitHub.

Esta camada concentra HTTP, autenticação, paginação e normalização dos dados.
Casos de uso recebem :class:`RepoInfo` e não dependem do JSON cru do GitHub.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_TIMEOUT = 15
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
MAX_REPOS = 500

_PADRAO_USUARIO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_PADRAO_REPO = re.compile(r"^[A-Za-z0-9_.-]+$")
_PADRAO_URL_PERFIL = re.compile(r"github\.com/([^/\s?#]+)", re.IGNORECASE)


def extrair_login(texto: str) -> str:
    """Extrai o login do GitHub de uma URL de perfil, ``@handle`` ou nome puro.

    Aceita ``https://github.com/User``, ``github.com/User/``, ``@User`` e
    ``User``. Devolve só o login (sem validar o formato — quem valida é
    :meth:`GitHubClient._validar_usuario`). Facilita colar URLs de perfil ao
    importar vários usuários de uma vez, sem obrigar o chamador a limpar a mão.
    """

    bruto = (texto or "").strip()
    if not bruto:
        return ""
    match = _PADRAO_URL_PERFIL.search(bruto)
    if match:
        return match.group(1).strip()
    return bruto.lstrip("@").strip().rstrip("/")


@dataclass(frozen=True)
class RateLimitInfo:
    """Informações operacionais de limite retornadas pelo GitHub."""

    limite: int | None = None
    restante: int | None = None
    reset_em: int | None = None


@dataclass
class RepoInfo:
    """Objeto de domínio normalizado de um repositório GitHub."""

    nome: str
    nome_completo: str
    descricao: str | None = None
    url_html: str | None = None
    url_api: str | None = None
    homepage: str | None = None
    linguagem: str | None = None
    linguagens: dict[str, int] = field(default_factory=dict)
    readme: str | None = None
    topicos: list[str] = field(default_factory=list)
    estrelas: int = 0
    forks: int = 0
    issues_abertas: int = 0
    observadores: int = 0
    tamanho_kb: int = 0
    privado: bool = False
    fork: bool = False
    arquivado: bool = False
    licenca: str | None = None
    dono: str | None = None
    branch_padrao: str | None = None
    criado_em: str | None = None
    atualizado_em: str | None = None
    enviado_em: str | None = None


def _repo_de_resposta(data: dict[str, Any]) -> RepoInfo:
    """Converte o JSON da API do GitHub em :class:`RepoInfo`."""

    topicos = data.get("topics")
    licenca = data.get("license")
    dono = data.get("owner")
    return RepoInfo(
        nome=str(data.get("name") or ""),
        nome_completo=str(data.get("full_name") or ""),
        descricao=data.get("description"),
        url_html=data.get("html_url"),
        url_api=data.get("url"),
        homepage=data.get("homepage") or None,
        linguagem=data.get("language"),
        topicos=list(topicos) if isinstance(topicos, list) else [],
        estrelas=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
        issues_abertas=int(data.get("open_issues_count") or 0),
        observadores=int(data.get("watchers_count") or 0),
        tamanho_kb=int(data.get("size") or 0),
        privado=bool(data.get("private", False)),
        fork=bool(data.get("fork", False)),
        arquivado=bool(data.get("archived", False)),
        licenca=(licenca.get("spdx_id") if isinstance(licenca, dict) else None) or None,
        dono=(dono.get("login") if isinstance(dono, dict) else None) or None,
        branch_padrao=data.get("default_branch"),
        criado_em=data.get("created_at"),
        atualizado_em=data.get("updated_at"),
        enviado_em=data.get("pushed_at"),
    )


def _inteiro_header(valor: str | None) -> int | None:
    try:
        return int(valor) if valor is not None else None
    except ValueError:
        return None


class GitHubAPIError(Exception):
    """Falha previsível retornada pela API do GitHub."""

    def __init__(
        self,
        status_code: int,
        body: str = "",
        *,
        rate_limit: RateLimitInfo | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body[:500]
        self.rate_limit = rate_limit
        super().__init__(f"GitHub HTTP {status_code}: {self.body}")


class GitHubConnectionError(Exception):
    """Falha de rede, timeout ou DNS após esgotar as retentativas."""


class GitHubClient:
    """Cliente HTTP resiliente para a API REST do GitHub.

    O token é opcional para repositórios públicos. Quando existe e o usuário
    consultado é o mesmo usuário autenticado, a listagem também inclui os
    repositórios privados pertencentes a essa conta.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = GITHUB_API_BASE,
        timeout: int = GITHUB_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = BACKOFF_BASE,
        max_repos: int = MAX_REPOS,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries não pode ser negativo.")
        if timeout <= 0:
            raise ValueError("timeout deve ser maior que zero.")
        if max_repos < 1:
            raise ValueError("max_repos deve ser maior que zero.")

        self._token = self._resolver_token(token)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = max(backoff_base, 0.0)
        self._max_repos = max_repos

    @staticmethod
    def _resolver_token(token: str | None) -> str | None:
        if token is not None:
            return token.strip() or None
        return os.environ.get(GITHUB_TOKEN_ENV, "").strip() or None

    def _headers(self, *, accept: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": accept or "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _rate_limit(response: requests.Response) -> RateLimitInfo:
        return RateLimitInfo(
            limite=_inteiro_header(response.headers.get("X-RateLimit-Limit")),
            restante=_inteiro_header(response.headers.get("X-RateLimit-Remaining")),
            reset_em=_inteiro_header(response.headers.get("X-RateLimit-Reset")),
        )

    @staticmethod
    def _eh_rate_limit(response: requests.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if response.headers.get("Retry-After"):
            return True
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        return "rate limit" in response.text.lower()

    def _request(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        accept: str | None = None,
        aceitar_404: bool = False,
    ) -> requests.Response | None:
        """Executa HTTP com retry em rede, rate limit e respostas 5xx."""

        url = f"{self._base_url}{path}"
        ultimo_erro: Exception | None = None

        for tentativa in range(self._max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._headers(accept=accept),
                    params=params,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                ultimo_erro = exc
                if tentativa < self._max_retries:
                    time.sleep(self._backoff_base * (2**tentativa))
                    continue
                raise GitHubConnectionError(str(exc)) from exc

            if response.status_code < 400:
                return response
            if aceitar_404 and response.status_code == 404:
                return None

            retentavel = response.status_code >= 500 or self._eh_rate_limit(response)
            erro = GitHubAPIError(
                response.status_code,
                response.text,
                rate_limit=self._rate_limit(response),
            )
            ultimo_erro = erro
            if retentavel and tentativa < self._max_retries:
                time.sleep(self._calcular_espera(response, tentativa))
                continue
            raise erro

        if isinstance(ultimo_erro, GitHubAPIError):
            raise ultimo_erro
        raise GitHubConnectionError(str(ultimo_erro or "Falha desconhecida no GitHub."))

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        response = self._request(method=method, path=path, params=params)
        assert response is not None
        try:
            resultado = response.json()
        except ValueError as exc:
            raise GitHubAPIError(response.status_code, "JSON inválido") from exc
        if not isinstance(resultado, (dict, list)):
            raise GitHubAPIError(response.status_code, "Formato JSON inesperado")
        return resultado

    def _request_text(
        self,
        *,
        path: str,
        accept: str,
        aceitar_404: bool = False,
    ) -> str | None:
        response = self._request(
            method="GET",
            path=path,
            accept=accept,
            aceitar_404=aceitar_404,
        )
        return response.content.decode("utf-8", errors="replace") if response is not None else None

    def _calcular_espera(self, response: requests.Response, tentativa: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return self._backoff_base * (2**tentativa)

    def _get_paginado(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        por_pagina: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= por_pagina <= 100:
            raise ValueError("por_pagina deve estar entre 1 e 100.")

        parametros = dict(params or {})
        parametros["per_page"] = str(por_pagina)
        pagina = 1
        todos: list[dict[str, Any]] = []

        while len(todos) < self._max_repos:
            parametros["page"] = str(pagina)
            resultado = self._request_json(
                method="GET",
                path=path,
                params=parametros,
            )
            if not isinstance(resultado, list):
                raise GitHubAPIError(0, "Resposta paginada inesperada.")
            todos.extend(resultado)
            if len(resultado) < por_pagina:
                break
            pagina += 1

        return todos[: self._max_repos]

    def _login_autenticado(self) -> str | None:
        if not self._token:
            return None
        resultado = self._request_json(method="GET", path="/user")
        if isinstance(resultado, list):
            raise GitHubAPIError(0, "Resposta inesperada ao consultar usuário autenticado.")
        login = resultado.get("login")
        return str(login) if login else None

    def listar_repos(self, usuario: str) -> list[RepoInfo]:
        """Lista públicos e, quando permitido, privados do usuário autenticado."""

        usuario = self._validar_usuario(usuario)
        repos = self._get_paginado(
            f"/users/{usuario}/repos",
            params={"sort": "updated", "direction": "desc", "type": "owner"},
        )

        login = self._login_autenticado()
        if login and login.casefold() == usuario.casefold():
            repos.extend(
                self._get_paginado(
                    "/user/repos",
                    params={
                        "sort": "updated",
                        "direction": "desc",
                        "visibility": "all",
                        "affiliation": "owner",
                    },
                )
            )

        unicos: dict[str, dict[str, Any]] = {}
        for repo in repos:
            dono = str((repo.get("owner") or {}).get("login") or "")
            if dono and dono.casefold() != usuario.casefold():
                continue
            chave = str(repo.get("html_url") or repo.get("full_name") or "")
            if chave:
                unicos[chave] = repo

        ordenados = sorted(
            unicos.values(),
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )
        return [_repo_de_resposta(repo) for repo in ordenados[: self._max_repos]]

    def detalhar_repo(self, repo_completo: str) -> RepoInfo:
        """Busca metadados, linguagens e README de ``owner/repo``."""

        owner, repo = self._validar_repo_completo(repo_completo)
        caminho = f"/repos/{owner}/{repo}"
        resultado = self._request_json(method="GET", path=caminho)
        if isinstance(resultado, list):
            raise GitHubAPIError(0, "Resposta inesperada da API do GitHub.")

        info = _repo_de_resposta(resultado)
        linguagens = self._request_json(method="GET", path=f"{caminho}/languages")
        if not isinstance(linguagens, dict):
            raise GitHubAPIError(0, "Resposta inesperada ao consultar linguagens.")
        info.linguagens = {
            str(nome): int(bytes_usados or 0) for nome, bytes_usados in linguagens.items()
        }
        info.readme = self._request_text(
            path=f"{caminho}/readme",
            accept="application/vnd.github.raw+json",
            aceitar_404=True,
        )
        return info

    @staticmethod
    def _validar_usuario(usuario: str) -> str:
        limpo = extrair_login(usuario)
        if not _PADRAO_USUARIO.fullmatch(limpo):
            raise ValueError("usuario deve ser um login válido do GitHub.")
        return limpo

    @staticmethod
    def _validar_repo_completo(repo_completo: str) -> tuple[str, str]:
        partes = (repo_completo or "").strip().removesuffix(".git").split("/")
        if len(partes) != 2:
            raise ValueError("repo_completo deve estar no formato owner/repo.")
        owner, repo = partes
        if not _PADRAO_USUARIO.fullmatch(owner) or not _PADRAO_REPO.fullmatch(repo):
            raise ValueError("repo_completo deve conter owner e repo válidos.")
        return owner, repo
