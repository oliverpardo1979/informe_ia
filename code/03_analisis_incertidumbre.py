"""Analisis descriptivo de la coincidencia entre los indices OIT-NASK y
AIOE/CAIOE para la poblacion ocupada en 2025.

Cada persona ocupada con correspondencia valida en los dos indices cae en
una de tres situaciones:

  - Ambos indices coinciden en que el potencial de automatizacion es alto.
  - Ambos indices coinciden en que es bajo.
  - Los indices no coinciden (incertidumbre): el residuo de las dos
    categorias anteriores.

Regla de corte: un indice es "alto" para una ocupacion cuando su puntaje es
igual o superior a la mediana de ese indice entre las ocupaciones (CIUO-08 a
4 digitos) con puntaje en ambos indices; cada ocupacion pesa igual.

Las figuras muestran solo las dos categorias de coincidencia; el residuo
hasta 100% corresponde a la incertidumbre. Las tablas conservan tambien la
participacion de la incertidumbre y el detalle de la discrepancia.

Este script reutiliza la carga de datos y clasificacion de
``01_analisis_exposicion_ia_2025.py`` (mismo insumo, misma metodologia).
Usa las mismas rutas de insumos: ``BASE_IA_PATH``, ``IA_CROSSWALK_PATH``,
``CJC_MONITOR_ROOT``.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_MODULE_PATH = SCRIPT_DIR / "01_analisis_exposicion_ia_2025.py"

_spec = importlib.util.spec_from_file_location("ia_report_base", BASE_MODULE_PATH)
base = importlib.util.module_from_spec(_spec)
sys.modules["ia_report_base"] = base
_spec.loader.exec_module(base)

TABLE_DIR = base.TABLE_DIR
FIG_DIR = base.FIG_DIR

ALTA_COLOR = base.BLUE
BAJA_COLOR = "#8FB3D9"
TRACK_COLOR = "#EDF0F3"
INCIERTO_COLOR = base.QUADRANT_COLORS[base.QUADRANT_ALTA_SUSTITUYE]

ALTA_LABEL = "Alto potencial de automatización"
BAJA_LABEL = "Bajo potencial de automatización"
INCIERTO_LABEL = "Potencial incierto"
SENSITIVITY_PERCENTILES = [30, 40, 50, 60, 70]  # corte comun a ambos indices
RESIDUAL_NOTE = "El resto hasta 100% es empleo donde los índices no coinciden."

SOURCE = (
    "Fuente: cálculos propios con GEIH 2025 del DANE, índice OIT-NASK (2025) y "
    "AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión)."
)


def occupation_table(data: pd.DataFrame) -> pd.DataFrame:
    """Una fila por ocupacion (CIUO-08 4d) con puntaje en ambos indices."""
    both = data[data["has_both_indices"]]
    return both.groupby(["oficio_c8_4d", "oficio_c8_label"], dropna=False, as_index=False).agg(
        oit=("ai_exposure_mean", "first"), aioe=("ai_aioe_all", "first")
    )


def occupation_medians(data: pd.DataFrame) -> tuple[float, float]:
    """Medianas de OIT-NASK y AIOE entre ocupaciones (cada una pesa igual)."""
    occupations = occupation_table(data)
    return float(occupations["oit"].median()), float(occupations["aioe"].median())


def flag_uncertainty(data: pd.DataFrame) -> pd.DataFrame:
    """Agrega al dataframe de personas las banderas de coincidencia.

    ``is_oit_alta``/``is_aioe_alta`` solo son validas cuando
    ``has_both_indices`` es verdadero; en el resto de casos la persona no
    tiene correspondencia en uno de los dos indices y se excluye de las
    comparaciones (igual que en la herramienta interactiva del Informe 3).
    """
    out = data.copy()
    has_oit = out["grupo_exposicion_4d"] != "Sin correspondencia 4d"
    has_aioe = out["cuadrante_aioe_caioe"] != base.QUADRANT_SIN_AIOE
    out["has_both_indices"] = has_oit & has_aioe
    corte_oit, corte_aioe = occupation_medians(out)
    out["corte_oit"] = corte_oit
    out["corte_aioe"] = corte_aioe
    is_oit_alta = out["ai_exposure_mean"] >= corte_oit
    is_aioe_alta = out["ai_aioe_all"] >= corte_aioe
    out["is_oit_alta"] = is_oit_alta
    out["is_aioe_alta"] = is_aioe_alta
    out["es_incierto"] = out["has_both_indices"] & (is_oit_alta != is_aioe_alta)
    return out


def _shares(both: pd.DataFrame) -> dict[str, float]:
    total_both = both["fex"].sum()
    return {
        "ocupados_con_ambos_indices": total_both,
        "observaciones_con_ambos_indices": len(both),
        "participacion_ambos_alta": both.loc[
            both["is_oit_alta"] & both["is_aioe_alta"], "fex"
        ].sum()
        / total_both,
        "participacion_ambos_baja": both.loc[
            ~both["is_oit_alta"] & ~both["is_aioe_alta"], "fex"
        ].sum()
        / total_both,
        "participacion_incertidumbre": both.loc[both["es_incierto"], "fex"].sum() / total_both,
        "participacion_solo_aioe_alta": both.loc[
            ~both["is_oit_alta"] & both["is_aioe_alta"], "fex"
        ].sum()
        / total_both,
        "participacion_solo_oit_alta": both.loc[
            both["is_oit_alta"] & ~both["is_aioe_alta"], "fex"
        ].sum()
        / total_both,
    }


def summarize_uncertainty(data: pd.DataFrame, group: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for value, part in data.groupby(group, dropna=False, sort=False):
        both = part[part["has_both_indices"]]
        if both["fex"].sum() <= 0:
            continue
        row: dict[str, object] = {group: value, "ocupados": part["fex"].sum()}
        row.update(_shares(both))
        row["participacion_coincide"] = row["participacion_ambos_alta"] + row["participacion_ambos_baja"]
        rows.append(row)
    return pd.DataFrame(rows)


def national_uncertainty_row(data: pd.DataFrame) -> pd.DataFrame:
    both = data[data["has_both_indices"]]
    row: dict[str, object] = {
        "anio": base.YEAR,
        "ocupados": data["fex"].sum(),
        "cobertura_ambos_indices": both["fex"].sum() / data["fex"].sum(),
    }
    row.update(_shares(both))
    row["participacion_coincide"] = row["participacion_ambos_alta"] + row["participacion_ambos_baja"]
    return pd.DataFrame([row])


def build_tables(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}

    tables["21_incertidumbre_nacional"] = national_uncertainty_row(data)

    sex_table = summarize_uncertainty(data, "sexo")
    sex_table["sexo"] = pd.Categorical(sex_table["sexo"], categories=["Mujer", "Hombre"], ordered=True)
    tables["22_incertidumbre_sexo"] = sex_table.sort_values("sexo")

    formality_table = summarize_uncertainty(data, "formalidad")
    tables["23_incertidumbre_formalidad"] = formality_table.sort_values(
        "participacion_incertidumbre", ascending=False
    )

    education_table = summarize_uncertainty(data, "educacion")
    education_order = data[["educ_hom_cod", "educacion"]].drop_duplicates().set_index("educacion")
    education_table["educ_hom_cod"] = education_table["educacion"].map(education_order["educ_hom_cod"])
    tables["24_incertidumbre_logro_educativo"] = education_table.sort_values("educ_hom_cod")

    sector_table = summarize_uncertainty(data, "sector")
    tables["25_incertidumbre_actividad_economica"] = sector_table.sort_values(
        "participacion_ambos_alta", ascending=False
    )

    income = data[
        data["ingreso_hora_real"].gt(0) & data["horas"].between(1, 112) & data["fex"].gt(0)
    ].copy()
    income["ingreso_laboral_mensual_2025"] = (
        income["ingreso_hora_real"] * income["horas"] * base.MONTHS_PER_WEEK
    )
    income["quintil_ingreso"] = base.assign_weighted_bins(
        income["ingreso_laboral_mensual_2025"], income["fex"], 5
    )
    quintile_table = summarize_uncertainty(income, "quintil_ingreso")
    tables["26_incertidumbre_quintil_ingreso"] = quintile_table.sort_values("quintil_ingreso")

    departments = data[data["depto"].isin(base.DEPARTMENTS_24)].copy()
    departments["departamento"] = departments["depto"].map(base.DEPARTMENTS_24)
    department_table = summarize_uncertainty(departments, "departamento")
    tables["27_incertidumbre_departamento"] = department_table.sort_values(
        "participacion_ambos_alta", ascending=False
    )

    both = data[data["has_both_indices"]].copy()
    total_ocupados = data["fex"].sum()
    both["ambos_alta"] = both["is_oit_alta"] & both["is_aioe_alta"]
    both["ambos_baja"] = ~both["is_oit_alta"] & ~both["is_aioe_alta"]
    occupation_table = (
        both.groupby(["oficio_c8_4d", "oficio_c8_label"], dropna=False, as_index=False)
        .apply(
            lambda part: pd.Series(
                {
                    "ocupados": part["fex"].sum(),
                    "ocupados_ambos_alta": part.loc[part["ambos_alta"], "fex"].sum(),
                    "ocupados_ambos_baja": part.loc[part["ambos_baja"], "fex"].sum(),
                    "ocupados_incertidumbre": part.loc[part["es_incierto"], "fex"].sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index(drop=True)
    )
    for column in ["ambos_alta", "ambos_baja", "incertidumbre"]:
        occupation_table[f"participacion_empleo_{column}"] = (
            occupation_table[f"ocupados_{column}"] / total_ocupados
        )
    tables["28_incertidumbre_ocupaciones"] = occupation_table.sort_values(
        "ocupados", ascending=False
    ).reset_index(drop=True)

    tables["29_dispersion_oit_aioe_ocupaciones"] = build_scatter_table(data)
    tables["30_sensibilidad_umbrales"] = build_sensitivity_table(data)

    percentile_income = income.copy()
    percentile_income["percentil_ingreso"] = base.assign_weighted_bins(
        percentile_income["ingreso_laboral_mensual_2025"], percentile_income["fex"], 100
    )
    percentile_table = summarize_uncertainty(percentile_income, "percentil_ingreso").sort_values(
        "percentil_ingreso"
    )
    tables["31_coincidencia_percentil_ingreso"] = percentile_table.reset_index(drop=True)

    return tables


def build_scatter_table(data: pd.DataFrame) -> pd.DataFrame:
    both = data[data["has_both_indices"]]
    occupations = (
        both.groupby(["oficio_c8_4d", "oficio_c8_label"], dropna=False, as_index=False)
        .agg(
            ocupados=("fex", "sum"),
            oit_puntaje=("ai_exposure_mean", "first"),
            aioe=("ai_aioe_all", "first"),
            is_oit_alta=("is_oit_alta", "first"),
            is_aioe_alta=("is_aioe_alta", "first"),
        )
    )
    occupations["categoria"] = np.select(
        [
            occupations["is_oit_alta"] & occupations["is_aioe_alta"],
            ~occupations["is_oit_alta"] & ~occupations["is_aioe_alta"],
        ],
        [ALTA_LABEL, BAJA_LABEL],
        default=INCIERTO_LABEL,
    )
    occupations["corte_oit"] = float(data["corte_oit"].iloc[0])
    occupations["corte_aioe"] = float(data["corte_aioe"].iloc[0])
    return occupations


def build_sensitivity_table(data: pd.DataFrame) -> pd.DataFrame:
    """Participacion de cada categoria cuando el corte de ambos indices se
    mueve del percentil 30 al 70 de su distribucion entre ocupaciones; el
    caso base es el percentil 50 (mediana)."""
    both = data[data["has_both_indices"]]
    occupations = occupation_table(data)
    weights = both["fex"]
    total = weights.sum()
    rows = []
    for percentile in SENSITIVITY_PERCENTILES:
        cut_oit = float(np.percentile(occupations["oit"], percentile))
        cut_aioe = float(np.percentile(occupations["aioe"], percentile))
        oit_alta = both["ai_exposure_mean"] >= cut_oit
        aioe_alta = both["ai_aioe_all"] >= cut_aioe
        rows.append(
            {
                "percentil_corte": percentile,
                "corte_oit": cut_oit,
                "corte_aioe": cut_aioe,
                "participacion_ambos_alta": weights[oit_alta & aioe_alta].sum() / total,
                "participacion_ambos_baja": weights[~oit_alta & ~aioe_alta].sum() / total,
                "participacion_incertidumbre": weights[oit_alta != aioe_alta].sum() / total,
            }
        )
    return pd.DataFrame(rows)


def save_stacked_chart(
    sections: list[tuple[str | None, pd.DataFrame, str]],
    filename: str,
    title: str,
    subtitle: str,
    row_height: int = 70,
    min_height: int = 560,
) -> None:
    """Barras horizontales de 0 a 100% por grupo, con los tres segmentos
    pintados de forma explicita: tramo oscuro = ambos indices coinciden en
    alto potencial, tramo claro = ambos coinciden en bajo potencial, tramo
    rojo = los indices no coinciden (incertidumbre). Los tres suman 100%.

    ``sections`` es una lista de ``(titulo_seccion, tabla, columna_etiqueta)``;
    cada tabla requiere ``participacion_ambos_alta``, ``participacion_ambos_baja``
    y ``participacion_incertidumbre``.
    """
    width = 2200
    label_left = 70
    plot_left = 790
    plot_right = 1700
    alta_x = 1730
    baja_x = 1885
    incierto_x = 2040
    font_label = base.image_font(23)
    font_value = base.image_font(22, bold=True)
    font_tick = base.image_font(20)
    font_section = base.image_font(27, bold=True)
    font_head = base.image_font(18, bold=True)

    section_gap = 30
    section_title_h = 56
    total_rows = sum(len(table) for _, table, _ in sections)
    body_h = (
        row_height * total_rows
        + sum((section_title_h if name else 0) + section_gap for name, _, _ in sections)
    )
    height = max(min_height, 330 + body_h + 100)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = base.draw_header(draw, title, subtitle, width)

    legend_y = top - 22
    legend_x = label_left
    for color, text in [(ALTA_COLOR, ALTA_LABEL), (BAJA_COLOR, BAJA_LABEL), (INCIERTO_COLOR, INCIERTO_LABEL)]:
        draw.rectangle((legend_x, legend_y + 3, legend_x + 24, legend_y + 27), fill=color)
        draw.text((legend_x + 36, legend_y), text, font=font_label, fill="#27313B")
        box = draw.textbbox((0, 0), text, font=font_label)
        legend_x += 36 + (box[2] - box[0]) + 50

    head_y = legend_y + 34
    draw.text((alta_x - 4, head_y), "Alta", font=font_head, fill=ALTA_COLOR)
    draw.text((baja_x - 4, head_y), "Baja", font=font_head, fill="#4A7BB0")
    draw.text((incierto_x - 4, head_y), "Incierta", font=font_head, fill=INCIERTO_COLOR)

    y = legend_y + 76
    plot_top = y
    for name, table, label_col in sections:
        if name:
            draw.text((label_left, y), name, font=font_section, fill=base.BLUE)
            y += section_title_h
        for _, row in table.iterrows():
            alta = float(row["participacion_ambos_alta"])
            baja = float(row["participacion_ambos_baja"])
            incierto = float(row["participacion_incertidumbre"])
            label = str(row[label_col])
            wrapped = textwrap.wrap(label, width=46)[:2]
            text_y = y + 8 - (12 if len(wrapped) == 2 else 0)
            for index, line in enumerate(wrapped):
                draw.text((label_left, text_y + index * 25), line, font=font_label, fill="#27313B")
            span = plot_right - plot_left
            alta_w = span * alta
            baja_w = span * baja
            incierto_w = span - alta_w - baja_w
            draw.rectangle((plot_left, y, plot_right, y + 38), fill=INCIERTO_COLOR)
            draw.rectangle((plot_left, y, plot_left + alta_w, y + 38), fill=ALTA_COLOR)
            draw.rectangle(
                (plot_left + alta_w, y, plot_left + alta_w + baja_w, y + 38), fill=BAJA_COLOR
            )
            draw.text((alta_x, y + 4), f"{alta:.1%}".replace(".", ","), font=font_value, fill="#27313B")
            draw.text((baja_x, y + 4), f"{baja:.1%}".replace(".", ","), font=font_value, fill="#27313B")
            draw.text((incierto_x, y + 4), f"{incierto:.1%}".replace(".", ","), font=font_value, fill="#27313B")
            y += row_height
        y += section_gap

    axis_y = y - section_gap + 8
    for step in range(5):
        x = plot_left + (plot_right - plot_left) * step / 4
        draw.line((x, plot_top, x, axis_y), fill="#FFFFFF", width=1)
        tick = f"{step * 25}%"
        box = draw.textbbox((0, 0), tick, font=font_tick)
        draw.text((x - (box[2] - box[0]) / 2, axis_y + 12), tick, font=font_tick, fill="#5A6570")
    draw.line((plot_left, axis_y, plot_right, axis_y), fill="#71808F", width=1)
    axis_label = "Participación del empleo del grupo"
    box = draw.textbbox((0, 0), axis_label, font=font_label)
    draw.text(
        ((plot_left + plot_right - (box[2] - box[0])) / 2, axis_y + 50),
        axis_label,
        font=font_label,
        fill="#3E4A56",
    )
    draw.text((70, height - 55), SOURCE, font=base.image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def _plot_legend(draw, items, x, y, font):
    for color, text in items:
        draw.ellipse((x, y + 3, x + 24, y + 27), fill=color)
        draw.text((x + 36, y), text, font=font, fill="#27313B")
        box = draw.textbbox((0, 0), text, font=font)
        x += 36 + (box[2] - box[0]) + 60


def occupation_percentiles(scores: pd.Series) -> pd.Series:
    """Rangos medios en percentiles, con los empates en la mediana en P50."""
    percentiles = 100 * (scores.rank(method="average") - 0.5) / scores.count()
    return percentiles.mask(scores.eq(scores.median()), 50.0)


def save_agreement_scatter(table: pd.DataFrame, filename: str) -> None:
    """Percentiles OIT-NASK (eje x) contra AIOE (eje y) por ocupacion. Las
    lineas de corte (medianas de cada indice) definen cuatro zonas: en dos
    coinciden los indices y las otras dos son la discrepancia (arriba a la
    izquierda: AIOE alto y OIT bajo; abajo a la derecha: OIT alto y AIOE bajo)."""
    table = table.assign(
        oit_percentil=occupation_percentiles(table["oit_puntaje"]),
        aioe_percentil=occupation_percentiles(table["aioe"]),
    )
    width, height = 2200, 1500
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = base.draw_header(
        draw,
        "Potencialidad de automatización por ocupación",
        "",
        width,
    )
    font_label = base.image_font(24)
    font_axis = base.image_font(26, bold=True)
    font_tick = base.image_font(20)
    font_zone = base.image_font(27, bold=True)

    _plot_legend(
        draw,
        [(ALTA_COLOR, ALTA_LABEL), (BAJA_COLOR, BAJA_LABEL), (INCIERTO_COLOR, INCIERTO_LABEL)],
        70,
        top - 22,
        font_label,
    )
    top += 50
    left, right = 230, 2120
    bottom = height - 170
    # Leave room for edge bubbles and quadrant labels outside the data range.
    x_min, x_max = -8.0, 108.0
    y_min, y_max = -8.0, 108.0

    def to_x(value: float) -> float:
        return left + (right - left) * (value - x_min) / (x_max - x_min)

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * (value - y_min) / (y_max - y_min)

    x_cut = to_x(50.0)
    y_cut = to_y(50.0)
    draw.rectangle((x_cut, top, right, y_cut), fill="#E7EEF7")
    draw.rectangle((left, top, x_cut, y_cut), fill="#FBECEA")
    draw.rectangle((left, y_cut, x_cut, bottom), fill="#F2F4F6")
    draw.rectangle((x_cut, y_cut, right, bottom), fill="#FBECEA")

    total = table["ocupados"].sum()
    share = table.groupby("categoria")["ocupados"].sum() / total
    solo_aioe = table.loc[~table["is_oit_alta"] & table["is_aioe_alta"], "ocupados"].sum() / total
    solo_oit = table.loc[table["is_oit_alta"] & ~table["is_aioe_alta"], "ocupados"].sum() / total
    zones = [
        ((x_cut + right) / 2, top + 20, f"ALTO POTENCIAL ({share.get(ALTA_LABEL, 0):.0%})"),
        ((left + x_cut) / 2, top + 20, f"INCIERTO ({solo_aioe:.0%})"),
        ((left + x_cut) / 2, bottom - 56, f"BAJO POTENCIAL ({share.get(BAJA_LABEL, 0):.0%})"),
        ((x_cut + right) / 2, bottom - 56, f"INCIERTO ({solo_oit:.0%})"),
    ]
    for cx, cy, text in zones:
        text = text.replace(".", ",")
        box = draw.textbbox((0, 0), text, font=font_zone)
        draw.text((cx - (box[2] - box[0]) / 2, cy), text, font=font_zone, fill="#8B95A1")

    for x_value in [0, 25, 50, 75, 100]:
        tick = str(x_value)
        box = draw.textbbox((0, 0), tick, font=font_tick)
        draw.text((to_x(x_value) - (box[2] - box[0]) / 2, bottom + 12), tick, font=font_tick, fill="#5A6570")
        y_value = x_value
        tick_y = str(y_value)
        box_y = draw.textbbox((0, 0), tick_y, font=font_tick)
        draw.text((left - 14 - (box_y[2] - box_y[0]), to_y(y_value) - 10), tick_y, font=font_tick, fill="#5A6570")

    draw.line((x_cut, top, x_cut, bottom), fill="#71808F", width=3)
    draw.line((left, y_cut, right, y_cut), fill="#71808F", width=3)
    font_cut = base.image_font(21)
    cut_oit_text = "Mediana OIT-NASK (P50)"
    cut_aioe_text = "Mediana AIOE (P50)"
    draw.text((x_cut + 10, bottom - 96), cut_oit_text, font=font_cut, fill="#5A6570")
    box = draw.textbbox((0, 0), cut_aioe_text, font=font_cut)
    draw.text((right - 10 - (box[2] - box[0]), y_cut - 30), cut_aioe_text, font=font_cut, fill="#5A6570")

    colors = {ALTA_LABEL: ALTA_COLOR, BAJA_LABEL: BAJA_COLOR, INCIERTO_LABEL: INCIERTO_COLOR}
    max_size = float(table["ocupados"].max()) or 1.0
    for _, row in table.sort_values("ocupados", ascending=False).iterrows():
        x = to_x(float(row["oit_percentil"]))
        y = to_y(float(row["aioe_percentil"]))
        radius = 4 + 26 * (float(row["ocupados"]) / max_size) ** 0.5
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=colors[row["categoria"]],
            outline="white",
            width=1,
        )

    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_label = "Percentil de la ocupación en OIT-NASK"
    box = draw.textbbox((0, 0), x_label, font=font_axis)
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 55), x_label, font=font_axis, fill="#27313B")
    draw.text((left, top - 34), "Percentil de la ocupación en AIOE (Felten)", font=font_axis, fill="#27313B")
    draw.text(
        (70, height - 85),
        "El tamaño de los puntos indica el empleo. Los porcentajes corresponden a trabajadores, no a ocupaciones.",
        font=base.image_font(23),
        fill="#5A6570",
    )
    draw.text((70, height - 45), SOURCE, font=base.image_font(19), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_sensitivity_chart(table: pd.DataFrame, filename: str) -> None:
    """Participacion de cada categoria segun el percentil en que se corta
    cada indice (el mismo percentil para ambos; P50 = mediana, caso base)."""
    width, height = 2200, 1300
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = base.draw_header(
        draw,
        "Potencialidad de automatización: sensibilidad al corte",
        "",
        width,
    )
    font_label = base.image_font(24)
    font_value = base.image_font(22, bold=True)
    font_axis = base.image_font(26, bold=True)
    font_tick = base.image_font(21)

    series = [
        (ALTA_LABEL, "participacion_ambos_alta", ALTA_COLOR),
        (BAJA_LABEL, "participacion_ambos_baja", BAJA_COLOR),
        (INCIERTO_LABEL, "participacion_incertidumbre", INCIERTO_COLOR),
    ]
    _plot_legend(draw, [(color, name) for name, _, color in series], 70, top - 22, font_label)
    top += 60
    left, right = 190, 2060
    bottom = height - 230
    y_max = 0.8
    percentiles = SENSITIVITY_PERCENTILES
    x_min, x_max = min(percentiles) - 5, max(percentiles) + 5

    def to_x(value: float) -> float:
        return left + (right - left) * (value - x_min) / (x_max - x_min)

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * value / y_max

    for step in range(5):
        value = y_max * step / 4
        y = to_y(value)
        draw.line((left, y, right, y), fill=base.GRID, width=1)
        draw.text((left - 84, y - 12), f"{value:.0%}", font=font_tick, fill="#5A6570")
    for percentile in percentiles:
        x = to_x(percentile)
        draw.line((x, bottom, x, bottom + 8), fill="#71808F", width=2)
        tick = f"P{percentile}"
        box = draw.textbbox((0, 0), tick, font=font_tick)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 16), tick, font=font_tick, fill="#5A6570")

    part = table.sort_values("percentil_corte")
    for _, column, color in series:
        points = [(to_x(r["percentil_corte"]), to_y(r[column])) for _, r in part.iterrows()]
        draw.line(points, fill=color, width=6, joint="curve")
        for (x, y), (_, r) in zip(points, part.iterrows()):
            radius = 15 if int(r["percentil_corte"]) == 50 else 9
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="white", width=3)
            label = f"{r[column]:.1%}".replace(".", ",")
            box = draw.textbbox((0, 0), label, font=font_value)
            is_top = r[column] >= max(r[c] for _, c, _ in series)
            label_y = y - 46 if is_top else y + 18
            draw.text((x - (box[2] - box[0]) / 2, label_y), label, font=font_value, fill="#27313B")

    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_label = "Percentil de corte de ambos índices entre ocupaciones (P50 = mediana, caso base)"
    box = draw.textbbox((0, 0), x_label, font=font_axis)
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 62), x_label, font=font_axis, fill="#27313B")
    draw.text((left, top - 34), "Participación del empleo", font=font_axis, fill="#27313B")
    draw.text((70, height - 55), SOURCE, font=base.image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_percentile_area_chart(table: pd.DataFrame, filename: str, window: int = 5) -> None:
    """Areas apiladas por percentil de ingreso: oscuro = ambos alta, claro =
    ambos baja; el espacio vacio hasta 100% es la incertidumbre."""
    plot = table.sort_values("percentil_ingreso").reset_index(drop=True)
    for column in ["participacion_ambos_alta", "participacion_ambos_baja"]:
        plot[column + "_suave"] = plot[column].rolling(window, center=True, min_periods=1).mean()
    width, height = 2200, 1300
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = base.draw_header(
        draw,
        "Potencialidad de automatización por percentil de ingreso",
        "",
        width,
    )
    font_label = base.image_font(24)
    font_axis = base.image_font(26, bold=True)
    font_tick = base.image_font(21)
    _plot_legend(draw, [(ALTA_COLOR, ALTA_LABEL), (BAJA_COLOR, BAJA_LABEL)], 70, top - 22, font_label)
    top += 60
    left, right = 190, 2110
    bottom = height - 230

    def to_x(percentile: float) -> float:
        return left + (right - left) * (percentile - 1) / 99

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * value

    draw.rectangle((left, top, right, bottom), fill=TRACK_COLOR)
    xs = [to_x(p) for p in plot["percentil_ingreso"]]
    alta = plot["participacion_ambos_alta_suave"].tolist()
    total = (plot["participacion_ambos_alta_suave"] + plot["participacion_ambos_baja_suave"]).tolist()
    baja_poly = [(x, to_y(t)) for x, t in zip(xs, total)] + [
        (x, to_y(a)) for x, a in zip(reversed(xs), reversed(alta))
    ]
    alta_poly = [(x, to_y(a)) for x, a in zip(xs, alta)] + [(xs[-1], bottom), (xs[0], bottom)]
    draw.polygon(baja_poly, fill=BAJA_COLOR)
    draw.polygon(alta_poly, fill=ALTA_COLOR)

    for step in range(5):
        value = step / 4
        y = to_y(value)
        draw.line((left, y, right, y), fill="white", width=2)
        draw.text((left - 84, y - 12), f"{value:.0%}", font=font_tick, fill="#5A6570")
    for percentile in [1, 20, 40, 60, 80, 100]:
        x = to_x(percentile)
        draw.line((x, bottom, x, bottom + 8), fill="#71808F", width=2)
        tick = str(percentile)
        box = draw.textbbox((0, 0), tick, font=font_tick)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 16), tick, font=font_tick, fill="#5A6570")

    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_label = "Percentil de ingreso laboral mensual"
    box = draw.textbbox((0, 0), x_label, font=font_axis)
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 62), x_label, font=font_axis, fill="#27313B")
    draw.text((left, top - 34), "Participación del empleo del percentil", font=font_axis, fill="#27313B")
    draw.text((70, height - 55), SOURCE, font=base.image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def build_charts(tables: dict[str, pd.DataFrame]) -> None:
    national = tables["21_incertidumbre_nacional"].iloc[0]
    headline = pd.DataFrame(
        [
            {"categoria": ALTA_LABEL, "participacion": national["participacion_ambos_alta"]},
            {"categoria": BAJA_LABEL, "participacion": national["participacion_ambos_baja"]},
            {"categoria": INCIERTO_LABEL, "participacion": national["participacion_incertidumbre"]},
        ]
    )
    base.save_bar_chart(
        headline,
        "categoria",
        "participacion",
        "fig_21_coincidencia_nacional.png",
        "Potencialidad de automatización en Colombia",
        "",
        percent=True,
        preserve_order=True,
        color_by_label={ALTA_LABEL: ALTA_COLOR, BAJA_LABEL: BAJA_COLOR, INCIERTO_LABEL: INCIERTO_COLOR},
        source=SOURCE,
        min_height=600,
        axis_label="Participación del empleo",
    )

    sex = tables["22_incertidumbre_sexo"]
    formality_2 = tables["23_incertidumbre_formalidad"][
        tables["23_incertidumbre_formalidad"]["formalidad"].isin(["Formal", "Informal"])
    ].copy()
    formality_2["formalidad"] = pd.Categorical(
        formality_2["formalidad"], categories=["Formal", "Informal"], ordered=True
    )
    formality_2 = formality_2.sort_values("formalidad")
    save_stacked_chart(
        [("A. Género", sex, "sexo"), ("B. Formalidad", formality_2, "formalidad")],
        "fig_22_coincidencia_genero_formalidad.png",
        "Potencialidad de automatización por género y formalidad",
        "",
    )

    save_stacked_chart(
        [(None, tables["24_incertidumbre_logro_educativo"], "educacion")],
        "fig_23_coincidencia_logro_educativo.png",
        "Potencialidad de automatización por logro educativo",
        "",
    )

    save_stacked_chart(
        [(None, tables["25_incertidumbre_actividad_economica"], "sector")],
        "fig_24_coincidencia_actividad_economica.png",
        "Potencialidad de automatización por actividad económica",
        "",
    )

    quintile = tables["26_incertidumbre_quintil_ingreso"].copy()
    quintile["quintil"] = quintile["quintil_ingreso"].map(
        {1: "Quintil 1 (más bajo)", 2: "Quintil 2", 3: "Quintil 3", 4: "Quintil 4", 5: "Quintil 5 (más alto)"}
    )
    save_stacked_chart(
        [(None, quintile, "quintil")],
        "fig_25_coincidencia_quintil_ingreso.png",
        "Potencialidad de automatización por quintil de ingreso laboral",
        "",
    )

    save_stacked_chart(
        [(None, tables["27_incertidumbre_departamento"], "departamento")],
        "fig_26_coincidencia_departamento.png",
        "Potencialidad de automatización por departamento",
        "",
        row_height=56,
    )

    occupations = tables["28_incertidumbre_ocupaciones"]
    top_alta = occupations.sort_values("ocupados_ambos_alta", ascending=False).head(12).copy()
    top_baja = occupations.sort_values("ocupados_ambos_baja", ascending=False).head(12).copy()
    top_alta["tipo"] = ALTA_LABEL
    top_baja["tipo"] = BAJA_LABEL
    base.save_multi_panel_bar_chart(
        [
            (top_alta, "oficio_c8_label", "participacion_empleo_ambos_alta", "A. Alto potencial"),
            (top_baja, "oficio_c8_label", "participacion_empleo_ambos_baja", "B. Bajo potencial"),
        ],
        "fig_27_coincidencia_ocupaciones.png",
        "Potencialidad de automatización: ocupaciones con más empleo",
        "",
        percent=True,
        color=ALTA_COLOR,
        axis_label="Participación en el empleo total nacional",
        label_widths=[300, 300],
        row_height=78,
        color_by_label={ALTA_LABEL: ALTA_COLOR, BAJA_LABEL: BAJA_COLOR},
        color_column="tipo",
        source=SOURCE,
    )

    top_incierto = occupations.sort_values("ocupados_incertidumbre", ascending=False).head(12).copy()
    base.save_bar_chart(
        top_incierto,
        "oficio_c8_label",
        "participacion_empleo_incertidumbre",
        "fig_27b_ocupaciones_incertidumbre.png",
        "Ocupaciones con más empleo y potencial de automatización incierto",
        "",
        percent=True,
        preserve_order=True,
        color=INCIERTO_COLOR,
        axis_label="Participación en el empleo total nacional",
        source=SOURCE,
        min_height=620,
    )

    save_agreement_scatter(tables["29_dispersion_oit_aioe_ocupaciones"], "fig_28_dispersion_oit_aioe.png")
    save_sensitivity_chart(tables["30_sensibilidad_umbrales"], "fig_29_sensibilidad_umbrales.png")
    save_percentile_area_chart(
        tables["31_coincidencia_percentil_ingreso"], "fig_30_coincidencia_percentil_ingreso.png"
    )


def write_outputs(tables: dict[str, pd.DataFrame]) -> None:
    for name, table in tables.items():
        table.to_csv(TABLE_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    data, _, _ = base.load_inputs()
    data = flag_uncertainty(data)
    tables = build_tables(data)
    write_outputs(tables)
    build_charts(tables)

    national = tables["21_incertidumbre_nacional"].iloc[0]
    print("Análisis de coincidencia terminado")
    print(f"Ocupados con ambos índices: {national['ocupados_con_ambos_indices']:,.0f}")
    print(f"Coinciden en exposición alta: {national['participacion_ambos_alta']:.2%}")
    print(f"Coinciden en exposición baja: {national['participacion_ambos_baja']:.2%}")
    print(f"Residuo (incertidumbre): {national['participacion_incertidumbre']:.2%}")
    print(f"Tablas: {TABLE_DIR}")
    print(f"Figuras: {FIG_DIR}")


if __name__ == "__main__":
    main()
