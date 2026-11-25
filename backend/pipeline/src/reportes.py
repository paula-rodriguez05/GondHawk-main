"""
reportes.py
Reportes descargables (PDF, Excel, Word) — GondHawk.

Genera el entregable que el retailer se lleva: el análisis completo con el
heatmap embebido, el embudo por góndola y las recomendaciones.

Los tres formatos salen de la misma estructura de datos para que no se
desincronicen. Cada dependencia se importa dentro de su función: si la máquina
no tiene `python-docx` instalado, el PDF y el Excel deben seguir funcionando en
vez de tumbar el módulo entero al importarlo.

    pip install reportlab openpyxl python-docx
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Paleta corporativa, en los tres formatos que piden las librerías.
AZUL = (0.15, 0.39, 0.71)
GRIS = (0.35, 0.35, 0.35)
AZUL_HEX = "265FB5"
VERDE_HEX = "2E9E5B"
AMBAR_HEX = "D98C1F"
ROJO_HEX = "C0392B"

COLOR_TEMPERATURA = {
    "caliente": ROJO_HEX,
    "templada": AMBAR_HEX,
    "fria": AZUL_HEX,
    "sin_datos": "888888",
}


def _cargar(outdir: Path) -> dict[str, Any]:
    """Reúne las salidas del pipeline en una sola estructura."""
    def leer(nombre: str, default: Any) -> Any:
        ruta = outdir / nombre
        if not ruta.exists():
            return default
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    metricas = leer("metricas_interaccion.json", {})
    pipeline = leer("metricas_pipeline.json", {})

    return {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "video": pipeline.get("video_fuente", "—"),
        "frames": pipeline.get("frames_procesados", 0),
        "detecciones": pipeline.get("total_detecciones", 0),
        "duracion_analisis": pipeline.get("tiempo_procesamiento_seg", 0),
        "total": metricas.get("total", {}),
        "zonas": metricas.get("zonas", []),
        "alertas": metricas.get("alertas", []),
        "recomendaciones": metricas.get("recomendaciones", []),
        "meta": metricas.get("meta", {}),
        "heatmap": outdir / "heatmap.png",
    }


def _filas_embudo(zona: dict[str, Any]) -> list[tuple[str, Any]]:
    e = zona.get("embudo", {})
    return [
        ("Visitas", e.get("visitas", 0)),
        ("Pasa de largo", e.get("pasa_de_largo", 0)),
        ("Se detiene", e.get("se_detiene", 0)),
        ("Toma producto", e.get("toma_producto", 0)),
        ("Devuelve", e.get("devuelve", 0)),
        ("Se lo lleva", e.get("se_lo_lleva", 0)),
    ]


# ── PDF ─────────────────────────────────────────────────────────────────────


def generar_pdf(outdir: Path | str, destino: Path | str | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    outdir = Path(outdir)
    destino = Path(destino) if destino else outdir / "reporte_gondhawk.pdf"
    datos = _cargar(outdir)

    estilos = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=estilos["Heading1"], textColor=colors.Color(*AZUL), fontSize=18)
    h2 = ParagraphStyle("h2", parent=estilos["Heading2"], textColor=colors.Color(*AZUL), fontSize=13)
    normal = estilos["BodyText"]
    pie = ParagraphStyle("pie", parent=normal, fontSize=8, textColor=colors.Color(*GRIS))

    doc = SimpleDocTemplate(
        str(destino), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title="GondHawk — Análisis de góndola",
    )
    hist: list[Any] = []

    hist.append(Paragraph("GondHawk — Análisis de góndola", h1))
    hist.append(Paragraph(
        f"Video: {Path(str(datos['video'])).name} &nbsp;|&nbsp; Generado: {datos['generado']}", pie))
    hist.append(Spacer(1, 0.6 * cm))

    # KPIs
    t = datos["total"]
    kpis = [
        ["Visitas", "Se detiene", "Toma producto", "Tasa interacción", "Tasa rechazo"],
        [
            str(t.get("visitas", 0)),
            str(t.get("se_detiene", 0)),
            str(t.get("toma_producto", 0)),
            f"{t.get('tasa_interaccion', 0) * 100:.1f}%",
            f"{t.get('tasa_rechazo', 0) * 100:.1f}%",
        ],
    ]
    tabla = Table(kpis, colWidths=[3.4 * cm] * 5)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + AZUL_HEX)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, 1), 15),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
    ]))
    hist.append(tabla)
    hist.append(Spacer(1, 0.7 * cm))

    # Heatmap
    if datos["heatmap"].exists():
        hist.append(Paragraph("Mapa de calor de flujo", h2))
        img = ImageReader(str(datos["heatmap"]))
        iw, ih = img.getSize()
        ancho = 16.5 * cm
        hist.append(Image(str(datos["heatmap"]), width=ancho, height=ancho * ih / iw))
        hist.append(Spacer(1, 0.5 * cm))

    # Embudo por zona
    hist.append(PageBreak())
    hist.append(Paragraph("Embudo por góndola", h2))
    hist.append(Spacer(1, 0.3 * cm))

    encabezado = ["Zona", "Visitas", "Se detiene", "Toma", "Devuelve", "Interacción", "Rechazo", "Estado"]
    filas = [encabezado]
    for z in datos["zonas"]:
        e = z.get("embudo", {})
        filas.append([
            z.get("zone_id", "—"),
            e.get("visitas", 0), e.get("se_detiene", 0),
            e.get("toma_producto", 0), e.get("devuelve", 0),
            f"{z.get('tasa_interaccion', 0) * 100:.0f}%",
            f"{z.get('tasa_rechazo', 0) * 100:.0f}%",
            z.get("temperatura", "—"),
        ])

    tabla = Table(filas, colWidths=[3.6 * cm, 1.8 * cm, 2 * cm, 1.6 * cm, 2 * cm, 2.2 * cm, 1.8 * cm, 2 * cm])
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + AZUL_HEX)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
    ]
    for i, z in enumerate(datos["zonas"], start=1):
        color = COLOR_TEMPERATURA.get(z.get("temperatura"), "888888")
        estilo.append(("TEXTCOLOR", (7, i), (7, i), colors.HexColor("#" + color)))
    tabla.setStyle(TableStyle(estilo))
    hist.append(tabla)
    hist.append(Spacer(1, 0.7 * cm))

    # Recomendaciones
    recomendaciones = datos["recomendaciones"] or datos["alertas"]
    if recomendaciones:
        hist.append(Paragraph("Recomendaciones", h2))
        hist.append(Spacer(1, 0.2 * cm))
        for r in recomendaciones:
            titulo = r.get("titulo") or r.get("tipo", "Observación")
            cuerpo = r.get("detalle") or r.get("mensaje", "")
            zona = r.get("zone_id", "")
            hist.append(Paragraph(f"<b>{zona} — {titulo}</b>", normal))
            hist.append(Paragraph(cuerpo, normal))
            if r.get("accion"):
                hist.append(Paragraph(f"<i>Acción sugerida:</i> {r['accion']}", normal))
            hist.append(Spacer(1, 0.25 * cm))

    # Nota de privacidad: va en el reporte porque es un criterio de evaluación
    # del reto y porque el documento sale de la empresa hacia terceros.
    hist.append(Spacer(1, 0.5 * cm))
    hist.append(Paragraph(
        "Privacidad por diseño — Este análisis no utiliza reconocimiento facial ni datos "
        "biométricos. No se almacenan imágenes de personas identificables; los rostros se "
        "difuminan antes de guardar cualquier fotograma. Los identificadores de seguimiento "
        "son temporales y anónimos, y se descartan al terminar el análisis. "
        "Cumple la Ley 1581 de 2012.", pie))

    doc.build(hist)
    return destino


# ── Excel ───────────────────────────────────────────────────────────────────


def generar_excel(outdir: Path | str, destino: Path | str | None = None) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    outdir = Path(outdir)
    destino = Path(destino) if destino else outdir / "reporte_gondhawk.xlsx"
    datos = _cargar(outdir)

    wb = Workbook()
    encabezado_fill = PatternFill("solid", fgColor=AZUL_HEX)
    encabezado_font = Font(color="FFFFFF", bold=True)

    # Hoja 1 — Resumen
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "GondHawk — Análisis de góndola"
    ws["A1"].font = Font(size=16, bold=True, color=AZUL_HEX)
    ws["A2"] = f"Video: {Path(str(datos['video'])).name}"
    ws["A3"] = f"Generado: {datos['generado']}"

    t = datos["total"]
    ws["A5"] = "Indicador"
    ws["B5"] = "Valor"
    for celda in ("A5", "B5"):
        ws[celda].fill = encabezado_fill
        ws[celda].font = encabezado_font

    indicadores = [
        ("Frames procesados", datos["frames"]),
        ("Detecciones totales", datos["detecciones"]),
        ("Duración del análisis (s)", datos["duracion_analisis"]),
        ("Visitas", t.get("visitas", 0)),
        ("Se detiene", t.get("se_detiene", 0)),
        ("Toma producto", t.get("toma_producto", 0)),
        ("Devuelve", t.get("devuelve", 0)),
        ("Se lo lleva", t.get("se_lo_lleva", 0)),
        ("Tasa de interacción", t.get("tasa_interaccion", 0)),
        ("Tasa de rechazo", t.get("tasa_rechazo", 0)),
    ]
    for i, (nombre, valor) in enumerate(indicadores, start=6):
        ws[f"A{i}"] = nombre
        ws[f"B{i}"] = valor
        if "Tasa" in nombre:
            ws[f"B{i}"].number_format = "0.0%"

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 16

    # Hoja 2 — Embudo por zona, con gráfico
    ws2 = wb.create_sheet("Embudo por góndola")
    columnas = ["Zona", "Visitas", "Pasa de largo", "Se detiene", "Toma producto",
                "Devuelve", "Se lo lleva", "Tasa interacción", "Tasa rechazo", "Estado"]
    ws2.append(columnas)
    for c in range(1, len(columnas) + 1):
        celda = ws2.cell(row=1, column=c)
        celda.fill = encabezado_fill
        celda.font = encabezado_font
        celda.alignment = Alignment(horizontal="center")

    for z in datos["zonas"]:
        e = z.get("embudo", {})
        ws2.append([
            z.get("zone_id", "—"),
            e.get("visitas", 0), e.get("pasa_de_largo", 0), e.get("se_detiene", 0),
            e.get("toma_producto", 0), e.get("devuelve", 0), e.get("se_lo_lleva", 0),
            z.get("tasa_interaccion", 0), z.get("tasa_rechazo", 0),
            z.get("temperatura", "—"),
        ])

    for fila in range(2, ws2.max_row + 1):
        ws2.cell(row=fila, column=8).number_format = "0.0%"
        ws2.cell(row=fila, column=9).number_format = "0.0%"
    for c in range(1, len(columnas) + 1):
        ws2.column_dimensions[get_column_letter(c)].width = 16

    if ws2.max_row > 1:
        grafico = BarChart()
        grafico.title = "Embudo por góndola"
        grafico.y_axis.title = "Eventos"
        grafico.add_data(Reference(ws2, min_col=2, max_col=7, min_row=1, max_row=ws2.max_row),
                         titles_from_data=True)
        grafico.set_categories(Reference(ws2, min_col=1, min_row=2, max_row=ws2.max_row))
        grafico.width, grafico.height = 24, 11
        ws2.add_chart(grafico, f"A{ws2.max_row + 3}")

    # Hoja 3 — Recomendaciones
    ws3 = wb.create_sheet("Recomendaciones")
    ws3.append(["Zona", "Tipo", "Recomendación", "Acción sugerida", "Prioridad"])
    for c in range(1, 6):
        ws3.cell(row=1, column=c).fill = encabezado_fill
        ws3.cell(row=1, column=c).font = encabezado_font

    for r in (datos["recomendaciones"] or datos["alertas"]):
        ws3.append([
            r.get("zone_id", ""),
            r.get("titulo") or r.get("tipo", ""),
            r.get("detalle") or r.get("mensaje", ""),
            r.get("accion", ""),
            r.get("prioridad", ""),
        ])
    ws3.column_dimensions["A"].width = 18
    ws3.column_dimensions["B"].width = 22
    ws3.column_dimensions["C"].width = 60
    ws3.column_dimensions["D"].width = 45
    for fila in ws3.iter_rows(min_row=2):
        fila[2].alignment = Alignment(wrap_text=True, vertical="top")
        fila[3].alignment = Alignment(wrap_text=True, vertical="top")

    # Hoja 4 — Heatmap
    if datos["heatmap"].exists():
        ws4 = wb.create_sheet("Mapa de calor")
        try:
            ws4.add_image(XLImage(str(datos["heatmap"])), "A1")
        except Exception:
            # openpyxl necesita Pillow para incrustar imágenes. Sin él, el
            # resto del libro debe generarse igual en vez de fallar entero.
            ws4["A1"] = "No se pudo incrustar el heatmap (falta Pillow)."

    wb.save(destino)
    return destino


# ── Word ────────────────────────────────────────────────────────────────────


def generar_word(outdir: Path | str, destino: Path | str | None = None) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    outdir = Path(outdir)
    destino = Path(destino) if destino else outdir / "reporte_gondhawk.docx"
    datos = _cargar(outdir)

    doc = Document()

    titulo = doc.add_heading("GondHawk — Análisis de góndola", level=0)
    for run in titulo.runs:
        run.font.color.rgb = RGBColor(0x26, 0x5F, 0xB5)

    p = doc.add_paragraph()
    run = p.add_run(f"Video: {Path(str(datos['video'])).name}  |  Generado: {datos['generado']}")
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    doc.add_heading("Indicadores principales", level=1)
    t = datos["total"]
    tabla = doc.add_table(rows=1, cols=2)
    tabla.style = "Light Grid Accent 1"
    tabla.rows[0].cells[0].text = "Indicador"
    tabla.rows[0].cells[1].text = "Valor"
    for nombre, valor in [
        ("Visitas", t.get("visitas", 0)),
        ("Se detiene", t.get("se_detiene", 0)),
        ("Toma producto", t.get("toma_producto", 0)),
        ("Devuelve", t.get("devuelve", 0)),
        ("Tasa de interacción", f"{t.get('tasa_interaccion', 0) * 100:.1f}%"),
        ("Tasa de rechazo", f"{t.get('tasa_rechazo', 0) * 100:.1f}%"),
    ]:
        fila = tabla.add_row().cells
        fila[0].text = str(nombre)
        fila[1].text = str(valor)

    if datos["heatmap"].exists():
        doc.add_heading("Mapa de calor de flujo", level=1)
        doc.add_picture(str(datos["heatmap"]), width=Inches(6.2))

    doc.add_heading("Embudo por góndola", level=1)
    encabezado = ["Zona", "Visitas", "Se detiene", "Toma", "Devuelve", "Interacción", "Estado"]
    tabla = doc.add_table(rows=1, cols=len(encabezado))
    tabla.style = "Light Grid Accent 1"
    for i, nombre in enumerate(encabezado):
        tabla.rows[0].cells[i].text = nombre
    for z in datos["zonas"]:
        e = z.get("embudo", {})
        fila = tabla.add_row().cells
        fila[0].text = str(z.get("zone_id", "—"))
        fila[1].text = str(e.get("visitas", 0))
        fila[2].text = str(e.get("se_detiene", 0))
        fila[3].text = str(e.get("toma_producto", 0))
        fila[4].text = str(e.get("devuelve", 0))
        fila[5].text = f"{z.get('tasa_interaccion', 0) * 100:.0f}%"
        fila[6].text = str(z.get("temperatura", "—"))

    recomendaciones = datos["recomendaciones"] or datos["alertas"]
    if recomendaciones:
        doc.add_heading("Recomendaciones", level=1)
        for r in recomendaciones:
            titulo_r = r.get("titulo") or r.get("tipo", "Observación")
            doc.add_heading(f"{r.get('zone_id', '')} — {titulo_r}", level=2)
            doc.add_paragraph(r.get("detalle") or r.get("mensaje", ""))
            if r.get("accion"):
                p = doc.add_paragraph()
                p.add_run("Acción sugerida: ").bold = True
                p.add_run(r["accion"])

    doc.add_page_break()
    doc.add_heading("Privacidad por diseño", level=1)
    p = doc.add_paragraph(
        "Este análisis no utiliza reconocimiento facial ni datos biométricos. No se "
        "almacenan imágenes de personas identificables: los rostros se difuminan antes "
        "de guardar cualquier fotograma. Los identificadores de seguimiento son "
        "temporales, anónimos y se descartan al terminar el análisis. Cumple la "
        "Ley 1581 de 2012 de protección de datos personales."
    )
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    doc.save(destino)
    return destino


GENERADORES = {"pdf": generar_pdf, "excel": generar_excel, "word": generar_word}
EXTENSIONES = {"pdf": ".pdf", "excel": ".xlsx", "word": ".docx"}


def generar(formato: str, outdir: Path | str, destino: Path | str | None = None) -> Path:
    formato = formato.lower()
    if formato not in GENERADORES:
        raise ValueError(f"Formato no soportado: {formato}. Usa: {sorted(GENERADORES)}")
    return GENERADORES[formato](outdir, destino)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Genera el reporte descargable del análisis")
    parser.add_argument("--outdir", default="pipeline/output", help="Carpeta con las salidas del pipeline")
    parser.add_argument("--formato", choices=["pdf", "excel", "word", "todos"], default="todos")
    parser.add_argument("--destino", default=None)
    args = parser.parse_args()

    formatos = ["pdf", "excel", "word"] if args.formato == "todos" else [args.formato]
    for formato in formatos:
        try:
            ruta = generar(formato, args.outdir, args.destino)
            print(f"[ok] {formato}: {ruta}")
        except ImportError as exc:
            print(f"[falta dependencia] {formato}: {exc}")


if __name__ == "__main__":
    main()
