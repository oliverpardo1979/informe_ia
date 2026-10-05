"""Genera el borrador PDF del informe CJC a partir de las salidas reproducibles."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "outputs" / "tables"
FIG_DIR = ROOT / "figures"
OUT_DIR = ROOT / "output" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT_DIR / "informe_ia_cjc_2025.pdf"

BLUE = HexColor("#173A63")
LIGHT_BLUE = HexColor("#EAF1F7")
GOLD = HexColor("#DDA63A")
TEXT = HexColor("#303A44")
MID = HexColor("#5A6570")
GRID = HexColor("#D8E0E8")
RED = HexColor("#BB443A")

DISPLAY_GROUP_LABELS = {
    "Not Exposed": "Muy baja o ninguna",
    "Minimal Exposure": "Muy baja o ninguna",
    "Gradient 1": "Baja",
    "Gradient 2": "Media",
    "Gradient 3": "Alta",
    "Gradient 4": "Muy alta",
    "Sin correspondencia 4d": "Sin correspondencia 4d",
}


def register_fonts() -> tuple[str, str]:
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("Arial", str(regular)))
        pdfmetrics.registerFont(TTFont("Arial-Bold", str(bold)))
        return "Arial", "Arial-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()


def read_csv(name: str) -> list[dict[str, str]]:
    with (TABLE_DIR / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fmt_num(value: str | float, decimals: int = 3) -> str:
    return f"{float(value):.{decimals}f}".replace(".", ",")


def fmt_pct(value: str | float, decimals: int = 1) -> str:
    return f"{100 * float(value):.{decimals}f}%".replace(".", ",")


def fmt_millions(value: str | float, decimals: int = 2) -> str:
    return f"{float(value) / 1_000_000:.{decimals}f}".replace(".", ",")


def exposure_label(value: str) -> str:
    return DISPLAY_GROUP_LABELS.get(value, value)


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        "BodyCJC",
        parent=styles["BodyText"],
        fontName=FONT,
        fontSize=9.4,
        leading=13.2,
        textColor=TEXT,
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        "SmallCJC",
        parent=styles["BodyText"],
        fontName=FONT,
        fontSize=7.6,
        leading=10.2,
        textColor=TEXT,
    )
)
styles.add(
    ParagraphStyle(
        "TinyCJC",
        parent=styles["BodyText"],
        fontName=FONT,
        fontSize=6.5,
        leading=8.0,
        textColor=TEXT,
    )
)
styles.add(
    ParagraphStyle(
        "H1CJC",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=17,
        leading=20,
        textColor=BLUE,
        spaceBefore=8,
        spaceAfter=8,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        "H2CJC",
        parent=styles["Heading2"],
        fontName=FONT_BOLD,
        fontSize=12,
        leading=15,
        textColor=BLUE,
        spaceBefore=7,
        spaceAfter=5,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        "CaptionCJC",
        parent=styles["BodyText"],
        fontName=FONT,
        fontSize=7.2,
        leading=9.2,
        textColor=MID,
        alignment=TA_CENTER,
        spaceBefore=3,
        spaceAfter=7,
    )
)
styles.add(
    ParagraphStyle(
        "SmallCJCHeader",
        parent=styles["SmallCJC"],
        fontName=FONT_BOLD,
        textColor=colors.white,
    )
)
styles.add(
    ParagraphStyle(
        "TinyCJCHeader",
        parent=styles["TinyCJC"],
        fontName=FONT_BOLD,
        textColor=colors.white,
    )
)
styles.add(
    ParagraphStyle(
        "BulletCJC",
        parent=styles["BodyCJC"],
        leftIndent=13,
        firstLineIndent=-8,
        bulletIndent=2,
        spaceAfter=3,
    )
)


def P(text: str, style: str = "BodyCJC") -> Paragraph:
    return Paragraph(text, styles[style])


def section(title: str) -> list:
    heading = Paragraph(title, styles["H1CJC"])
    rule = HRFlowable(width="100%", thickness=1, color=GOLD)
    gap = Spacer(1, 4)
    # Encadenar el encabezado con el primer elemento de la sección evita
    # títulos huérfanos al final de una página.
    heading.keepWithNext = True
    rule.keepWithNext = True
    gap.keepWithNext = True
    return [heading, rule, gap]


def subsection(title: str) -> Paragraph:
    return Paragraph(title, styles["H2CJC"])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"• {text}", styles["BulletCJC"])


def report_table(data: list[list], widths: list[float], header_rows: int = 1, tiny: bool = False) -> Table:
    style_name = "TinyCJC" if tiny else "SmallCJC"
    header_style_name = "TinyCJCHeader" if tiny else "SmallCJCHeader"
    cooked = []
    for row_idx, row in enumerate(data):
        row_style = header_style_name if row_idx < header_rows else style_name
        cooked.append([
            cell if hasattr(cell, "wrap") else Paragraph(str(cell), styles[row_style])
            for cell in row
        ])
    table = LongTable(cooked, colWidths=widths, repeatRows=header_rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
                ("FONTNAME", (0, 0), (-1, header_rows - 1), FONT_BOLD),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, HexColor("#F6F8FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def chart(filename: str, max_width: float = 6.90 * inch, max_height: float = 7.55 * inch) -> Image:
    path = FIG_DIR / filename
    with PILImage.open(path) as im:
        width_px, height_px = im.size
    ratio = min(max_width / width_px, max_height / height_px)
    image = Image(str(path), width=width_px * ratio, height=height_px * ratio)
    image.hAlign = "CENTER"
    return image


def add_chart(story: list, filename: str, caption: str, max_height: float = 7.55 * inch) -> None:
    story.append(chart(filename, max_height=max_height))
    story.append(P(caption, "CaptionCJC"))


def header_footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 28, width - doc.rightMargin, 28)
    canvas.setFont(FONT_BOLD, 7.5)
    canvas.setFillColor(BLUE)
    canvas.drawString(doc.leftMargin, 17, "CENTRO JAVERIANO DE COMPETITIVIDAD")
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MID)
    canvas.drawRightString(width - doc.rightMargin, 17, f"IA y empleo en Colombia | {doc.page}")
    if doc.page > 1:
        canvas.line(doc.leftMargin, height - 28, width - doc.rightMargin, height - 28)
        canvas.setFont(FONT, 7.2)
        canvas.drawString(doc.leftMargin, height - 20, "Borrador técnico - julio de 2026")
    canvas.restoreState()


def build_story() -> list:
    national = read_csv("01_resumen_nacional.csv")[0]
    groups = read_csv("02_grupos_exposicion.csv")
    quintiles = read_csv("03_quintiles_ingreso_mensual.csv")
    departments = read_csv("05_departamentos_24.csv")
    sectors = read_csv("06_actividad_economica.csv")
    education = read_csv("07_logro_educativo.csv")
    sex = read_csv("08_sexo.csv")
    formality = read_csv("09_formalidad.csv")
    occupations = read_csv("11_ocupaciones_alta_exposicion_empleo.csv")[:12]
    sensitivity = read_csv("13_sensibilidad_2d.csv")
    aioe_national = read_csv("14_aioe_caioe_resumen_nacional.csv")[0]
    quadrants = read_csv("15_cuadrantes_exposicion_complementariedad.csv")
    substitution_risk = read_csv("16_ocupaciones_riesgo_sustitucion_empleo.csv")[:10]
    high_complementarity = read_csv("17_ocupaciones_alta_complementariedad_empleo.csv")[:10]

    story: list = []

    story.extend([Spacer(1, 0.55 * inch), P("CENTRO JAVERIANO DE COMPETITIVIDAD", "H2CJC"), Spacer(1, 0.55 * inch)])
    story.append(Paragraph("Inteligencia artificial y empleo en Colombia", ParagraphStyle(
        "CoverTitle", fontName=FONT_BOLD, fontSize=28, leading=32, textColor=BLUE, alignment=TA_LEFT, spaceAfter=9
    )))
    story.append(Paragraph("Exposición ocupacional en 2025", ParagraphStyle(
        "CoverSub", fontName=FONT, fontSize=17, leading=21, textColor=TEXT, spaceAfter=18
    )))
    story.append(HRFlowable(width="100%", thickness=4, color=GOLD))
    story.append(Spacer(1, 0.35 * inch))
    metric_data = [[
        P("<b>0,264</b><br/><font size='7'>puntaje promedio con cruce exacto</font>", "BodyCJC"),
        P("<b>25,4%</b><br/><font size='7'>del empleo entre baja y muy alta exposición</font>", "BodyCJC"),
        P("<b>8,0%</b><br/><font size='7'>del empleo con exposición alta o muy alta</font>", "BodyCJC"),
        P("<b>96,5%</b><br/><font size='7'>cobertura exacta a cuatro dígitos</font>", "BodyCJC"),
    ]]
    metrics = Table(metric_data, colWidths=[1.72 * inch] * 4)
    metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE), ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    story.append(metrics)
    story.append(Spacer(1, 0.35 * inch))
    story.append(P("<b>Borrador técnico.</b> Resultados provisionales para los 22,96 millones de ocupados expandidos que conserva la versión disponible de BaseIA.dta. Antes de publicar se debe reconstruir el universo completo y recuperar la educación detallada.", "BodyCJC"))
    story.append(Spacer(1, 1.55 * inch))
    story.append(P("Julio de 2026", "H2CJC"))
    story.append(PageBreak())

    story.extend(section("Resumen ejecutivo"))
    summaries = [
        ("El puntaje resume la exposición de las tareas.", "El indicador de la OIT asigna a cada tarea un valor entre 0 y 1. El puntaje de una ocupación es el promedio de esos valores. No es un porcentaje de trabajadores expuestos ni predice pérdida de empleo: el efecto depende de si la IA sustituye o complementa esas tareas."),
        ("Una cuarta parte del empleo presenta exposición sustantiva.", "El 25,4% se ubica entre baja y muy alta exposición; el 8,0% tiene exposición alta o muy alta. Oficinistas, contadores, centros de llamadas, auxiliares contables, secretarios y desarrolladores concentran una parte importante."),
        ("La exposición aumenta con ingreso y educación.", "El puntaje promedio pasa de 0,211 en el primer quintil a 0,358 en el quinto. Es mayor entre mujeres que hombres y entre formales que informales. Esto describe tareas, no vulnerabilidad económica total."),
        ("Los resultados observados son mixtos.", "Experimentos encuentran más productividad en centros de atención, consultoría, escritura y software; otra evidencia muestra caídas de empleo e ingresos en trabajo independiente expuesto. El resultado depende de la organización del trabajo."),
        ("La respuesta debe enfocarse en transiciones.", "Empresas, trabajadores y Gobierno deben capacitar, experimentar con métricas de calidad, mantener revisión humana y proteger ingresos durante cambios ocupacionales."),
    ]
    for lead, body in summaries:
        story.append(P(f"<b>{lead}</b> {body}"))

    story.extend(section("1. Qué mide la OIT"))
    story.append(P("La actualización de 2025 de la OIT y NASK parte de 2.541 ocupaciones y 29.753 tareas de una clasificación polaca detallada. Una encuesta a 1.640 trabajadores produjo 52.558 evaluaciones sobre 2.861 tareas representativas. El equipo combinó revisión experta, un proceso Delphi y un asistente de clasificación para puntuar 3.265 tareas CIUO-08."))
    story.append(P("Cada tarea recibe un valor entre 0 -la IA no puede realizarla- y 1 -puede realizarla completamente sin intervención humana bajo la capacidad considerada-. El puntaje de exposición de una ocupación es el promedio no ponderado de los puntajes de sus tareas. La unidad de partida es la tarea, no el trabajador ni la ocupación completa."))
    story.append(P("Al cruzar el indicador con la GEIH, cada ocupado recibe el puntaje de su ocupación a cuatro dígitos. Por eso, un promedio de 0,358 en el quinto quintil de ingreso no significa que 35,8% de sus trabajadores esté expuesto; significa que las ocupaciones de ese quintil tienen, en promedio, tareas más expuestas a IA generativa."))
    thresholds = [
        ["Etiqueta del informe", "Regla OIT"],
        ["Muy alta", "Gradiente 4: media >= 0,60 y media - desviación >= 0,50"],
        ["Alta", "Gradiente 3: 0,50 <= media < 0,60 y media + desviación >= 0,50"],
        ["Media", "Gradiente 2: 0,40 <= media < 0,50 y media + desviación >= 0,50"],
        ["Baja", "Gradiente 1: media < 0,40 y media + desviación >= 0,50"],
        ["Muy baja o ninguna", "Exposición mínima: no clasificada antes, media < 0,50 y media + desviación > 0,40; no expuesta: casos restantes"],
    ]
    story.append(report_table(thresholds, [1.25 * inch, 5.7 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("<b>Precauciones.</b> La escala del informe reemplaza los nombres técnicos de la OIT por cinco rótulos. La categoría muy baja o ninguna agrupa los casos sin exposición y los de exposición mínima. Las tareas no se ponderan por frecuencia ni importancia; el indicador mide potencial técnico, no efectos causales sobre empleo, salarios o calidad del trabajo."))

    story.append(subsection("Aplicación a la GEIH"))
    story.append(P("El indicador principal enlaza OFICIO_C8 con la CIUO-08 exactamente a cuatro dígitos. La cobertura es 96,49%. El 3,51% sin correspondencia se conserva como categoría aparte. Una imputación a dos dígitos se usa sólo como sensibilidad porque puede ocultar diferencias entre ocupaciones colombianas."))
    sens_data = [["Método", "Cobertura", "Puntaje promedio"]] + [[r["metodo"], fmt_pct(r["cobertura"], 2), fmt_num(r["exposicion_promedio"])] for r in sensitivity]
    story.append(report_table(sens_data, [4.5 * inch, 1.15 * inch, 1.15 * inch]))
    story.append(P("El ingreso mensual equivalente multiplica el ingreso real por hora por horas semanales y por 52/12. Los cuantiles se ponderan y no separan empates; por eso la tabla de percentiles conserva 68 posiciones con masa positiva."))

    story.extend(section("2. Resultados nacionales"))
    add_chart(story, "fig_01_distribucion_exposicion.png", "Figura 1. Distribución del empleo por exposición. Fuente: GEIH 2025 e índice OIT-NASK.", 5.0 * inch)
    group_data = [["Grupo", "Ocupados (millones)", "Participación"]] + [[r["grupo_exposicion_es"], fmt_millions(r["ocupados"]), fmt_pct(r["participacion"])] for r in groups]
    story.append(report_table(group_data, [3.5 * inch, 1.75 * inch, 1.45 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("El 71,1% del empleo se clasifica como muy baja o ninguna exposición. La exposición baja y media reúne 17,4%; la exposición alta o muy alta, 8,0%. Esto no significa que 25,4% de los puestos desaparecerá: indica que contienen tareas con potencial técnico de apoyo o automatización."))

    story.append(PageBreak())
    story.extend(section("3. Ingreso, educación y perfiles"))
    add_chart(story, "fig_02_quintiles_ingreso.png", "Figura 2. Puntaje promedio de exposición por quintil de ingreso laboral mensual equivalente.", 4.0 * inch)
    quint_data = [["Quintil", "Puntaje", "Mediana mensual (millones)", "Participación muestra"]] + [[r["quintil_ingreso"], fmt_num(r["exposicion_promedio_4d"]), fmt_millions(r["ingreso_mediana_ponderada"]), fmt_pct(r["participacion_muestra_ingreso"])] for r in quintiles]
    story.append(report_table(quint_data, [1.1 * inch, 1.1 * inch, 2.6 * inch, 1.8 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("La figura muestra el promedio ponderado del puntaje ocupacional de exposición, no el porcentaje de trabajadores expuestos. El puntaje es similar en los dos quintiles inferiores y aumenta con fuerza desde el tercero. La relación es descriptiva: las ocupaciones mejor remuneradas concentran más tareas cognitivas y de oficina que la IA generativa puede ejecutar."))
    story.append(PageBreak())
    add_chart(story, "fig_03_percentiles_ingreso.png", "Figura 3. Puntaje promedio de exposición a lo largo de la distribución ponderada de ingreso.", 5.5 * inch)
    story.append(P("La línea no contiene cien puntos porque los empates de ingreso -muy frecuentes alrededor de valores redondos y el salario mínimo- permanecen juntos. Dividirlos al azar produciría percentiles de tamaño idéntico, pero una precisión ficticia."))
    story.append(PageBreak())
    add_chart(story, "fig_06_logro_educativo.png", "Figura 4. Puntaje promedio de exposición por logro educativo disponible.", 4.3 * inch)
    edu_data = [["Educación", "Puntaje", "Cobertura"]] + [[r["educacion"], fmt_num(r["exposicion_promedio_4d"]), fmt_pct(r["cobertura_4d"])] for r in education]
    story.append(report_table(edu_data, [4.2 * inch, 1.2 * inch, 1.2 * inch]))
    story.append(Spacer(1, 4))
    story.append(P("La base disponible sólo conserva seis grupos. No permite separar técnica profesional, tecnológica, universitaria, especialización, maestría y doctorado. Ese cruce requiere recuperar P3042 antes de cerrar el informe."))
    story.append(PageBreak())
    add_chart(story, "fig_07_genero.png", "Figura 5. Puntaje promedio de exposición por género.", 2.8 * inch)
    gender_data = [["Género", "Puntaje", "Alta o muy alta", "Cobertura"]] + [
        [
            r["sexo"],
            fmt_num(r["exposicion_promedio_4d"]),
            fmt_pct(r["participacion_alta_g3_g4"]),
            fmt_pct(r["cobertura_4d"]),
        ]
        for r in sorted(sex, key=lambda row: 0 if row["sexo"] == "Mujer" else 1)
    ]
    story.append(report_table(gender_data, [2.2 * inch, 1.15 * inch, 1.65 * inch, 1.35 * inch]))
    story.append(P("Las mujeres registran mayor exposición que los hombres: 0,297 frente a 0,240. La exposición alta o muy alta también es mayor entre mujeres, con 12,2% del empleo femenino frente a 5,1% del masculino. La comparación describe composición ocupacional; no mide pérdidas esperadas de empleo ni vulnerabilidad económica total."))
    story.append(subsection("Formalidad"))
    formality_data = [["Formalidad", "Puntaje", "Cobertura"]] + [[r["formalidad"], fmt_num(r["exposicion_promedio_4d"]), fmt_pct(r["cobertura_4d"])] for r in formality]
    story.append(report_table(formality_data, [4.2 * inch, 1.2 * inch, 1.2 * inch]))
    story.append(P("Los ocupados formales también presentan mayor exposición directa. Menor exposición informal no significa menor vulnerabilidad: los informales suelen tener menos protección frente a choques indirectos y transiciones."))

    story.extend(section("4. Geografía y actividad económica"))
    add_chart(story, "fig_04_departamentos.png", "Figura 6. Puntaje promedio de exposición en los 24 departamentos seleccionados.", 7.25 * inch)
    story.append(P("Bogotá encabeza con 0,319, seguida por Antioquia, Atlántico y Valle del Cauca. Huila, Cauca y Nariño tienen los promedios más bajos. La Guajira requiere cautela: la cobertura exacta es 80,0%, por debajo del resto."))
    story.append(PageBreak())
    add_chart(story, "fig_05_actividad_economica.png", "Figura 7. Puntaje promedio de exposición por actividad económica.", 6.8 * inch)
    story.append(P("Finanzas y seguros (0,478) e información y comunicaciones (0,455) encabezan. Agricultura (0,141), hogares empleadores (0,153) y construcción (0,160) están abajo. El puntaje no captura robótica, plataformas ni analítica, por lo que menor exposición generativa no significa inmunidad tecnológica."))

    story.extend(section("5. Ocupaciones prioritarias"))
    add_chart(story, "fig_08_ocupaciones_alta_exposicion.png", "Figura 8. Ocupaciones de exposición alta o muy alta con mayor empleo.", 6.5 * inch)
    occ_data = [["Código", "Ocupación", "Grupo", "Ocupados"]] + [[r["oficio_c8_4d"], r["oficio_c8_label"], r.get("grupo_exposicion_es") or exposure_label(r["grupo_exposicion_4d"]), f"{float(r['ocupados']):,.0f}".replace(",", ".")] for r in occupations]
    story.append(report_table(occ_data, [0.65 * inch, 3.7 * inch, 1.1 * inch, 1.15 * inch], tiny=True))
    story.append(P("Los perfiles son prioritarios para adopción responsable y formación, no porque su desplazamiento sea inevitable, sino porque una proporción grande de sus tareas puede cambiar pronto."))

    story.extend(section("6. Tareas y evidencia documentada"))
    story.append(P("La tabla combina tareas OIT con evidencia empírica. Cuando un estudio no corresponde exactamente a la ocupación colombiana, se identifica la conexión como evidencia relacionada o inferencia."))
    evidence = [
        ["Ocupación", "Tareas expuestas", "Resultado documentado", "Lectura"],
        ["Centros de llamadas", "Enviar documentos, registrar requerimientos, pagos, llamadas y reclamos.", "Un asistente elevó 15% los casos resueltos por hora y cerca de 30% la productividad de agentes menos experimentados.", "Directa: productividad positiva; empleo final incierto."],
        ["Desarrolladores", "Código, documentación, revisión y pruebas.", "En 4.867 desarrolladores, la herramienta elevó 26,1% las tareas completadas; mayores ganancias entre menos experimentados.", "Directa: productividad positiva; empleo no medido."],
        ["Analistas y consultores", "Informes, pronósticos, datos y recomendaciones.", "Dentro de la frontera de IA: 12,2% más tareas y 25,1% más rápido. Fuera de ella: 19% menos probabilidad de acertar.", "Cercana: efecto mixto; verificar es decisivo."],
        ["Traductores y escritura", "Revisar, corregir, traducir y usar herramientas.", "En escritura: 40% menos tiempo y 18% más calidad. En una plataforma, el trabajo independiente expuesto perdió empleo e ingresos.", "Relacionada: productividad y demanda negativa pueden coexistir."],
        ["Auxiliares contables", "Facturas, estados, software contable, informes y registros.", "La IA puede acelerar clasificación y conciliación; no hay en estas fuentes una estimación causal específica para Colombia.", "Inferencia: resultado incierto; alto rediseño."],
        ["Secretarios y datos", "Reuniones, correspondencia, transcripción, hojas de cálculo y archivos.", "Un experimento empresarial encontró dos horas menos de correo por semana, sin cambio detectado en cantidad o composición de tareas.", "Relacionada: ahorro de tiempo; empleo incierto."],
    ]
    story.append(report_table(evidence, [1.05 * inch, 1.45 * inch, 3.25 * inch, 1.15 * inch], tiny=True))
    story.append(Spacer(1, 5))
    story.append(P("La unidad pertinente es la tarea. La IA puede automatizar el primer borrador o el registro y dejar al trabajador la validación, el trato con clientes, la responsabilidad y las excepciones. Si la firma usa el ahorro para expandir producción, el empleo puede sostenerse; si la demanda es fija, puede reducir horas o contratación."))

    story.extend(section("7. Por qué no se asigna un signo por ocupación"))
    story.append(P("<b>No es viable clasificar las 427 ocupaciones como positivas o negativas usando la correlativa OIT.</b> El indicador no contiene elasticidad de demanda, costos de adopción, decisiones empresariales, regulación, calidad, salarios ni reasignación. Un signo convertiría supuestos del analista en un dato aparentemente observado."))
    layers = [
        ["Capa", "Contenido", "Cobertura recomendada"],
        ["1. Exposición tecnológica", "Puntaje OIT y etiqueta de exposición", "Todas las ocupaciones"],
        ["2. Evidencia de resultados", "Productividad, calidad, horas, empleo e ingresos", "Sólo con estudio pertinente"],
        ["3. Confianza", "Directa, cercana o baja según ocupación y contexto", "Cada evidencia"],
    ]
    story.append(report_table(layers, [1.55 * inch, 3.6 * inch, 1.7 * inch]))
    story.append(P("Con esta regla, la mayoría de ocupaciones conserva resultado incierto hasta contar con evidencia. Es una conclusión útil: orienta pilotos y evita presentar como pronóstico lo que hoy es posibilidad tecnológica."))

    story.extend(section("8. Recomendaciones"))
    story.append(subsection("Firmas"))
    for item in [
        "Mapear tareas en puestos de exposición alta y muy alta, empezando por oficina, contabilidad, centros de llamadas, secretarías y software.",
        "Hacer pilotos con tiempo, calidad, errores, satisfacción y carga de trabajo; no medir éxito sólo por costo.",
        "Capacitar antes y durante el rediseño, con guías, datos confiables y supervisión.",
        "Mantener revisión humana en decisiones legales, financieras, laborales y de atención sensible.",
        "Compartir ganancias de productividad mediante formación, mejores tareas, progresión o compensación.",
    ]:
        story.append(bullet(item))
    story.append(subsection("Trabajadores"))
    for item in [
        "Aprender a formular instrucciones, verificar fuentes, detectar errores y documentar decisiones asistidas.",
        "Fortalecer criterio profesional, conocimiento del negocio, negociación, comunicación, cuidado y coordinación.",
        "Acumular credenciales portables y evidencia de proyectos ligados a tareas del oficio.",
        "Anticipar transiciones hacia calidad, relación con clientes, excepciones y supervisión de sistemas.",
    ]:
        story.append(bullet(item))
    story.append(subsection("Gobierno"))
    for item in [
        "Priorizar formación modular del SENA y alianzas sectoriales, cruzando exposición con informalidad, ingreso, edad y capacidad de transición.",
        "Cofinanciar adopción y capacitación en mipymes para evitar que el costo fijo amplíe brechas.",
        "Fortalecer intermediación, certificación y protección de ingresos durante transiciones.",
        "Medir uso efectivo, tareas, vacantes, salarios, horas y calidad del empleo; la exposición no sustituye estos indicadores.",
        "Definir protección de datos, no discriminación, transparencia y responsabilidad en usos laborales de IA.",
    ]:
        story.append(bullet(item))

    story.extend(section("9. Limitaciones y cierre pendiente"))
    limitations = [
        ["Pendiente", "Implicación y acción"],
        ["Universo", "BaseIA suma 22,96 millones, 872 mil menos que el promedio oficial. Reconstruir desde el archivo completo de ocupados y documentar exclusiones."],
        ["Educación", "Recuperar P3042 para separar los doce niveles, de preescolar a doctorado."],
        ["Cruce", "Revisar manualmente códigos colombianos sin equivalencia; no imputar silenciosamente a dos dígitos."],
        ["Causalidad", "El indicador no incorpora adopción, inversión complementaria ni demanda. Es línea base, no pronóstico."],
        ["Muestra", "Agregar errores estándar con el diseño GEIH, especialmente en departamentos y ocupaciones pequeñas."],
    ]
    story.append(report_table(limitations, [1.25 * inch, 5.55 * inch]))
    story.append(Spacer(1, 6))
    story.append(P("<b>Reproducibilidad.</b> code/01_analisis_exposicion_ia_2025.py genera las 17 tablas, las 13 figuras y las pruebas de calidad, incluyendo el cruce con AIOE/CAIOE. Ningún resultado principal usa imputación a dos dígitos ni la variante alternativa de CAIOE."))

    story.extend(section("10. Exposición y complementariedad potencial (AIOE/CAIOE)"))
    story.append(P("El AI Occupational Exposure (AIOE), propuesto por Felten, Raj y Seamans (2021), mide la exposición de cada ocupación a la inteligencia artificial combinando dos insumos: un mapa de similitud entre aplicaciones de IA (reconocimiento de imágenes, traducción automática, transcripción de voz, generación de texto, entre otras) y las habilidades laborales detalladas de O*NET, y la puntuación de importancia que O*NET asigna a cada habilidad dentro de cada ocupación. El resultado es un puntaje continuo, sin cota superior, que ordena ocupaciones según qué tan relacionadas están sus habilidades más importantes con las capacidades demostradas por la IA. A diferencia del índice OIT, que evalúa tareas frente a la IA generativa actual, AIOE captura un conjunto más amplio y anterior de capacidades tecnológicas (por ejemplo, visión por computador y reconocimiento de patrones)."))
    story.append(P("Pizzinelli et al. extienden AIOE con un parámetro de complementariedad potencial, theta, que resume qué tan sustituibles o complementarias son las tareas de una ocupación frente a la IA: un theta más alto indica que la IA tiende a acompañar el trabajo humano en esas tareas en lugar de reemplazarlo. Theta resume seis atributos ocupacionales -comunicación, responsabilidad, exigencia física, criticidad de los errores, contenido rutinario y nivel de habilidades-, de los cuales la criticidad de los errores y la comunicación muestran la asociación más alta con la complementariedad potencial. A partir de theta construyen el Complementarity-Adjusted AIOE (CAIOE), que ajusta el AIOE por esa complementariedad; este informe usa la variante base de CAIOE como indicador principal y una variante alternativa como ejercicio de sensibilidad. Como el paper de Pizzinelli et al. está en revisión, la definición de estos indicadores puede ajustarse antes de su publicación; cualquier uso público de las cifras de esta sección debe citar tanto a Pizzinelli et al. como a Felten, Raj y Seamans (2021)."))
    story.append(P("Pizzinelli et al. clasifican cada ocupación en tres categorías según si su AIOE y su theta superan sendas medianas de referencia (exposición baja; exposición alta con complementariedad baja, mayor riesgo de sustitución; y exposición alta con complementariedad alta, mayor potencial de aumento). Este informe reproduce esa taxonomía sobre la distribución del empleo colombiano, calculando las medianas entre los ocupados con correspondencia en lugar de usar las medianas globales de referencia del archivo de trabajo (la reclasificación coincide con la taxonomía original en 84,9% de los casos). Para comparar grupos de población, el informe resume los dos cuadrantes de exposición alta en una razón entre la participación del empleo en el cuadrante de alta complementariedad y la del cuadrante de riesgo de sustitución: un valor superior a 1 indica que, entre los ocupados con alta exposición, predomina el perfil complementario. El cruce con la GEIH usa la misma correspondencia exacta a cuatro dígitos ISCO-08 que el índice OIT: el 100% de las 427 ocupaciones de la correlativa tiene AIOE/CAIOE, con una cobertura ponderada de 96,83% del empleo de 2025, muy similar al 96,49% del índice OIT."))
    national_data = [
        ["Indicador", "Valor"],
        ["Cobertura ponderada AIOE/CAIOE", fmt_pct(aioe_national["cobertura_aioe"], 2)],
        ["AIOE promedio", fmt_num(aioe_national["aioe_all_promedio"])],
        ["CAIOE promedio", fmt_num(aioe_national["caioe_promedio"])],
        ["Theta promedio (complementariedad)", fmt_num(aioe_national["theta_promedio"])],
        ["Correlación con índice OIT (Spearman, por ocupación)", fmt_num(aioe_national["correlacion_spearman_oit_aioe_all"], 2)],
    ]
    story.append(report_table(national_data, [4.5 * inch, 2.3 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("AIOE y el índice OIT están fuertemente correlacionados a nivel ocupación (correlación de Spearman de " + fmt_num(aioe_national["correlacion_spearman_oit_aioe_all"], 2) + "): ambos identifican como más expuestas a las ocupaciones de oficina, contabilidad y atención al cliente. La correlación con CAIOE es más moderada, reflejo de la dimensión de complementariedad que el índice OIT no mide."))
    add_chart(story, "fig_12_aioe_percentiles_ingreso.png", "Figura 9. AIOE promedio a lo largo de la distribución de ingreso laboral.", 4.3 * inch)
    story.append(P("El patrón es similar al del índice OIT, con más variación en la parte baja de la distribución: el AIOE promedio se mantiene entre 5,6 y 5,9 hasta cerca del percentil 65 y sube con claridad a partir de ese punto, hasta cerca de 6,4 en los percentiles más altos."))

    story.append(subsection("Cuadrantes de exposición y complementariedad"))
    add_chart(story, "fig_09_cuadrante_exposicion_complementariedad.png", "Figura 10. AIOE y complementariedad potencial por ocupación; el tamaño del punto es proporcional al empleo.", 5.0 * inch)
    quad_data = [["Cuadrante", "Ocupados (millones)", "Participación"]] + [[r["cuadrante"], fmt_millions(r["ocupados"]), fmt_pct(r["participacion"])] for r in quadrants]
    story.append(report_table(quad_data, [3.6 * inch, 1.75 * inch, 1.35 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("El cuadrante de alta exposición y baja complementariedad -mayor riesgo de sustitución- concentra cerca de una quinta parte del empleo. El cuadrante de alta exposición y alta complementariedad -mayor potencial de aumento- es el más grande entre los de alta exposición. Ninguno de los dos cuadrantes predice el resultado laboral: ambos describen composición de tareas, no un pronóstico de empleo."))

    story.append(subsection("Ocupaciones en cada cuadrante de alta exposición"))
    occ_compare = [["Riesgo de sustitución", "Alta complementariedad"]] + [
        [substitution_risk[i]["oficio_c8_label"], high_complementarity[i]["oficio_c8_label"]]
        for i in range(min(len(substitution_risk), len(high_complementarity)))
    ]
    story.append(report_table(occ_compare, [3.45 * inch, 3.45 * inch], tiny=True))
    story.append(Spacer(1, 5))
    story.append(P("Las ocupaciones de riesgo de sustitución están dominadas por tareas de punto de venta, oficina y registro contable: oficinistas generales, contadores, auxiliares de contabilidad y empleados de centros de llamadas encabezan también la lista de exposición alta o muy alta del índice OIT, mientras que vendedores en tiendas, vendedores ambulantes y especialistas en tratamientos de belleza tienen una exposición OIT baja o nula y sólo aparecen expuestos bajo AIOE, que además de tareas cognitivas recoge tareas de punto de venta e inventario sensibles a otras capacidades tecnológicas. Las ocupaciones de alta complementariedad combinan exposición tecnológica con responsabilidad, comunicación o atención directa a personas: guardias de seguridad, gerentes y representantes comerciales, conductores de carga, abogados, profesores, peluqueros y supervisores de oficina."))

    story.append(subsection("Actividad económica"))
    add_chart(story, "fig_10_riesgo_sustitucion_sector.png", "Figura 11. Participación del empleo en el cuadrante de riesgo de sustitución, por actividad económica.", 6.3 * inch)
    story.append(PageBreak())
    sector_quad = [["Actividad económica", "Alta complementariedad", "Riesgo de sustitución"]] + [
        [r["sector"], fmt_pct(r["participacion_cuadrante_alta_exposicion_alta_complementariedad"], 1), fmt_pct(r["participacion_cuadrante_alta_exposicion_baja_complementariedad"], 1)]
        for r in sorted(sectors, key=lambda row: float(row["participacion_cuadrante_alta_exposicion_alta_complementariedad"]) + float(row["participacion_cuadrante_alta_exposicion_baja_complementariedad"]), reverse=True)
    ]
    story.append(report_table(sector_quad, [3.9 * inch, 1.5 * inch, 1.5 * inch], tiny=True))
    story.append(Spacer(1, 5))
    story.append(P("Educación y organizaciones extraterritoriales tienen la mayor participación complementaria, muy por encima de su participación en riesgo de sustitución. Actividades financieras y de seguros es la única actividad donde el riesgo de sustitución supera a la complementariedad; comercio y reparación tiene el segundo mayor riesgo, con una complementariedad considerablemente menor. Agricultura y hogares como empleadores tienen la menor participación en ambos cuadrantes, reflejo de su baja exposición general."))

    story.extend(section("11. Heterogeneidad de la complementariedad potencial"))
    story.append(P("La razón entre complementariedad y riesgo de sustitución es " + fmt_num(aioe_national["razon_complementariedad_sustitucion"], 2) + " a nivel nacional. Esta sección la desagrega por logro educativo, ingreso, departamento y género y formalidad."))
    education_reliable = [r for r in education if float(r["observaciones"]) >= 100]
    add_chart(story, "fig_11_razon_complementariedad_educacion.png", "Figura 12. Razón entre complementariedad y riesgo de sustitución por logro educativo (excluye preescolar, con 27 observaciones).", 3.4 * inch)
    story.append(P("La razón aumenta con el logro educativo: de " + fmt_num(education_reliable[0]["razon_complementariedad_sustitucion"], 2) + " entre quienes no tienen educación formal a " + fmt_num(education_reliable[-1]["razon_complementariedad_sustitucion"], 2) + " en educación superior o universitaria. La exposición de los ocupados sin educación formal se concentra más en el perfil de riesgo; en la educación superior, el empleo complementario casi duplica al de riesgo."))
    ratio_data = [["Grupo", "Razón complementariedad/riesgo"]] + [
        [f"Quintil de ingreso {r['quintil_ingreso']}", fmt_num(r["razon_complementariedad_sustitucion"], 2)] for r in quintiles
    ] + [
        [r["sexo"], fmt_num(r["razon_complementariedad_sustitucion"], 2)] for r in sorted(sex, key=lambda row: 0 if row["sexo"] == "Hombre" else 1)
    ] + [
        [r["formalidad"], fmt_num(r["razon_complementariedad_sustitucion"], 2)] for r in formality if r["formalidad"] in ("Formal", "Informal")
    ]
    story.append(report_table(ratio_data, [4.5 * inch, 2.3 * inch]))
    story.append(Spacer(1, 5))
    story.append(P("La razón crece de forma monótona con el ingreso: la participación en el cuadrante de riesgo es relativamente estable entre quintiles (16% a 23%), mientras que la de alta complementariedad crece con fuerza hacia el extremo superior de la distribución. Por género, la mayor exposición femenina que ya documentaba el índice OIT se concentra, según AIOE/CAIOE, más en el perfil de sustitución que en el de complementariedad (razón cercana a 1 entre mujeres frente a casi 2 entre hombres). Por formalidad, los informales reparten su exposición de forma casi equitativa entre complementariedad y riesgo, mientras que en el empleo formal predomina la complementariedad."))

    add_chart(story, "fig_13_razon_complementariedad_departamento.png", "Figura 13. Razón entre complementariedad y riesgo de sustitución por departamento.", 7.2 * inch)
    story.append(P("La razón supera 1 en los 24 departamentos analizados: varía entre " + fmt_num(min(float(r["razon_complementariedad_sustitucion"]) for r in departments), 2) + " en Quindío y " + fmt_num(max(float(r["razon_complementariedad_sustitucion"]) for r in departments), 2) + " en Caquetá. Bogotá, el departamento con mayor exposición según el índice OIT y AIOE, tiene una razón cercana a la mediana departamental. A diferencia de la educación, el ingreso, el género y la formalidad, la geografía no separa con claridad departamentos donde predomine el riesgo de sustitución."))
    story.append(P("Estos patrones describen, para 2025, en qué cuadrante de exposición y complementariedad se concentran hoy las tareas de cada grupo; no establecen una relación causal entre educación, ingreso, departamento, actividad económica, género o formalidad y el efecto final de la IA sobre el empleo, ni anticipan cómo evolucionará esa composición a medida que cambien la adopción tecnológica y la organización del trabajo."))

    story.extend(section("Referencias y fuentes"))
    refs = [
        ("OIT y NASK (2025)", "Generative AI and Jobs: A Refined Global Index of Occupational Exposure", "https://www.ilo.org/publications/generative-ai-and-jobs-refined-global-index-occupational-exposure"),
        ("Felten, Raj y Seamans (2021)", "Occupational, Industry, and Geographic Exposure to Artificial Intelligence: A Novel Dataset and Its Potential Uses", "https://doi.org/10.1002/smj.3286"),
        ("Pizzinelli y coautores (en revisión)", "AIOE/CAIOE: complementariedad potencial y exposición ocupacional. Documento de trabajo en revisión; cita por confirmar cuando se publique", ""),
        ("Brynjolfsson, Li y Raymond (2025)", "Generative AI at Work", "https://academic.oup.com/qje/article/140/2/889/7990658"),
        ("Dell'Acqua et al. (2026)", "Navigating the Jagged Technological Frontier", "https://pubsonline.informs.org/doi/10.1287/orsc.2025.21838"),
        ("Noy y Zhang (2023)", "Experimental Evidence on the Productivity Effects of Generative AI", "https://doi.org/10.1126/science.adh2586"),
        ("Dillon et al. (forthcoming)", "Shifting Work Patterns with Generative AI", "https://www.aeaweb.org/articles?id=10.1257/aeri.20250275"),
        ("Cui et al. (2026)", "The Effects of Generative AI on High-Skilled Work", "https://pubsonline.informs.org/doi/10.1287/mnsc.2025.00535"),
        ("Hui, Reshef y Zhou (2024)", "The Short-Term Effects of Generative AI on Employment", "https://pubsonline.informs.org/doi/10.1287/orsc.2023.18441"),
        ("DANE (2026)", "Mercado laboral, diciembre de 2025", "https://www.dane.gov.co/index.php/estadisticas-por-tema/mercado-laboral/empleo-y-desempleo"),
    ]
    for author, title, url in refs:
        title_html = f"<link href='{url}' color='#173A63'>{title}</link>" if url else title
        story.append(P(f"<b>{author}.</b> {title_html}.", "SmallCJC"))

    return story


def main() -> None:
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.48 * inch,
        bottomMargin=0.47 * inch,
        title="Inteligencia artificial y empleo en Colombia: exposición ocupacional en 2025",
        author="Centro Javeriano de Competitividad",
    )
    doc.build(build_story(), onFirstPage=header_footer, onLaterPages=header_footer)
    print(PDF_PATH)


if __name__ == "__main__":
    main()
