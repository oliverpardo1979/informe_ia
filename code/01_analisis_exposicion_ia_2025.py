"""Analisis de exposicion a IA generativa para la poblacion ocupada en 2025.

El indicador principal usa exclusivamente la correspondencia exacta a cuatro
digitos entre OFICIO_C8 (CIUO-08 A.C.) y la tabla de exposicion de la OIT. La
imputacion a dos digitos se conserva solo como ejercicio de sensibilidad.

Insumos esperados:
  - CJC-Monitor/Datos/Processed/BaseIA.dta
  - CJC-Monitor/DocumentacionAuxiliar/
    correlativa_IA_ISCO08_GEIH_OFICIO_C8.xlsx
  - informe_ia/sources/ILO_2025_GenAI_scores_ISCO08.json (opcional, para QA)

Las rutas pueden reemplazarse con BASE_IA_PATH, IA_CROSSWALK_PATH y
CJC_MONITOR_ROOT.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CJC_ROOT = Path(os.environ.get("CJC_MONITOR_ROOT", ROOT.parent / "CJC-Monitor"))
BASE_PATH = Path(
    os.environ.get(
        "BASE_IA_PATH",
        CJC_ROOT / "Datos" / "Processed" / "BaseIA.dta",
    )
)
CROSSWALK_PATH = Path(
    os.environ.get(
        "IA_CROSSWALK_PATH",
        CJC_ROOT
        / "DocumentacionAuxiliar"
        / "correlativa_IA_ISCO08_GEIH_OFICIO_C8.xlsx",
    )
)
ILO_TASKS_PATH = ROOT / "sources" / "ILO_2025_GenAI_scores_ISCO08.json"

TABLE_DIR = ROOT / "outputs" / "tables"
FIG_DIR = ROOT / "figures"
TABLE_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

YEAR = 2025
MONTHS_PER_WEEK = 52.0 / 12.0

DEPARTMENTS_24 = {
    5: "Antioquia",
    8: "Atlántico",
    11: "Bogotá D.C.",
    13: "Bolívar",
    15: "Boyacá",
    17: "Caldas",
    18: "Caquetá",
    19: "Cauca",
    20: "Cesar",
    23: "Córdoba",
    25: "Cundinamarca",
    27: "Chocó",
    41: "Huila",
    44: "La Guajira",
    47: "Magdalena",
    50: "Meta",
    52: "Nariño",
    54: "Norte de Santander",
    63: "Quindío",
    66: "Risaralda",
    68: "Santander",
    70: "Sucre",
    73: "Tolima",
    76: "Valle del Cauca",
}

GROUP_ORDER = [
    "Not Exposed",
    "Minimal Exposure",
    "Gradient 1",
    "Gradient 2",
    "Gradient 3",
    "Gradient 4",
    "Sin correspondencia 4d",
]
GROUP_LABELS = {
    "Not Exposed": "No expuesta",
    "Minimal Exposure": "Exposición mínima",
    "Gradient 1": "Gradiente 1",
    "Gradient 2": "Gradiente 2",
    "Gradient 3": "Gradiente 3",
    "Gradient 4": "Gradiente 4",
    "Sin correspondencia 4d": "Sin correspondencia 4d",
}
GROUP_COLORS = {
    "Not Exposed": "#D9DDE2",
    "Minimal Exposure": "#9FB3C8",
    "Gradient 1": "#6BAED6",
    "Gradient 2": "#3182BD",
    "Gradient 3": "#D9A441",
    "Gradient 4": "#B6423C",
    "Sin correspondencia 4d": "#666666",
}
BLUE = "#17365D"
GOLD = "#D9A441"
GRID = "#D9DEE5"


def normalize_text(value: object) -> str:
    text = str(value).strip().lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values[mask].astype(float), weights=weights[mask].astype(float)))


def weighted_quantile(values: pd.Series, weights: pd.Series, probs: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame({"value": values, "weight": weights}).dropna()
    frame = frame[frame["weight"] > 0].sort_values("value")
    if frame.empty:
        return np.full(len(probs), np.nan)
    grouped = frame.groupby("value", as_index=False, sort=True)["weight"].sum()
    cumulative = grouped["weight"].cumsum().to_numpy()
    targets = np.asarray(probs, dtype=float) * grouped["weight"].sum()
    idx = np.searchsorted(cumulative, targets, side="left")
    idx = np.clip(idx, 0, len(grouped) - 1)
    return grouped["value"].to_numpy()[idx]


def assign_weighted_bins(values: pd.Series, weights: pd.Series, bins: int) -> pd.Series:
    cutoffs = weighted_quantile(values, weights, np.arange(1, bins) / bins)
    result = np.searchsorted(cutoffs, values.to_numpy(dtype=float), side="left") + 1
    return pd.Series(result, index=values.index, dtype="Int64")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not BASE_PATH.exists():
        raise FileNotFoundError(f"No existe la base: {BASE_PATH}")
    if not CROSSWALK_PATH.exists():
        raise FileNotFoundError(f"No existe la correlativa: {CROSSWALK_PATH}")

    columns = [
        "persona_id",
        "anio",
        "depto",
        "sector_hom_cod",
        "sector",
        "oficio_c8_4d",
        "oficio_c8_label",
        "oficio_c8_2d_cod",
        "oficio_c8_2d_label",
        "posicion_ocupacional_label",
        "educ_hom_cod",
        "educacion",
        "sexo",
        "formalidad",
        "fex",
        "horas",
        "ingreso_hora_real",
    ]
    data = pd.read_stata(BASE_PATH, columns=columns, convert_categoricals=False)
    numeric = [
        "anio",
        "depto",
        "sector_hom_cod",
        "oficio_c8_4d",
        "oficio_c8_2d_cod",
        "educ_hom_cod",
        "fex",
        "horas",
        "ingreso_hora_real",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[(data["anio"] == YEAR) & data["fex"].gt(0)].copy()
    data["oficio_c8_4d"] = data["oficio_c8_4d"].astype("Int64")
    data["oficio_c8_2d_cod"] = data["oficio_c8_2d_cod"].astype("Int64")

    crosswalk_4d = pd.read_excel(CROSSWALK_PATH, sheet_name="correlativa_4d")
    crosswalk_2d = pd.read_excel(CROSSWALK_PATH, sheet_name="resumen_2d")
    crosswalk_4d["oficio_c8"] = pd.to_numeric(
        crosswalk_4d["oficio_c8"], errors="raise"
    ).astype("Int64")
    crosswalk_2d["oficio_2d"] = pd.to_numeric(
        crosswalk_2d["oficio_2d"], errors="raise"
    ).astype("Int64")

    if crosswalk_4d["oficio_c8"].duplicated().any():
        raise ValueError("La correlativa contiene códigos 4d duplicados.")
    if crosswalk_2d["oficio_2d"].duplicated().any():
        raise ValueError("La correlativa contiene códigos 2d duplicados.")

    data = data.merge(
        crosswalk_4d[
            [
                "oficio_c8",
                "occupation_name_isco08",
                "ai_exposure_mean",
                "ai_exposure_sd",
                "ai_exposure_group",
                "ai_exposure_order",
                "high_exposure_g3_g4",
            ]
        ],
        left_on="oficio_c8_4d",
        right_on="oficio_c8",
        how="left",
        validate="m:1",
    )
    data = data.merge(
        crosswalk_2d[
            [
                "oficio_2d",
                "ai_exposure_mean_unweighted_2d",
                "modal_exposure_group_2d",
            ]
        ],
        left_on="oficio_c8_2d_cod",
        right_on="oficio_2d",
        how="left",
        validate="m:1",
    )
    data["grupo_exposicion_4d"] = data["ai_exposure_group"].fillna(
        "Sin correspondencia 4d"
    )
    data["exposicion_sensibilidad_2d"] = data["ai_exposure_mean"].fillna(
        data["ai_exposure_mean_unweighted_2d"]
    )
    data["fuente_sensibilidad"] = np.select(
        [
            data["ai_exposure_mean"].notna(),
            data["ai_exposure_mean_unweighted_2d"].notna(),
        ],
        ["4d", "2d"],
        default="sin correspondencia",
    )
    return data, crosswalk_4d, crosswalk_2d


def summarize_group(data: pd.DataFrame, group: str, label: str | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for value, part in data.groupby(group, dropna=False, sort=False):
        total = part["fex"].sum()
        matched = part["ai_exposure_mean"].notna()
        row: dict[str, object] = {
            group: value,
            "ocupados": total,
            "observaciones": len(part),
            "cobertura_4d": part.loc[matched, "fex"].sum() / total,
            "exposicion_promedio_4d": weighted_mean(
                part.loc[matched, "ai_exposure_mean"], part.loc[matched, "fex"]
            ),
        }
        for exposure_group in GROUP_ORDER:
            key = "participacion_" + exposure_group.lower().replace(" ", "_")
            row[key] = (
                part.loc[part["grupo_exposicion_4d"] == exposure_group, "fex"].sum()
                / total
            )
        row["participacion_expuesta_g1_g4"] = (
            part.loc[
                part["grupo_exposicion_4d"].isin(
                    ["Gradient 1", "Gradient 2", "Gradient 3", "Gradient 4"]
                ),
                "fex",
            ].sum()
            / total
        )
        row["participacion_alta_g3_g4"] = (
            part.loc[
                part["grupo_exposicion_4d"].isin(["Gradient 3", "Gradient 4"]),
                "fex",
            ].sum()
            / total
        )
        rows.append(row)
    result = pd.DataFrame(rows)
    if label is not None:
        result = result.rename(columns={group: label})
    return result


def validate_ilo_task_file(crosswalk: pd.DataFrame) -> dict[str, object]:
    result: dict[str, object] = {
        "archivo_tareas_oit_disponible": ILO_TASKS_PATH.exists(),
        "ocupaciones_json": np.nan,
        "codigos_json_iguales_correlativa": np.nan,
        "max_diferencia_media_anexo_vs_tareas_redondeadas": np.nan,
        "codigo_max_diferencia": np.nan,
    }
    if not ILO_TASKS_PATH.exists():
        return result

    tree = json.loads(ILO_TASKS_PATH.read_text(encoding="utf-8"))
    occupations: list[dict[str, object]] = []
    for level1 in tree.get("children", []):
        for level2 in level1.get("children", []):
            for level3 in level2.get("children", []):
                for occupation in level3.get("children", []):
                    match = re.match(r"^(\d{4})\s*-\s*(.*)$", occupation["name"])
                    if not match:
                        continue
                    scores = []
                    for task in occupation.get("children", []):
                        score_match = re.match(r"^\(\s*([0-9.]+)\s*\)", task["name"])
                        if score_match:
                            scores.append(float(score_match.group(1)))
                    occupations.append(
                        {
                            "oficio_c8": int(match.group(1)),
                            "media_tareas_json": np.mean(scores) if scores else np.nan,
                        }
                    )
    official = pd.DataFrame(occupations)
    merged = crosswalk.merge(official, on="oficio_c8", how="outer", indicator=True)
    both = merged[merged["_merge"] == "both"].copy()
    both["diferencia"] = both["ai_exposure_mean"] - both["media_tareas_json"]
    max_index = both["diferencia"].abs().idxmax()
    result.update(
        {
            "ocupaciones_json": len(official),
            "codigos_json_iguales_correlativa": bool((merged["_merge"] == "both").all()),
            "max_diferencia_media_anexo_vs_tareas_redondeadas": float(
                both.loc[max_index, "diferencia"]
            ),
            "codigo_max_diferencia": int(both.loc[max_index, "oficio_c8"]),
        }
    )
    return result


def build_tables(data: pd.DataFrame, crosswalk_4d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    total_weight = data["fex"].sum()
    matched = data["ai_exposure_mean"].notna()
    matched_weight = data.loc[matched, "fex"].sum()

    national = pd.DataFrame(
        [
            {
                "anio": YEAR,
                "observaciones": len(data),
                "ocupados": total_weight,
                "ocupados_con_correspondencia_4d": matched_weight,
                "cobertura_4d": matched_weight / total_weight,
                "exposicion_promedio_4d": weighted_mean(
                    data.loc[matched, "ai_exposure_mean"], data.loc[matched, "fex"]
                ),
                "participacion_expuesta_g1_g4": data.loc[
                    data["grupo_exposicion_4d"].isin(
                        ["Gradient 1", "Gradient 2", "Gradient 3", "Gradient 4"]
                    ),
                    "fex",
                ].sum()
                / total_weight,
                "participacion_alta_g3_g4": data.loc[
                    data["grupo_exposicion_4d"].isin(["Gradient 3", "Gradient 4"]),
                    "fex",
                ].sum()
                / total_weight,
                "participacion_gradiente_4": data.loc[
                    data["grupo_exposicion_4d"] == "Gradient 4", "fex"
                ].sum()
                / total_weight,
                "participacion_sin_correspondencia_4d": 1 - matched_weight / total_weight,
            }
        ]
    )

    groups = (
        data.groupby("grupo_exposicion_4d", as_index=False, dropna=False)
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
        .assign(participacion=lambda x: x["ocupados"] / total_weight)
    )
    groups["orden"] = groups["grupo_exposicion_4d"].map(
        {value: index for index, value in enumerate(GROUP_ORDER)}
    )
    groups["grupo_exposicion_es"] = groups["grupo_exposicion_4d"].map(GROUP_LABELS)
    groups = groups.sort_values("orden").drop(columns="orden")

    income = data[
        data["ingreso_hora_real"].gt(0)
        & data["horas"].between(1, 112)
        & data["fex"].gt(0)
    ].copy()
    income["ingreso_laboral_mensual_2025"] = (
        income["ingreso_hora_real"] * income["horas"] * MONTHS_PER_WEEK
    )
    income["quintil_ingreso"] = assign_weighted_bins(
        income["ingreso_laboral_mensual_2025"], income["fex"], 5
    )
    income["percentil_ingreso"] = assign_weighted_bins(
        income["ingreso_laboral_mensual_2025"], income["fex"], 100
    )

    quintiles = summarize_group(income, "quintil_ingreso").sort_values("quintil_ingreso")
    percentiles = summarize_group(income, "percentil_ingreso").sort_values(
        "percentil_ingreso"
    )
    for table, group_column in [
        (quintiles, "quintil_ingreso"),
        (percentiles, "percentil_ingreso"),
    ]:
        income_stats = (
            income.groupby(group_column, as_index=False)
            .apply(
                lambda part: pd.Series(
                    {
                        "ingreso_min": part["ingreso_laboral_mensual_2025"].min(),
                        "ingreso_mediana_ponderada": weighted_quantile(
                            part["ingreso_laboral_mensual_2025"],
                            part["fex"],
                            np.array([0.5]),
                        )[0],
                        "ingreso_max": part["ingreso_laboral_mensual_2025"].max(),
                    }
                ),
                include_groups=False,
            )
            .reset_index(drop=True)
        )
        table["participacion_muestra_ingreso"] = table["ocupados"] / income["fex"].sum()
        table.merge(income_stats, on=group_column, how="left", validate="1:1")
        for column in ["ingreso_min", "ingreso_mediana_ponderada", "ingreso_max"]:
            table[column] = table[group_column].map(
                income_stats.set_index(group_column)[column]
            )

    departments = data[data["depto"].isin(DEPARTMENTS_24)].copy()
    departments["departamento"] = departments["depto"].map(DEPARTMENTS_24)
    department_table = summarize_group(departments, "departamento").sort_values(
        "exposicion_promedio_4d", ascending=False
    )

    sector_table = summarize_group(data, "sector").sort_values(
        "exposicion_promedio_4d", ascending=False
    )
    education_table = summarize_group(data, "educacion")
    education_order = (
        data[["educ_hom_cod", "educacion"]].drop_duplicates().set_index("educacion")
    )
    education_table["educ_hom_cod"] = education_table["educacion"].map(
        education_order["educ_hom_cod"]
    )
    education_table = education_table.sort_values("educ_hom_cod")

    sex_table = summarize_group(data, "sexo").sort_values("sexo")
    formality_table = summarize_group(data, "formalidad").sort_values("formalidad")

    occupations = (
        data.groupby(
            [
                "oficio_c8_4d",
                "oficio_c8_label",
                "occupation_name_isco08",
                "grupo_exposicion_4d",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            ocupados=("fex", "sum"),
            observaciones=("persona_id", "size"),
            exposicion_promedio_4d=("ai_exposure_mean", "first"),
            desviacion_tareas_4d=("ai_exposure_sd", "first"),
        )
        .assign(participacion_empleo=lambda x: x["ocupados"] / total_weight)
    )
    occupations = occupations.sort_values(
        ["exposicion_promedio_4d", "ocupados"], ascending=[False, False], na_position="last"
    )
    high_employment = occupations[
        occupations["grupo_exposicion_4d"].isin(["Gradient 3", "Gradient 4"])
    ].sort_values("ocupados", ascending=False)

    unmatched = (
        data[data["ai_exposure_mean"].isna()]
        .groupby(["oficio_c8_4d", "oficio_c8_label"], dropna=False, as_index=False)
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
        .assign(participacion_empleo=lambda x: x["ocupados"] / total_weight)
        .sort_values("ocupados", ascending=False)
    )

    sensitivity_match = data["exposicion_sensibilidad_2d"].notna()
    sensitivity = pd.DataFrame(
        [
            {
                "metodo": "Correspondencia exacta 4d (principal)",
                "cobertura": matched_weight / total_weight,
                "exposicion_promedio": weighted_mean(
                    data.loc[matched, "ai_exposure_mean"], data.loc[matched, "fex"]
                ),
            },
            {
                "metodo": "4d con imputacion 2d (sensibilidad)",
                "cobertura": data.loc[sensitivity_match, "fex"].sum() / total_weight,
                "exposicion_promedio": weighted_mean(
                    data.loc[sensitivity_match, "exposicion_sensibilidad_2d"],
                    data.loc[sensitivity_match, "fex"],
                ),
            },
        ]
    )

    qa_ilo = validate_ilo_task_file(crosswalk_4d)
    qa = pd.DataFrame(
        [
            {
                "anio": YEAR,
                "filas_base": len(data),
                "ocupados_expandido": total_weight,
                "codigos_geih_4d": data["oficio_c8_4d"].nunique(),
                "codigos_correlativa_4d": crosswalk_4d["oficio_c8"].nunique(),
                "cobertura_ponderada_4d": matched_weight / total_weight,
                "departamentos_24_presentes": departments["depto"].nunique(),
                "muestra_ingreso_ocupados": income["fex"].sum(),
                "muestra_ingreso_cobertura": income["fex"].sum() / total_weight,
                **qa_ilo,
            }
        ]
    )

    if not (20_000_000 <= total_weight <= 27_000_000):
        raise ValueError(f"El total expandido de 2025 es implausible: {total_weight:,.0f}")
    if matched_weight / total_weight < 0.90:
        raise ValueError("La cobertura ponderada del cruce 4d es inferior a 90%.")
    if departments["depto"].nunique() != 24:
        raise ValueError("No están presentes los 24 departamentos esperados.")
    if not np.isclose(groups["participacion"].sum(), 1.0, atol=1e-10):
        raise ValueError("Las participaciones por grupo de exposición no suman uno.")

    return {
        "00_qa": qa,
        "01_resumen_nacional": national,
        "02_grupos_exposicion": groups,
        "03_quintiles_ingreso_mensual": quintiles,
        "04_percentiles_ingreso_mensual": percentiles,
        "05_departamentos_24": department_table,
        "06_actividad_economica": sector_table,
        "07_logro_educativo": education_table,
        "08_sexo": sex_table,
        "09_formalidad": formality_table,
        "10_ocupaciones": occupations,
        "11_ocupaciones_alta_exposicion_empleo": high_employment,
        "12_sin_correspondencia_4d": unmatched,
        "13_sensibilidad_2d": sensitivity,
    }


def image_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def draw_header(
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    width: int,
) -> int:
    left = 70
    title_font = image_font(42, bold=True)
    subtitle_font = image_font(25)
    draw.text((left, 48), title, font=title_font, fill=BLUE)
    subtitle_lines = textwrap.wrap(subtitle, width=105)
    y = 108
    for line in subtitle_lines:
        draw.text((left, y), line, font=subtitle_font, fill="#4D5966")
        y += 32
    draw.line((left, y + 10, width - left, y + 10), fill=GRID, width=2)
    return y + 36


def save_bar_chart(
    table: pd.DataFrame,
    label_column: str,
    value_column: str,
    filename: str,
    title: str,
    subtitle: str,
    percent: bool = False,
    color: str = BLUE,
    color_by_label: dict[str, str] | None = None,
    preserve_order: bool = False,
) -> None:
    plot = table[[label_column, value_column]].dropna()
    if not preserve_order:
        plot = plot.sort_values(value_column)
    width = 2200
    row_height = 78
    top_estimate = 200
    bottom = 150
    height = max(900, top_estimate + row_height * len(plot) + bottom)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)

    label_left = 70
    plot_left = 910
    plot_right = 1960
    value_right = 2140
    chart_bottom = top + row_height * len(plot)
    maximum = float(plot[value_column].max()) if len(plot) else 1.0
    scale_max = maximum * 1.12 if maximum > 0 else 1.0
    label_font = image_font(23)
    value_font = image_font(23, bold=True)
    tick_font = image_font(20)

    for step in range(6):
        value = scale_max * step / 5
        x = plot_left + (plot_right - plot_left) * step / 5
        draw.line((x, top, x, chart_bottom), fill=GRID, width=1)
        tick = f"{value:.0%}" if percent else f"{value:.2f}".replace(".", ",")
        box = draw.textbbox((0, 0), tick, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, chart_bottom + 12), tick, font=tick_font, fill="#5A6570")

    for row_index, (_, row) in enumerate(plot.iterrows()):
        value = float(row[value_column])
        label = str(row[label_column])
        y = top + row_index * row_height + 13
        wrapped = textwrap.wrap(label, width=61)[:2]
        label_y = y - (12 if len(wrapped) == 2 else 0)
        for line_index, line in enumerate(wrapped):
            draw.text((label_left, label_y + line_index * 25), line, font=label_font, fill="#27313B")
        bar_width = (plot_right - plot_left) * value / scale_max
        bar_color = color_by_label.get(label, color) if color_by_label else color
        draw.rounded_rectangle(
            (plot_left, y, plot_left + bar_width, y + 38),
            radius=5,
            fill=bar_color,
        )
        value_label = (
            f"{value:.1%}".replace(".", ",")
            if percent
            else f"{value:.3f}".replace(".", ",")
        )
        draw.text((plot_left + bar_width + 14, y + 4), value_label, font=value_font, fill="#27313B")

    axis_label = "Participación de ocupados" if percent else "Índice promedio de exposición"
    axis_box = draw.textbbox((0, 0), axis_label, font=label_font)
    draw.text(
        ((plot_left + plot_right - (axis_box[2] - axis_box[0])) / 2, chart_bottom + 50),
        axis_label,
        font=label_font,
        fill="#3E4A56",
    )
    source = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025)."
    draw.text((70, height - 55), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_percentile_chart(percentiles: pd.DataFrame) -> None:
    width, height = 2200, 1160
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(
        draw,
        "Exposición a IA por percentil de ingreso laboral",
        "Percentiles ponderados; los empates de ingreso permanecen en el mismo grupo, Colombia, 2025.",
        width,
    )
    left, right = 190, 2110
    bottom = 940
    y_max = max(0.55, float(percentiles["exposicion_promedio_4d"].max()) * 1.08)
    tick_font = image_font(21)
    label_font = image_font(24)

    for step in range(6):
        value = y_max * step / 5
        y = bottom - (bottom - top) * step / 5
        draw.line((left, y, right, y), fill=GRID, width=1)
        label = f"{value:.1f}".replace(".", ",")
        draw.text((85, y - 12), label, font=tick_font, fill="#5A6570")
    for percentile in [1, 20, 40, 60, 80, 100]:
        x = left + (right - left) * (percentile - 1) / 99
        draw.line((x, bottom, x, bottom + 8), fill="#71808F", width=2)
        label = str(percentile)
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 16), label, font=tick_font, fill="#5A6570")

    points: list[tuple[float, float]] = []
    for _, row in percentiles.dropna(subset=["exposicion_promedio_4d"]).iterrows():
        x = left + (right - left) * (float(row["percentil_ingreso"]) - 1) / 99
        y = bottom - (bottom - top) * float(row["exposicion_promedio_4d"]) / y_max
        points.append((x, y))
    if len(points) >= 2:
        draw.line(points, fill=BLUE, width=5, joint="curve")
    for x, y in points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=BLUE)
    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_label = "Percentil de ingreso laboral mensual"
    box = draw.textbbox((0, 0), x_label, font=label_font)
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 62), x_label, font=label_font, fill="#3E4A56")
    draw.text((70, height - 55), "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).", font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / "fig_03_percentiles_ingreso.png", dpi=(220, 220))


def build_charts(tables: dict[str, pd.DataFrame]) -> None:
    groups = tables["02_grupos_exposicion"].copy()
    groups["grupo_exposicion_es"] = pd.Categorical(
        groups["grupo_exposicion_es"],
        categories=[GROUP_LABELS[group] for group in GROUP_ORDER],
        ordered=True,
    )
    groups = groups.sort_values("grupo_exposicion_es", na_position="last")
    group_color_map = {
        GROUP_LABELS[group]: GROUP_COLORS[group] for group in GROUP_ORDER
    }
    save_bar_chart(
        groups,
        "grupo_exposicion_es",
        "participacion",
        "fig_01_distribucion_exposicion.png",
        "Distribución de la población ocupada por exposición a IA generativa",
        "Colombia, 2025. Correspondencia exacta a cuatro dígitos; el no cruce se muestra por separado.",
        percent=True,
        color_by_label=group_color_map,
        preserve_order=True,
    )

    quintiles = tables["03_quintiles_ingreso_mensual"].copy()
    quintiles["quintil"] = "Quintil " + quintiles["quintil_ingreso"].astype(str)
    save_bar_chart(
        quintiles,
        "quintil",
        "exposicion_promedio_4d",
        "fig_02_quintiles_ingreso.png",
        "Exposición a IA por quintil de ingreso laboral",
        "Promedio del índice entre ocupados con ingreso y horas válidas, Colombia, 2025.",
        preserve_order=True,
    )

    save_percentile_chart(tables["04_percentiles_ingreso_mensual"])

    save_bar_chart(
        tables["05_departamentos_24"],
        "departamento",
        "exposicion_promedio_4d",
        "fig_04_departamentos.png",
        "Exposición a IA por departamento",
        "Promedio del índice entre ocupados con correspondencia exacta, 24 departamentos, 2025.",
    )
    save_bar_chart(
        tables["06_actividad_economica"],
        "sector",
        "exposicion_promedio_4d",
        "fig_05_actividad_economica.png",
        "Exposición a IA por actividad económica",
        "Promedio del índice entre ocupados con correspondencia exacta, Colombia, 2025.",
    )
    save_bar_chart(
        tables["07_logro_educativo"],
        "educacion",
        "exposicion_promedio_4d",
        "fig_06_logro_educativo.png",
        "Exposición a IA por logro educativo",
        "La base disponible agrupa el logro en seis categorías, Colombia, 2025.",
        preserve_order=True,
    )

    high = tables["11_ocupaciones_alta_exposicion_empleo"].head(15).copy()
    high["ocupacion_plot"] = high["oficio_c8_label"].fillna(
        high["occupation_name_isco08"]
    )
    save_bar_chart(
        high,
        "ocupacion_plot",
        "participacion_empleo",
        "fig_07_ocupaciones_alta_exposicion.png",
        "Ocupaciones de alta exposición con mayor peso en el empleo",
        "Gradientes 3 y 4, ordenadas por participación en la población ocupada, Colombia, 2025.",
        percent=True,
        color=GOLD,
    )


def write_outputs(tables: dict[str, pd.DataFrame]) -> None:
    for name, table in tables.items():
        table.to_csv(TABLE_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    data, crosswalk_4d, _ = load_inputs()
    tables = build_tables(data, crosswalk_4d)
    write_outputs(tables)
    build_charts(tables)
    national = tables["01_resumen_nacional"].iloc[0]
    print("Análisis terminado")
    print(f"Ocupados 2025: {national['ocupados']:,.0f}")
    print(f"Cobertura exacta 4d: {national['cobertura_4d']:.2%}")
    print(f"Exposición promedio (muestra con cruce): {national['exposicion_promedio_4d']:.3f}")
    print(f"Tablas: {TABLE_DIR}")
    print(f"Figuras: {FIG_DIR}")


if __name__ == "__main__":
    main()
