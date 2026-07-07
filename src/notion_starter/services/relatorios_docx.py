"""Exportacao de relatorios diarios do Notion para DOCX.

O caso de uso junta propriedades e corpo da pagina numa unica passada: consulta
o database por periodo, le os blocos de cada relatorio como Markdown e renderiza
um arquivo DOCX profissional por dia. A borda CLI/API deve apenas resolver
parametros; a regra de negocio fica aqui.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - coberto indiretamente nos ambientes com dependencia.
    from docx import Document
    from docx.enum.section import WD_SECTION_START
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "A exportacao DOCX exige a dependencia 'python-docx'. "
        "Instale o pacote ou reinstale notion-starter."
    ) from exc

from notion_starter import readers
from notion_starter.content import blocos_para_markdown

PROPRIEDADES_DESTAQUE_PADRAO = (
    "Data",
    "Status",
    "Area",
    "Área",
    "Resumo",
    "Bloqueios",
    "Proximos passos",
    "Próximos passos",
    "Tasks feitas",
    "Arquivos complementares",
)

SECOES_DESTAQUE = (
    ("Resumo", ("Resumo",)),
    ("Bloqueios", ("Bloqueios",)),
    ("Proximos passos", ("Proximos passos", "Próximos passos")),
)


@dataclass(frozen=True)
class RelatorioDocxExportado:
    """Resumo serializavel de um DOCX gerado."""

    id: str
    titulo: str
    data: str
    arquivo: str


def exportar_relatorios_docx(
    *,
    database_id: str,
    data_inicio: str,
    data_fim: str,
    saida: str | Path,
    cliente: Any,
    campo_data: str = "Data",
    propriedades_destaque: tuple[str, ...] = PROPRIEDADES_DESTAQUE_PADRAO,
) -> dict[str, Any]:
    """Exporta um arquivo DOCX por relatorio no intervalo informado.

    Args:
        database_id: ID do database de relatorios.
        data_inicio: Inicio do periodo em ISO ``YYYY-MM-DD``.
        data_fim: Fim do periodo em ISO ``YYYY-MM-DD``.
        saida: Diretorio onde os arquivos serao gravados.
        cliente: Instancia compativel com ``NotionClient``.
        campo_data: Nome da propriedade de data usada no filtro.
        propriedades_destaque: Propriedades que aparecem primeiro no DOCX.

    Returns:
        Dicionario serializavel para CLI/API, com periodo e arquivos gerados.
    """

    inicio = _parse_data(data_inicio, "data_inicio")
    fim = _parse_data(data_fim, "data_fim")
    if fim < inicio:
        raise ValueError("data_fim deve ser maior ou igual a data_inicio.")

    destino = Path(saida)
    destino.mkdir(parents=True, exist_ok=True)

    filtro = {
        "and": [
            {"property": campo_data, "date": {"on_or_after": inicio.isoformat()}},
            {"property": campo_data, "date": {"on_or_before": fim.isoformat()}},
        ]
    }
    paginas = cliente.consultar_database(database_id, buscar_todos=True, filtro=filtro)
    relatorios = [
        _montar_relatorio(
            pagina,
            cliente=cliente,
            destino=destino,
            campo_data=campo_data,
            propriedades_destaque=propriedades_destaque,
        )
        for pagina in paginas
    ]
    relatorios.sort(key=lambda item: (item.data, item.titulo.lower()))

    return {
        "database_id": database_id,
        "periodo": {"de": inicio.isoformat(), "ate": fim.isoformat()},
        "campo_data": campo_data,
        "saida": str(destino),
        "total": len(relatorios),
        "arquivos": [asdict(item) for item in relatorios],
    }


def _montar_relatorio(
    pagina: dict[str, Any],
    *,
    cliente: Any,
    destino: Path,
    campo_data: str,
    propriedades_destaque: tuple[str, ...],
) -> RelatorioDocxExportado:
    valores = readers.extrair_valores(pagina)
    titulo = _titulo_pagina(pagina, valores)
    data_relatorio = _data_pagina(valores, campo_data)
    blocos = cliente.ler_blocos(pagina["id"], buscar_todos=True, recursivo=True)
    markdown = blocos_para_markdown(blocos)

    nome_arquivo = f"{data_relatorio} - {_nome_seguro(titulo or 'Relatorio')}.docx"
    caminho = destino / nome_arquivo
    renderizar_docx(
        caminho,
        titulo=titulo or "Relatorio",
        data_relatorio=data_relatorio,
        propriedades=valores,
        markdown=markdown,
        propriedades_destaque=propriedades_destaque,
    )
    return RelatorioDocxExportado(
        id=pagina["id"],
        titulo=titulo,
        data=data_relatorio,
        arquivo=str(caminho),
    )


def renderizar_docx(
    caminho: str | Path,
    *,
    titulo: str,
    data_relatorio: str,
    propriedades: dict[str, Any],
    markdown: str,
    propriedades_destaque: tuple[str, ...] = PROPRIEDADES_DESTAQUE_PADRAO,
) -> Path:
    """Renderiza um relatorio ja carregado em um arquivo DOCX."""

    documento = Document()
    _configurar_documento(documento)
    _adicionar_capa(documento, titulo, data_relatorio, propriedades)
    _adicionar_sumario_manual(documento)
    _adicionar_tabela_propriedades(documento, propriedades, propriedades_destaque)
    _adicionar_secoes_destaque(documento, propriedades)
    _adicionar_markdown(documento, markdown)

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    documento.save(destino)
    return destino


def _configurar_documento(documento: Any) -> None:
    section = documento.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    styles = documento.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10.5)
    for style_name, size in (("Title", 24), ("Heading 1", 17), ("Heading 2", 14)):
        styles[style_name].font.name = "Aptos Display"
        styles[style_name].font.size = Pt(size)
        styles[style_name].font.color.rgb = RGBColor(31, 41, 55)


def _adicionar_capa(
    documento: Any,
    titulo: str,
    data_relatorio: str,
    propriedades: dict[str, Any],
) -> None:
    dia = _dia_semana(data_relatorio)
    p = documento.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Relatorio diario")
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(75, 85, 99)

    h = documento.add_heading(titulo, level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitulo = documento.add_paragraph()
    subtitulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitulo.add_run(f"{data_relatorio} - {dia}").italic = True

    resumo = _primeiro_valor(propriedades, ("Resumo",))
    if resumo:
        p_resumo = documento.add_paragraph()
        p_resumo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_resumo.add_run(_valor_para_texto(resumo))

    documento.add_section(WD_SECTION_START.NEW_PAGE)


def _adicionar_sumario_manual(documento: Any) -> None:
    documento.add_heading("Sumario", level=1)
    for item in (
        "Propriedades",
        "Resumo",
        "Bloqueios",
        "Proximos passos",
        "Relatorio completo",
    ):
        documento.add_paragraph(item, style="List Bullet")


def _adicionar_tabela_propriedades(
    documento: Any,
    propriedades: dict[str, Any],
    propriedades_destaque: tuple[str, ...],
) -> None:
    documento.add_heading("Propriedades", level=1)
    ordenadas = _ordenar_propriedades(propriedades, propriedades_destaque)
    tabela = documento.add_table(rows=1, cols=2)
    tabela.style = "Table Grid"
    cabecalho = tabela.rows[0].cells
    cabecalho[0].text = "Campo"
    cabecalho[1].text = "Valor"
    for nome, valor in ordenadas:
        texto = _valor_para_texto(valor)
        if not texto:
            continue
        cells = tabela.add_row().cells
        cells[0].text = nome
        cells[1].text = texto


def _adicionar_secoes_destaque(documento: Any, propriedades: dict[str, Any]) -> None:
    for titulo, nomes in SECOES_DESTAQUE:
        valor = _primeiro_valor(propriedades, nomes)
        if valor:
            documento.add_heading(titulo, level=1)
            _adicionar_paragrafos_texto(documento, _valor_para_texto(valor))


def _adicionar_markdown(documento: Any, markdown: str) -> None:
    documento.add_heading("Relatorio completo", level=1)
    linhas = markdown.splitlines()
    i = 0
    em_codigo = False
    codigo: list[str] = []
    while i < len(linhas):
        linha = linhas[i]
        if linha.startswith("```"):
            if em_codigo:
                _adicionar_codigo(documento, "\n".join(codigo))
                codigo = []
                em_codigo = False
            else:
                em_codigo = True
            i += 1
            continue
        if em_codigo:
            codigo.append(linha)
            i += 1
            continue
        if _linha_tabela(linha):
            bloco, i = _coletar_tabela(linhas, i)
            _adicionar_tabela_markdown(documento, bloco)
            continue
        _adicionar_linha_markdown(documento, linha)
        i += 1
    if codigo:
        _adicionar_codigo(documento, "\n".join(codigo))


def _adicionar_linha_markdown(documento: Any, linha: str) -> None:
    texto = linha.strip()
    if not texto:
        documento.add_paragraph()
        return
    if texto.startswith("# "):
        documento.add_heading(texto[2:].strip(), level=1)
        return
    if texto.startswith("## "):
        documento.add_heading(texto[3:].strip(), level=2)
        return
    if texto.startswith("### "):
        documento.add_heading(texto[4:].strip(), level=3)
        return
    if texto.startswith("- [ ] ") or texto.startswith("- [x] "):
        marcador = "[x]" if texto.startswith("- [x] ") else "[ ]"
        p = documento.add_paragraph(style="List Bullet")
        _adicionar_inline(p, f"{marcador} {texto[6:]}")
        return
    if texto.startswith("- "):
        p = documento.add_paragraph(style="List Bullet")
        _adicionar_inline(p, texto[2:])
        return
    if re.match(r"^\d+\.\s+", texto):
        p = documento.add_paragraph(style="List Number")
        _adicionar_inline(p, re.sub(r"^\d+\.\s+", "", texto))
        return
    if texto.startswith("> "):
        p = documento.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.add_run(texto[2:]).italic = True
        return
    p = documento.add_paragraph()
    _adicionar_inline(p, texto)


def _adicionar_inline(paragrafo: Any, texto: str) -> None:
    padrao = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
    pos = 0
    for match in padrao.finditer(texto):
        if match.start() > pos:
            paragrafo.add_run(texto[pos : match.start()])
        token = match.group(0)
        run = paragrafo.add_run(token[2:-2] if token.startswith("**") else token[1:-1])
        if token.startswith("**"):
            run.bold = True
        else:
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        pos = match.end()
    if pos < len(texto):
        paragrafo.add_run(texto[pos:])


def _adicionar_codigo(documento: Any, texto: str) -> None:
    p = documento.add_paragraph()
    run = p.add_run(texto)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    p.paragraph_format.left_indent = Inches(0.25)


def _adicionar_paragrafos_texto(documento: Any, texto: str) -> None:
    for linha in texto.splitlines() or [texto]:
        if linha.strip():
            documento.add_paragraph(linha.strip())


def _linha_tabela(linha: str) -> bool:
    return linha.strip().startswith("|") and linha.strip().endswith("|")


def _coletar_tabela(linhas: list[str], inicio: int) -> tuple[list[str], int]:
    bloco: list[str] = []
    i = inicio
    while i < len(linhas) and _linha_tabela(linhas[i]):
        bloco.append(linhas[i])
        i += 1
    return bloco, i


def _adicionar_tabela_markdown(documento: Any, linhas: list[str]) -> None:
    linhas_validas = [
        [celula.strip() for celula in linha.strip().strip("|").split("|")]
        for linha in linhas
        if not re.match(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", linha.strip())
    ]
    if not linhas_validas:
        return
    tabela = documento.add_table(rows=0, cols=len(linhas_validas[0]))
    tabela.style = "Table Grid"
    for linha in linhas_validas:
        cells = tabela.add_row().cells
        for idx, valor in enumerate(linha[: len(cells)]):
            cells[idx].text = valor


def _parse_data(valor: str, campo: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise ValueError(f"{campo} deve estar no formato YYYY-MM-DD.") from exc


def _data_pagina(valores: dict[str, Any], campo_data: str) -> str:
    valor = valores.get(campo_data)
    if not valor:
        raise ValueError(f"Relatorio sem propriedade de data preenchida: {campo_data}.")
    return str(valor)[:10]


def _titulo_pagina(pagina: dict[str, Any], valores: dict[str, Any]) -> str:
    for prop in pagina.get("properties", {}).values():
        if prop.get("type") == "title":
            titulo = readers.ler_title(prop)
            if titulo:
                return titulo
    for valor in valores.values():
        if isinstance(valor, str) and valor:
            return valor
    return pagina.get("id", "")


def _primeiro_valor(propriedades: dict[str, Any], nomes: tuple[str, ...]) -> Any:
    for nome in nomes:
        valor = propriedades.get(nome)
        if valor:
            return valor
    return None


def _ordenar_propriedades(
    propriedades: dict[str, Any], destaque: tuple[str, ...]
) -> list[tuple[str, Any]]:
    vistos: set[str] = set()
    ordenadas: list[tuple[str, Any]] = []
    for nome in destaque:
        if nome in propriedades and nome not in vistos:
            ordenadas.append((nome, propriedades[nome]))
            vistos.add(nome)
    for nome in sorted(propriedades):
        if nome not in vistos:
            ordenadas.append((nome, propriedades[nome]))
    return ordenadas


def _valor_para_texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, list):
        return ", ".join(_valor_para_texto(item) for item in valor if item)
    if isinstance(valor, dict):
        return ", ".join(f"{k}: {_valor_para_texto(v)}" for k, v in valor.items() if v)
    return str(valor)


def _nome_seguro(valor: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", valor).strip(" .-")
    nome = re.sub(r"\s+", " ", nome)
    return nome[:120] or "Relatorio"


def _dia_semana(data_iso: str) -> str:
    nomes = (
        "segunda-feira",
        "terca-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sabado",
        "domingo",
    )
    return nomes[datetime.fromisoformat(data_iso[:10]).weekday()]
