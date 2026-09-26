"""Reordenar um bloco nunca pode custar o bloco.

O serviço antigo apagava o original **antes** de criar a cópia, copiava o bloco
lido (com ``"icon": null``, que a API recusa) e não conferia tipo nem filhos.
Resultado medido no workspace real: todo parágrafo reordenado sumia, tabelas e
toggles com filhos iam para a lixeira, e ``--inicio`` mandava o bloco para o
fim. O :class:`PaginaFalsa` abaixo imita a API: tem ordem de filhos, respeita
``position`` e recusa com 400 o que o Notion recusa.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from notion_starter.exceptions import (
    NotionConnectionError,
    NotionHTTPError,
    NotionSyncError,
)
from notion_starter.services import reordenacao as svc


class PaginaFalsa:
    """Filhos de uma página, com a semântica de ``position`` da API."""

    def __init__(self, blocos: list[dict[str, Any]], *, falhar_ao_excluir: bool = False):
        self.blocos = list(blocos)
        self.chamadas: list[tuple[str, Any]] = []
        self.excluidos: list[str] = []
        self.anexados: list[dict[str, Any]] = []
        self.falhar_ao_excluir = falhar_ao_excluir
        self._proximo = 0

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler", block_id))
        return [dict(bloco) for bloco in self.blocos]

    def ids(self) -> list[str]:
        return [bloco["id"] for bloco in self.blocos]

    def anexar_blocos(self, block_id, blocos, *, apos_bloco_id=None, no_inicio=False):
        self.chamadas.append(("anexar", apos_bloco_id, no_inicio))
        for bloco in blocos:
            corpo = bloco[bloco["type"]]
            nulos = [campo for campo, valor in corpo.items() if valor is None]
            if nulos:
                raise NotionHTTPError(
                    400,
                    f"body.children[0].{bloco['type']}.{nulos[0]} should be an object "
                    "or `undefined`, instead was `null`.",
                )
            if bloco["type"] in ("child_page", "table"):
                raise NotionHTTPError(400, "body failed validation")
        novos = []
        for bloco in blocos:
            self._proximo += 1
            novos.append({**bloco, "id": f"novo-{self._proximo}"})
        if no_inicio:
            posicao = 0
        elif apos_bloco_id:
            if apos_bloco_id not in self.ids():
                raise NotionHTTPError(400, f"Block ID {apos_bloco_id} is not parented by")
            posicao = self.ids().index(apos_bloco_id) + 1
        else:
            posicao = len(self.blocos)
        self.blocos[posicao:posicao] = novos
        self.anexados.extend(blocos)
        # Como a API real: com posição, devolve os novos e os irmãos seguintes.
        seguintes = self.blocos[posicao + len(novos) :] if (no_inicio or apos_bloco_id) else []
        return {"results": [*novos, *seguintes]}

    def excluir_bloco(self, block_id):
        self.chamadas.append(("excluir", block_id))
        if self.falhar_ao_excluir:
            raise NotionHTTPError(502, "bad gateway")
        self.excluidos.append(block_id)
        self.blocos = [bloco for bloco in self.blocos if bloco["id"] != block_id]
        return {"id": block_id, "in_trash": True}


def _paragrafo(id_: str, texto: str = "oi") -> dict[str, Any]:
    """Formato real de leitura: ``icon: null`` e ``color`` dentro do corpo."""

    return {
        "object": "block",
        "id": id_,
        "type": "paragraph",
        "created_time": "2026-01-01T00:00:00.000Z",
        "has_children": False,
        "in_trash": False,
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": texto, "link": None},
                    "annotations": {"bold": False, "color": "default"},
                    "plain_text": texto,
                    "href": None,
                }
            ],
            "icon": None,
            "color": "default",
        },
    }


def _bloco(id_: str, tipo: str, corpo: dict[str, Any] | None = None, **extra) -> dict[str, Any]:
    return {"object": "block", "id": id_, "type": tipo, tipo: corpo or {}, **extra}


@pytest.fixture(autouse=True)
def _backup_isolado(tmp_path, monkeypatch):
    """Nenhum teste grava backup na pasta real do usuário."""

    monkeypatch.setenv("NOTION_AUTOMACOES_BACKUP_DIR", str(tmp_path / "backups"))


# -- ordem segura: copiar, conferir, só então apagar -------------------------


def test_paragrafo_com_icon_null_e_reordenado_sem_sumir():
    """A cópia não pode levar ``icon: null``: a API recusa e o bloco sumia."""

    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B"), _paragrafo("C")])

    resultado = svc.reordenar_bloco("pg", "C", apos_bloco_id="A", cliente=pagina)

    assert "icon" not in pagina.anexados[0]["paragraph"]
    assert pagina.ids() == ["A", resultado.bloco_id_novo, "B"]
    assert pagina.excluidos == ["C"]


def test_anexa_a_copia_antes_de_excluir_o_original():
    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B")])

    svc.reordenar_bloco("pg", "B", inicio=True, cliente=pagina)

    etapas = [chamada[0] for chamada in pagina.chamadas]
    assert etapas.index("anexar") < etapas.index("excluir")


def test_falha_ao_anexar_nao_apaga_o_original():
    """Qualquer 400 na cópia deixava a página sem o bloco."""

    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B")])

    with pytest.raises(svc.ReordenacaoIncompletaError) as erro:
        svc.reordenar_bloco("pg", "B", apos_bloco_id="de-outra-pagina", cliente=pagina)

    assert pagina.excluidos == []
    assert pagina.ids() == ["A", "B"]
    assert erro.value.etapa == "anexar"
    assert erro.value.bloco_id_novo is None
    assert Path(erro.value.backup_path).is_file()
    assert "NÃO foi apagado" in str(erro.value)
    assert "is not parented" in str(erro.value)  # o motivo da API não se perde


def test_resposta_perdida_no_anexar_avisa_que_pode_haver_copia():
    class RedeCaiNoAnexar(PaginaFalsa):
        def anexar_blocos(self, *args, **kwargs):
            raise NotionConnectionError("timeout")

    pagina = RedeCaiNoAnexar([_paragrafo("A"), _paragrafo("B")])

    with pytest.raises(svc.ReordenacaoIncompletaError) as erro:
        svc.reordenar_bloco("pg", "B", inicio=True, cliente=pagina)

    assert erro.value.copia_incerta is True
    assert pagina.excluidos == []
    assert "blocos <pagina_id>" in str(erro.value)


def test_falha_ao_excluir_informa_a_duplicata():
    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B")], falhar_ao_excluir=True)

    with pytest.raises(svc.ReordenacaoIncompletaError) as erro:
        svc.reordenar_bloco("pg", "B", inicio=True, cliente=pagina)

    assert erro.value.etapa == "excluir"
    assert erro.value.bloco_id_novo == "novo-1"
    assert "B" in pagina.ids()  # o original continua lá
    assert isinstance(erro.value, NotionSyncError)


# -- posição --------------------------------------------------------------------


def test_inicio_leva_o_bloco_para_o_primeiro_lugar():
    """Sem ``position: start`` o bloco caía no FIM da página."""

    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B"), _paragrafo("C")])

    resultado = svc.reordenar_bloco("pg", "C", inicio=True, cliente=pagina)

    assert pagina.ids() == [resultado.bloco_id_novo, "A", "B"]
    assert pagina.chamadas[1] == ("anexar", None, True)


def test_apos_bloco_usa_o_primeiro_resultado_como_id_novo():
    """Com posição a API devolve também os irmãos seguintes: o novo é o primeiro."""

    pagina = PaginaFalsa([_paragrafo("A"), _paragrafo("B"), _paragrafo("C")])

    resultado = svc.reordenar_bloco("pg", "A", apos_bloco_id="B", cliente=pagina)

    assert resultado.bloco_id_novo == "novo-1"
    assert pagina.ids() == ["B", "novo-1", "C"]


def test_apos_o_proprio_bloco_e_recusado():
    pagina = PaginaFalsa([_paragrafo("A")])

    with pytest.raises(ValueError, match="próprio bloco"):
        svc.reordenar_bloco("pg", "A", apos_bloco_id="A", cliente=pagina)

    assert pagina.excluidos == []


def test_ids_sem_hifen_e_link_encontram_o_bloco():
    com_hifen = "3e691f95-497e-8113-89e4-c13e18c97bd3"
    outro = "3e691f95-497e-81aa-89e4-c13e18c97bd3"
    pagina = PaginaFalsa([_paragrafo(outro), _paragrafo(com_hifen)])

    resultado = svc.reordenar_bloco(
        "pg",
        "https://www.notion.so/Pagina-3e691f95497e816bb57ee8ae6be6d500#3e691f95497e811389e4c13e18c97bd3",
        inicio=True,
        cliente=pagina,
    )

    assert resultado.bloco_id_antigo == com_hifen
    assert pagina.excluidos == [com_hifen]


# -- lista branca, filhos e tipos impossíveis --------------------------------------


@pytest.mark.parametrize(
    "tipo",
    ["table", "column_list", "synced_block", "image", "link_to_page", "unsupported"],
)
def test_tipo_fora_da_lista_branca_e_recusado_sem_escrita(tipo):
    pagina = PaginaFalsa([_bloco("X", tipo)])

    with pytest.raises(svc.BlocoNaoReordenavelError):
        svc.reordenar_bloco("pg", "X", inicio=True, cliente=pagina)

    assert pagina.excluidos == []
    assert pagina.anexados == []


@pytest.mark.parametrize("forcar", [False, True])
def test_child_page_e_recusado_sempre(forcar):
    """A API não recria child_page por append: 'forçar' só destruía a subpágina."""

    pagina = PaginaFalsa([_bloco("cp1", "child_page", {"title": "Estado atual"})])

    with pytest.raises(svc.BlocoImpossivelError, match="interface do Notion"):
        svc.reordenar_bloco(
            "pg", "cp1", inicio=True, forcar_tipos_arriscados=forcar, cliente=pagina
        )

    assert pagina.excluidos == []
    assert pagina.anexados == []


def test_child_database_e_recusado_mesmo_com_forcar():
    pagina = PaginaFalsa([_bloco("db1", "child_database", {"title": "Docs"})])

    with pytest.raises(svc.BlocoImpossivelError):
        svc.reordenar_bloco(
            "pg", "db1", inicio=True, forcar_tipos_arriscados=True, cliente=pagina
        )

    assert pagina.excluidos == []


@pytest.mark.parametrize("tipo", ["toggle", "bulleted_list_item", "heading_2", "paragraph"])
def test_bloco_com_filhos_e_recusado_antes_de_escrever(tipo):
    """A cópia sairia sem os filhos e o original os levaria para a lixeira."""

    pagina = PaginaFalsa([_bloco("T", tipo, {"rich_text": []}, has_children=True)])

    with pytest.raises(svc.BlocoComFilhosError):
        svc.reordenar_bloco("pg", "T", inicio=True, cliente=pagina)

    assert pagina.excluidos == []
    assert pagina.anexados == []


def test_callout_com_icone_hospedado_e_recusado():
    icone = {"type": "file", "file": {"url": "https://s3/expira", "expiry_time": "x"}}
    pagina = PaginaFalsa([_bloco("K", "callout", {"rich_text": [], "icon": icone})])

    with pytest.raises(svc.BlocoNaoReordenavelError, match="expira"):
        svc.reordenar_bloco("pg", "K", inicio=True, cliente=pagina)

    assert pagina.excluidos == []


def test_callout_com_emoji_mantem_o_icone():
    icone = {"type": "emoji", "emoji": "💡"}
    pagina = PaginaFalsa([_bloco("K", "callout", {"rich_text": [], "icon": icone})])

    svc.reordenar_bloco("pg", "K", inicio=True, cliente=pagina)

    assert pagina.anexados[0]["callout"]["icon"] == icone


def test_mencao_de_usuario_vai_no_formato_de_requisicao():
    """A leitura traz nome/avatar do usuário, que a escrita recusa."""

    mencao = {
        "type": "mention",
        "mention": {
            "type": "user",
            "user": {"object": "user", "id": "u1", "name": "Ana", "avatar_url": None},
        },
        "plain_text": "@Ana",
        "href": None,
    }
    pagina = PaginaFalsa([_bloco("M", "paragraph", {"rich_text": [mencao]})])

    svc.reordenar_bloco("pg", "M", inicio=True, cliente=pagina)

    enviado = pagina.anexados[0]["paragraph"]["rich_text"][0]
    assert enviado == {
        "type": "mention",
        "mention": {"type": "user", "user": {"object": "user", "id": "u1"}},
    }


def test_mencao_somente_leitura_e_recusada_antes_de_escrever():
    previa = {"type": "mention", "mention": {"type": "link_preview", "link_preview": {"url": "x"}}}
    pagina = PaginaFalsa([_bloco("L", "paragraph", {"rich_text": [previa]})])

    with pytest.raises(svc.BlocoNaoReordenavelError, match="link_preview"):
        svc.reordenar_bloco("pg", "L", inicio=True, cliente=pagina)

    assert pagina.anexados == []


def test_recusas_derivam_de_notion_sync_error_e_de_value_error():
    for classe in (
        svc.BlocoArriscadoError,
        svc.BlocoImpossivelError,
        svc.BlocoNaoReordenavelError,
        svc.BlocoComFilhosError,
    ):
        assert issubclass(classe, NotionSyncError)
        assert issubclass(classe, ValueError)


# -- backup ---------------------------------------------------------------------------


def test_backup_nunca_cai_no_diretorio_corrente(tmp_path, monkeypatch):
    """Os JSON caíam no cwd e acabaram versionados num repositório público."""

    trabalho = tmp_path / "repo"
    trabalho.mkdir()
    monkeypatch.chdir(trabalho)
    pagina = PaginaFalsa([_paragrafo("A")])

    resultado = svc.reordenar_bloco("pg", "A", inicio=True, cliente=pagina)

    caminho = Path(resultado.backup_path)
    assert caminho.is_absolute()
    assert not (trabalho / ".notion-backups").exists()
    assert caminho.parent == (tmp_path / "backups").resolve()
    assert json.loads(caminho.read_text(encoding="utf-8"))["id"] == "A"


@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX")
def test_backup_e_privado_ao_dono():
    pagina = PaginaFalsa([_paragrafo("A")])

    resultado = svc.reordenar_bloco("pg", "A", inicio=True, cliente=pagina)

    modo = stat.S_IMODE(Path(resultado.backup_path).stat().st_mode)
    assert modo & 0o077 == 0


def test_diretorio_explicito_continua_valendo(tmp_path):
    pagina = PaginaFalsa([_paragrafo("A")])

    resultado = svc.reordenar_bloco(
        "pg", "A", inicio=True, diretorio_backup=tmp_path / "meu", cliente=pagina
    )

    assert Path(resultado.backup_path).parent == (tmp_path / "meu").resolve()


# -- validação de argumentos ---------------------------------------------------------


def test_exige_exatamente_um_alvo():
    pagina = PaginaFalsa([_paragrafo("p1")])
    with pytest.raises(ValueError):
        svc.reordenar_bloco("pg", "p1", cliente=pagina)
    with pytest.raises(ValueError):
        svc.reordenar_bloco("pg", "p1", apos_bloco_id="p2", inicio=True, cliente=pagina)


def test_bloco_nao_encontrado():
    pagina = PaginaFalsa([_paragrafo("p1")])
    with pytest.raises(ValueError, match="não encontrado"):
        svc.reordenar_bloco("pg", "inexistente", inicio=True, cliente=pagina)
