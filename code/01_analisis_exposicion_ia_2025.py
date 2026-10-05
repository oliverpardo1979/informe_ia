"""Analisis de exposicion a IA generativa para la poblacion ocupada en 2025.

El indicador principal usa exclusivamente la correspondencia exacta a cuatro
digitos entre OFICIO_C8 (CIUO-08 A.C.) y la tabla de exposicion de la OIT. La
imputacion a dos digitos se conserva solo como ejercicio de sensibilidad.

Insumos esperados:
  - CJC-Monitor/Datos/Processed/BaseIA.dta
  - CJC-Monitor/DocumentacionAuxiliar/
    correlativa_IA_ISCO08_GEIH_OFICIO_C8.xlsx
  - informe_ia/sources/ILO_2025_GenAI_scores_ISCO08.json (opcional, para QA)
  - informe_ia/sources/AIOE_CAIOE_theta_for_sharing.xlsx (AIOE de Felten,
    Raj y Seamans 2021, extendido con el parametro de complementariedad
    theta y el indice CAIOE de Pizzinelli et al., en revision)

Las rutas pueden reemplazarse con BASE_IA_PATH, IA_CROSSWALK_PATH y
CJC_MONITOR_ROOT. Ver README.md para las condiciones de uso del archivo
AIOE/CAIOE.
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
AIOE_CAIOE_PATH = ROOT / "sources" / "AIOE_CAIOE_theta_for_sharing.xlsx"

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
    "Not Exposed": "Muy baja o ninguna",
    "Minimal Exposure": "Muy baja o ninguna",
    "Gradient 1": "Baja",
    "Gradient 2": "Media",
    "Gradient 3": "Alta",
    "Gradient 4": "Muy alta",
    "Sin correspondencia 4d": "Sin correspondencia 4d",
}
REPORT_GROUP_ORDER = [
    "Muy baja o ninguna",
    "Baja",
    "Media",
    "Alta",
    "Muy alta",
    "Sin correspondencia 4d",
]
BLUE = "#17365D"
GRID = "#D9DEE5"

QUADRANT_ALTA_COMPLEMENTA = "Alto potencial de automatización, alta complementariedad"
QUADRANT_ALTA_SUSTITUYE = "Alto potencial de automatización, baja complementariedad"
QUADRANT_BAJA_EXPOSICION = "Bajo potencial de automatización"
QUADRANT_SIN_AIOE = "Sin correspondencia AIOE"
QUADRANT_ORDER = [
    QUADRANT_ALTA_COMPLEMENTA,
    QUADRANT_ALTA_SUSTITUYE,
    QUADRANT_BAJA_EXPOSICION,
    QUADRANT_SIN_AIOE,
]
QUADRANT_COLORS = {
    QUADRANT_ALTA_COMPLEMENTA: "#3182BD",
    QUADRANT_ALTA_SUSTITUYE: "#B6423C",
    QUADRANT_BAJA_EXPOSICION: "#D9DDE2",
    QUADRANT_SIN_AIOE: "#666666",
}


def normalize_text(value: object) -> str:
    text = str(value).strip().lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def quadrant_column(quadrant: str) -> str:
    return "participacion_cuadrante_" + normalize_text(quadrant).replace(" ", "_").replace(
        ",", ""
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


def load_aioe_caioe() -> pd.DataFrame:
    """Carga AIOE y CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).

    La hoja ``data_ISCO08`` mezcla códigos ISCO-08 a 4 dígitos con agregados
    jerárquicos a 1-3 dígitos rellenados con ceros; estos últimos no tienen
    puntajes y se descartan con el ``dropna`` sobre ``aioe_all``. El archivo
    también incluye la propia taxonomía de Pizzinelli et al. (``le``,
    ``helc``, ``hehc``) y las medianas globales de referencia que usan para
    construirla (``median_aioe_all``, ``median_theta``), que se conservan
    para comparar con la clasificación recalculada sobre la GEIH.
    """
    raw = pd.read_excel(AIOE_CAIOE_PATH, sheet_name="data_ISCO08")
    raw["isco08"] = pd.to_numeric(raw["isco08"], errors="raise").astype("Int64")
    raw = raw.dropna(subset=["aioe_all"]).copy()
    if raw["isco08"].duplicated().any():
        raise ValueError("El archivo AIOE/CAIOE contiene códigos ISCO-08 duplicados.")
    aioe = raw[
        [
            "isco08",
            "isco08lab",
            "complementarity_theta",
            "aioe_all",
            "aioe_lm",
            "aioe_img",
            "c_aioe",
            "caioe_w50",
            "communication",
            "responsibility",
            "physical_condition",
            "criticality",
            "routine",
            "skills",
            "le",
            "helc",
            "hehc",
            "median_aioe_all",
            "median_theta",
        ]
    ].rename(
        columns={
            "isco08lab": "ai_aioe_isco08lab",
            "complementarity_theta": "ai_theta",
            "aioe_all": "ai_aioe_all",
            "aioe_lm": "ai_aioe_lm",
            "aioe_img": "ai_aioe_img",
            "c_aioe": "ai_caioe",
            "caioe_w50": "ai_caioe_w50",
            "communication": "ai_theta_comunicacion",
            "responsibility": "ai_theta_responsabilidad",
            "physical_condition": "ai_theta_exigencia_fisica",
            "criticality": "ai_theta_criticidad",
            "routine": "ai_theta_rutina",
            "skills": "ai_theta_habilidades",
            "le": "ai_taxonomia_baja_exposicion",
            "helc": "ai_taxonomia_alta_baja_complementariedad",
            "hehc": "ai_taxonomia_alta_alta_complementariedad",
            "median_aioe_all": "ai_aioe_all_mediana_global",
            "median_theta": "ai_theta_mediana_global",
        }
    )
    return aioe


def classify_quadrant(data: pd.DataFrame) -> pd.Series:
    """Cuadrante exposición (AIOE) x complementariedad (theta), sobre la
    mediana ponderada de la población con correspondencia AIOE."""
    matched = data["ai_aioe_all"].notna() & data["ai_theta"].notna()
    if not matched.any():
        return pd.Series(QUADRANT_SIN_AIOE, index=data.index)
    median_aioe = weighted_quantile(
        data.loc[matched, "ai_aioe_all"], data.loc[matched, "fex"], np.array([0.5])
    )[0]
    median_theta = weighted_quantile(
        data.loc[matched, "ai_theta"], data.loc[matched, "fex"], np.array([0.5])
    )[0]
    high_exposure = data["ai_aioe_all"] >= median_aioe
    high_complementarity = data["ai_theta"] >= median_theta
    result = pd.Series(QUADRANT_SIN_AIOE, index=data.index, dtype="object")
    result[matched & ~high_exposure] = QUADRANT_BAJA_EXPOSICION
    result[matched & high_exposure & high_complementarity] = QUADRANT_ALTA_COMPLEMENTA
    result[matched & high_exposure & ~high_complementarity] = QUADRANT_ALTA_SUSTITUYE
    return result


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not BASE_PATH.exists():
        raise FileNotFoundError(f"No existe la base: {BASE_PATH}")
    if not CROSSWALK_PATH.exists():
        raise FileNotFoundError(f"No existe la correlativa: {CROSSWALK_PATH}")
    if not AIOE_CAIOE_PATH.exists():
        raise FileNotFoundError(f"No existe el archivo AIOE/CAIOE: {AIOE_CAIOE_PATH}")

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

    aioe_caioe = load_aioe_caioe()
    data = data.merge(
        aioe_caioe,
        left_on="oficio_c8_4d",
        right_on="isco08",
        how="left",
        validate="m:1",
    )
    data["cuadrante_aioe_caioe"] = classify_quadrant(data)
    data["cuadrante_taxonomia_autor"] = np.select(
        [
            data["ai_taxonomia_baja_exposicion"] == 1,
            data["ai_taxonomia_alta_baja_complementariedad"] == 1,
            data["ai_taxonomia_alta_alta_complementariedad"] == 1,
        ],
        [QUADRANT_BAJA_EXPOSICION, QUADRANT_ALTA_SUSTITUYE, QUADRANT_ALTA_COMPLEMENTA],
        default=QUADRANT_SIN_AIOE,
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
        aioe_matched = part["ai_aioe_all"].notna()
        row["cobertura_aioe"] = part.loc[aioe_matched, "fex"].sum() / total
        row["aioe_promedio"] = weighted_mean(
            part.loc[aioe_matched, "ai_aioe_all"], part.loc[aioe_matched, "fex"]
        )
        row["caioe_promedio"] = weighted_mean(
            part.loc[aioe_matched, "ai_caioe"], part.loc[aioe_matched, "fex"]
        )
        row["theta_promedio"] = weighted_mean(
            part.loc[aioe_matched, "ai_theta"], part.loc[aioe_matched, "fex"]
        )
        for quadrant in QUADRANT_ORDER:
            key = quadrant_column(quadrant)
            row[key] = part.loc[part["cuadrante_aioe_caioe"] == quadrant, "fex"].sum() / total
        complementa = row[quadrant_column(QUADRANT_ALTA_COMPLEMENTA)]
        sustituye = row[quadrant_column(QUADRANT_ALTA_SUSTITUYE)]
        row["razon_complementariedad_sustitucion"] = (
            complementa / sustituye if sustituye else np.nan
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
        data.assign(
            grupo_exposicion_es=data["grupo_exposicion_4d"].map(GROUP_LABELS)
        )
        .groupby("grupo_exposicion_es", as_index=False, dropna=False)
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
        .assign(participacion=lambda x: x["ocupados"] / total_weight)
    )
    groups["orden"] = groups["grupo_exposicion_es"].map(
        {value: index for index, value in enumerate(REPORT_GROUP_ORDER)}
    )
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

    sector_by_quintile = (
        income.groupby(["quintil_ingreso", "sector"], as_index=False)
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
    )
    sector_by_quintile["participacion_quintil"] = sector_by_quintile["ocupados"] / (
        sector_by_quintile.groupby("quintil_ingreso")["ocupados"].transform("sum")
    )
    sector_by_quintile = sector_by_quintile.sort_values(
        ["quintil_ingreso", "ocupados"], ascending=[True, False]
    ).reset_index(drop=True)

    occupations_by_quintile = (
        income.groupby(
            ["quintil_ingreso", "oficio_c8_4d", "oficio_c8_label", "grupo_exposicion_4d"],
            dropna=False,
            as_index=False,
        )
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
    )
    high_exposure_by_quintile = occupations_by_quintile[
        occupations_by_quintile["grupo_exposicion_4d"].isin(["Gradient 3", "Gradient 4"])
    ].sort_values(["quintil_ingreso", "ocupados"], ascending=[True, False]).reset_index(drop=True)

    occupations_aioe_by_quintile = (
        income.groupby(
            ["quintil_ingreso", "oficio_c8_4d", "oficio_c8_label", "cuadrante_aioe_caioe"],
            dropna=False,
            as_index=False,
        )
        .agg(ocupados=("fex", "sum"), observaciones=("persona_id", "size"))
    )
    high_exposure_aioe_by_quintile = occupations_aioe_by_quintile[
        occupations_aioe_by_quintile["cuadrante_aioe_caioe"].isin(
            [QUADRANT_ALTA_COMPLEMENTA, QUADRANT_ALTA_SUSTITUYE]
        )
    ].sort_values(["quintil_ingreso", "ocupados"], ascending=[True, False]).reset_index(drop=True)

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
            aioe_all=("ai_aioe_all", "first"),
            caioe=("ai_caioe", "first"),
            caioe_w50=("ai_caioe_w50", "first"),
            theta=("ai_theta", "first"),
            cuadrante_aioe_caioe=("cuadrante_aioe_caioe", "first"),
        )
        .assign(participacion_empleo=lambda x: x["ocupados"] / total_weight)
    )
    occupations["grupo_exposicion_es"] = occupations["grupo_exposicion_4d"].map(
        GROUP_LABELS
    )
    occupations = occupations.sort_values(
        ["exposicion_promedio_4d", "ocupados"], ascending=[False, False], na_position="last"
    )
    high_employment = occupations[
        occupations["grupo_exposicion_4d"].isin(["Gradient 3", "Gradient 4"])
    ].sort_values("ocupados", ascending=False)

    substitution_risk = occupations[
        occupations["cuadrante_aioe_caioe"] == QUADRANT_ALTA_SUSTITUYE
    ].sort_values("ocupados", ascending=False)
    high_complementarity = occupations[
        occupations["cuadrante_aioe_caioe"] == QUADRANT_ALTA_COMPLEMENTA
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

    aioe_matched = data["ai_aioe_all"].notna()
    aioe_matched_weight = data.loc[aioe_matched, "fex"].sum()

    quadrant_rows = []
    for quadrant in QUADRANT_ORDER:
        part = data[data["cuadrante_aioe_caioe"] == quadrant]
        quadrant_rows.append(
            {
                "cuadrante": quadrant,
                "ocupados": part["fex"].sum(),
                "observaciones": len(part),
                "participacion": part["fex"].sum() / total_weight,
            }
        )
    quadrants = pd.DataFrame(quadrant_rows)
    complementa_share = quadrants.loc[
        quadrants["cuadrante"] == QUADRANT_ALTA_COMPLEMENTA, "participacion"
    ].iloc[0]
    sustituye_share = quadrants.loc[
        quadrants["cuadrante"] == QUADRANT_ALTA_SUSTITUYE, "participacion"
    ].iloc[0]

    concordancia_mask = aioe_matched & data["cuadrante_taxonomia_autor"].notna()
    concordancia_taxonomia = (
        data.loc[
            concordancia_mask
            & (data["cuadrante_aioe_caioe"] == data["cuadrante_taxonomia_autor"]),
            "fex",
        ].sum()
        / data.loc[concordancia_mask, "fex"].sum()
    )

    occupation_level = crosswalk_4d.merge(
        occupations[["oficio_c8_4d", "aioe_all", "caioe", "theta"]],
        left_on="oficio_c8",
        right_on="oficio_c8_4d",
        how="inner",
    ).dropna(subset=["ai_exposure_mean", "aioe_all", "caioe"])
    aioe_caioe_national = pd.DataFrame(
        [
            {
                "anio": YEAR,
                "ocupados_con_aioe": aioe_matched_weight,
                "cobertura_aioe": aioe_matched_weight / total_weight,
                "aioe_all_promedio": weighted_mean(
                    data.loc[aioe_matched, "ai_aioe_all"], data.loc[aioe_matched, "fex"]
                ),
                "caioe_promedio": weighted_mean(
                    data.loc[aioe_matched, "ai_caioe"], data.loc[aioe_matched, "fex"]
                ),
                "caioe_w50_promedio": weighted_mean(
                    data.loc[aioe_matched, "ai_caioe_w50"], data.loc[aioe_matched, "fex"]
                ),
                "theta_promedio": weighted_mean(
                    data.loc[aioe_matched, "ai_theta"], data.loc[aioe_matched, "fex"]
                ),
                "aioe_all_p10": weighted_quantile(
                    data.loc[aioe_matched, "ai_aioe_all"], data.loc[aioe_matched, "fex"], np.array([0.10])
                )[0],
                "aioe_all_p50": weighted_quantile(
                    data.loc[aioe_matched, "ai_aioe_all"], data.loc[aioe_matched, "fex"], np.array([0.50])
                )[0],
                "aioe_all_p90": weighted_quantile(
                    data.loc[aioe_matched, "ai_aioe_all"], data.loc[aioe_matched, "fex"], np.array([0.90])
                )[0],
                "n_ocupaciones_comparadas_con_oit": len(occupation_level),
                "correlacion_pearson_oit_aioe_all": occupation_level["ai_exposure_mean"].corr(
                    occupation_level["aioe_all"], method="pearson"
                ),
                "correlacion_spearman_oit_aioe_all": occupation_level["ai_exposure_mean"].corr(
                    occupation_level["aioe_all"], method="spearman"
                ),
                "correlacion_pearson_oit_caioe": occupation_level["ai_exposure_mean"].corr(
                    occupation_level["caioe"], method="pearson"
                ),
                "correlacion_spearman_oit_caioe": occupation_level["ai_exposure_mean"].corr(
                    occupation_level["caioe"], method="spearman"
                ),
                "participacion_alta_complementariedad": complementa_share,
                "participacion_alta_sustitucion": sustituye_share,
                "razon_complementariedad_sustitucion": (
                    complementa_share / sustituye_share if sustituye_share else np.nan
                ),
                "aioe_all_mediana_global_autor": data["ai_aioe_all_mediana_global"].dropna().iloc[0],
                "theta_mediana_global_autor": data["ai_theta_mediana_global"].dropna().iloc[0],
                "concordancia_con_taxonomia_autor": concordancia_taxonomia,
            }
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
                "cobertura_ponderada_aioe_caioe": aioe_matched_weight / total_weight,
                **qa_ilo,
            }
        ]
    )

    if not (20_000_000 <= total_weight <= 27_000_000):
        raise ValueError(f"El total expandido de 2025 es implausible: {total_weight:,.0f}")
    if matched_weight / total_weight < 0.90:
        raise ValueError("La cobertura ponderada del cruce 4d es inferior a 90%.")
    if aioe_matched_weight / total_weight < 0.90:
        raise ValueError("La cobertura ponderada del cruce AIOE/CAIOE es inferior a 90%.")
    if departments["depto"].nunique() != 24:
        raise ValueError("No están presentes los 24 departamentos esperados.")
    if not np.isclose(groups["participacion"].sum(), 1.0, atol=1e-10):
        raise ValueError("Las participaciones por grupo de exposición no suman uno.")
    if not np.isclose(quadrants["participacion"].sum(), 1.0, atol=1e-10):
        raise ValueError("Las participaciones por cuadrante AIOE/CAIOE no suman uno.")

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
        "14_aioe_caioe_resumen_nacional": aioe_caioe_national,
        "15_cuadrantes_exposicion_complementariedad": quadrants,
        "16_ocupaciones_riesgo_sustitucion_empleo": substitution_risk,
        "17_ocupaciones_alta_complementariedad_empleo": high_complementarity,
        "18_actividad_economica_por_quintil": sector_by_quintile,
        "19_ocupaciones_alta_exposicion_por_quintil": high_exposure_by_quintile,
        "20_ocupaciones_alta_exposicion_aioe_por_quintil": high_exposure_aioe_by_quintile,
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
    """Encabezado centrado, en la línea visual de identidad del CJC (azul oscuro)."""
    margin = 70
    title_font = image_font(38, bold=True)
    subtitle_font = image_font(24)

    title_lines = textwrap.wrap(title, width=70)
    y = 44
    for line in title_lines:
        box = draw.textbbox((0, 0), line, font=title_font)
        line_w = box[2] - box[0]
        draw.text(((width - line_w) / 2, y), line, font=title_font, fill=BLUE)
        y += 46

    y += 12
    subtitle_lines = textwrap.wrap(subtitle, width=105)
    for line in subtitle_lines:
        box = draw.textbbox((0, 0), line, font=subtitle_font)
        line_w = box[2] - box[0]
        draw.text(((width - line_w) / 2, y), line, font=subtitle_font, fill="#4D5966")
        y += 32
    draw.line((margin, y + 10, width - margin, y + 10), fill=GRID, width=1)
    return y + 55


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
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
    axis_label: str | None = None,
    min_height: int = 900,
) -> None:
    plot = table[[label_column, value_column]].dropna()
    if not preserve_order:
        plot = plot.sort_values(value_column)
    width = 2200
    row_height = 78
    top_estimate = 200
    bottom = 150
    height = max(min_height, top_estimate + row_height * len(plot) + bottom)
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
        if percent:
            tick = (
                f"{value:.1%}".replace(".", ",")
                if scale_max < 0.10
                else f"{value:.0%}"
            )
        else:
            tick = f"{value:.2f}".replace(".", ",")
        box = draw.textbbox((0, 0), tick, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, chart_bottom + 12), tick, font=tick_font, fill="#5A6570")
    draw.line((plot_left, chart_bottom, plot_right, chart_bottom), fill="#71808F", width=1)

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

    if axis_label is None:
        axis_label = (
            "Participación de ocupados"
            if percent
            else "Puntaje promedio de potencial de automatización (0 a 1)"
        )
    axis_box = draw.textbbox((0, 0), axis_label, font=label_font)
    draw.text(
        ((plot_left + plot_right - (axis_box[2] - axis_box[0])) / 2, chart_bottom + 50),
        axis_label,
        font=label_font,
        fill="#3E4A56",
    )
    draw.text((70, height - 55), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_percentile_chart(
    percentiles: pd.DataFrame,
    value_column: str = "exposicion_promedio_4d",
    filename: str = "fig_03_percentiles_ingreso.png",
    title: str = "Puntaje de potencial de automatización por percentil de ingreso laboral",
    subtitle: str = "Promedio ponderado del puntaje ocupacional (0 a 1); los empates de ingreso permanecen en el mismo grupo, Colombia, 2025.",
    y_label_format: str = "{:.1f}",
    min_y_max: float = 0.55,
    y_min: float = 0.0,
    color: str = BLUE,
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
) -> None:
    width, height = 2200, 1160
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)
    left, right = 190, 2110
    bottom = 940
    y_max = max(min_y_max, float(percentiles[value_column].max()) * 1.08)
    y_span = y_max - y_min
    tick_font = image_font(21)
    label_font = image_font(24)

    for step in range(6):
        value = y_min + y_span * step / 5
        y = bottom - (bottom - top) * step / 5
        label = y_label_format.format(value).replace(".", ",")
        draw.text((85, y - 12), label, font=tick_font, fill="#5A6570")
    for percentile in [1, 20, 40, 60, 80, 100]:
        x = left + (right - left) * (percentile - 1) / 99
        draw.line((x, bottom, x, bottom + 8), fill="#71808F", width=2)
        label = str(percentile)
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 16), label, font=tick_font, fill="#5A6570")

    points: list[tuple[float, float]] = []
    for _, row in percentiles.dropna(subset=[value_column]).iterrows():
        x = left + (right - left) * (float(row["percentil_ingreso"]) - 1) / 99
        y = bottom - (bottom - top) * (float(row[value_column]) - y_min) / y_span
        points.append((x, y))
    if len(points) >= 2:
        draw.line(points, fill=color, joint="curve", width=5)
    for x, y in points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_label = "Percentil de ingreso laboral mensual"
    box = draw.textbbox((0, 0), x_label, font=label_font)
    draw.text(((left + right - (box[2] - box[0])) / 2, bottom + 62), x_label, font=label_font, fill="#3E4A56")
    draw.text((70, height - 55), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def _paste_rotated_label(
    image: Image.Image,
    tick_x: float,
    tick_y: float,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    angle: float = 45,
) -> None:
    """Pega ``text`` rotado, con su esquina superior derecha anclada en (tick_x, tick_y)."""
    tmp = Image.new("RGBA", (500, 70), (255, 255, 255, 0))
    ImageDraw.Draw(tmp).text((2, 2), text, font=font, fill=fill)
    bbox = tmp.getbbox()
    if bbox is None:
        return
    tmp = tmp.crop(bbox)
    rotated = tmp.rotate(angle, expand=True, resample=Image.BICUBIC)
    image.paste(rotated, (int(tick_x - rotated.width), int(tick_y)), rotated)


def save_vertical_bar_chart(
    table: pd.DataFrame,
    label_column: str,
    value_column: str,
    filename: str,
    title: str,
    subtitle: str,
    percent: bool = False,
    color: str = BLUE,
    preserve_order: bool = False,
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
    axis_label: str | None = None,
    label_angle: float = 48,
) -> None:
    """Gráfico de columnas (categorías en el eje horizontal), pensado para
    listas largas de categorías (ej. departamentos) que en formato de barras
    horizontales ocupan demasiado alto. Las etiquetas de categoría se
    rotan para que quepan sin superponerse."""
    plot = table[[label_column, value_column]].dropna().reset_index(drop=True)
    if not preserve_order:
        plot = plot.sort_values(value_column, ascending=False).reset_index(drop=True)
    n = len(plot)

    width = max(2200, 95 * n + 260)
    height = 1300
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)

    margin_left, margin_right = 110, 60
    bottom = height - 300
    plot_left, plot_right = margin_left, width - margin_right
    maximum = float(plot[value_column].max()) if n else 1.0
    scale_max = maximum * 1.15 if maximum > 0 else 1.0

    tick_font = image_font(20)
    label_font = image_font(21)
    value_font = image_font(19, bold=True)

    for step in range(6):
        value = scale_max * step / 5
        y = bottom - (bottom - top) * step / 5
        tick = f"{value:.0%}" if percent else f"{value:.2f}".replace(".", ",")
        box = draw.textbbox((0, 0), tick, font=tick_font)
        draw.text((margin_left - 14 - (box[2] - box[0]), y - 10), tick, font=tick_font, fill="#5A6570")

    slot_width = (plot_right - plot_left) / n
    bar_width = slot_width * 0.55
    for i, row in plot.iterrows():
        value = float(row[value_column])
        label = str(row[label_column])
        x_center = plot_left + slot_width * (i + 0.5)
        bar_height = (bottom - top) * value / scale_max
        draw.rounded_rectangle(
            (x_center - bar_width / 2, bottom - bar_height, x_center + bar_width / 2, bottom),
            radius=4,
            fill=color,
        )
        value_label = f"{value:.1%}".replace(".", ",") if percent else f"{value:.3f}".replace(".", ",")
        box = draw.textbbox((0, 0), value_label, font=value_font)
        draw.text((x_center - (box[2] - box[0]) / 2, bottom - bar_height - 26), value_label, font=value_font, fill="#27313B")
        _paste_rotated_label(image, x_center + 8, bottom + 10, label, label_font, "#27313B", angle=label_angle)

    draw = ImageDraw.Draw(image)
    draw.line((plot_left, bottom, plot_right, bottom), fill="#71808F", width=2)
    draw.line((plot_left, top, plot_left, bottom), fill="#71808F", width=2)

    if axis_label is None:
        axis_label = "Participación de ocupados" if percent else "Puntaje promedio de potencial de automatización (0 a 1)"
    axis_font = image_font(22)
    draw.text((plot_left, top - 32), axis_label, font=axis_font, fill="#3E4A56")

    draw.text((70, height - 45), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def _draw_bar_panel(
    draw: ImageDraw.ImageDraw,
    table: pd.DataFrame,
    label_column: str,
    value_column: str,
    panel_title: str,
    box_left: float,
    box_right: float,
    top: float,
    row_height: float,
    scale_max: float,
    label_width: float,
    value_width: float,
    color: str,
    percent: bool,
    color_by_label: dict[str, str] | None = None,
    color_column: str | None = None,
) -> None:
    label_font = image_font(23)
    value_font = image_font(23, bold=True)
    tick_font = image_font(20)
    title_font = image_font(27, bold=True)

    draw.text((box_left, top - 44), panel_title, font=title_font, fill=BLUE)

    plot_left = box_left + label_width
    plot_right = box_right - value_width
    chart_bottom = top + row_height * len(table)

    for step in range(6):
        value = scale_max * step / 5
        x = plot_left + (plot_right - plot_left) * step / 5
        tick = f"{value:.0%}" if percent else f"{value:.2f}".replace(".", ",")
        box = draw.textbbox((0, 0), tick, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, chart_bottom + 12), tick, font=tick_font, fill="#5A6570")
    draw.line((plot_left, chart_bottom, plot_right, chart_bottom), fill="#71808F", width=1)

    for row_index, (_, row) in enumerate(table.iterrows()):
        value = float(row[value_column])
        label = str(row[label_column])
        y = top + row_index * row_height + 10
        wrapped = textwrap.wrap(label, width=24)[:3]
        label_y = y - 12 * (len(wrapped) - 1)
        for line_index, line in enumerate(wrapped):
            draw.text((box_left, label_y + line_index * 25), line, font=label_font, fill="#27313B")
        bar_width = (plot_right - plot_left) * value / scale_max
        bar_color = color_by_label.get(row[color_column], color) if (color_by_label and color_column) else color
        draw.rounded_rectangle((plot_left, y, plot_left + bar_width, y + 34), radius=5, fill=bar_color)
        value_label = f"{value:.1%}".replace(".", ",") if percent else f"{value:.3f}".replace(".", ",")
        draw.text((plot_left + bar_width + 12, y + 3), value_label, font=value_font, fill="#27313B")


def save_multi_panel_bar_chart(
    panels: list[tuple[pd.DataFrame, str, str, str]],
    filename: str,
    title: str,
    subtitle: str,
    percent: bool = False,
    color: str = BLUE,
    axis_label: str | None = None,
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
    label_widths: list[float] | None = None,
    row_height: float = 92,
    color_by_label: dict[str, str] | None = None,
    color_column: str | None = None,
) -> None:
    """Figura de N paneles uno al lado del otro, con el mismo eje.

    ``panels`` es una lista de ``(tabla, columna_etiqueta, columna_valor,
    titulo_panel)``. Todos los paneles comparten la misma escala del eje
    de valores para que sean comparables entre sí. Si se pasa
    ``color_column``/``color_by_label``, cada barra se colorea según el
    valor de esa columna (misma clave en todos los paneles).
    """
    keep_extra = [color_column] if color_column else []
    cleaned = [
        (table[[label_col, value_col] + keep_extra].dropna(subset=[label_col, value_col]), label_col, value_col, panel_title)
        for table, label_col, value_col, panel_title in panels
    ]
    if label_widths is None:
        label_widths = [260] * len(cleaned)

    width = max(2600, 1000 * len(cleaned))
    top_estimate = 260 + (54 if color_by_label else 0)
    bottom_margin = 170
    n_rows = max(len(table) for table, _, _, _ in cleaned)
    height = top_estimate + row_height * n_rows + bottom_margin
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)
    top += 40

    if color_by_label:
        legend_font = image_font(20)
        legend_x = width - 70
        legend_y = top - 46
        for lbl in reversed(list(color_by_label.keys())):
            box = draw.textbbox((0, 0), lbl, font=legend_font)
            text_w = box[2] - box[0]
            legend_x -= text_w
            draw.text((legend_x, legend_y), lbl, font=legend_font, fill="#3E4A56")
            legend_x -= 26
            draw.ellipse((legend_x, legend_y + 2, legend_x + 16, legend_y + 18), fill=color_by_label[lbl])
            legend_x -= 24
        # Deja una fila completa de aire entre la leyenda y los titulos de
        # cada panel (que se dibujan en top-44): sin este espacio, un panel
        # a la derecha puede arrancar justo debajo del texto de la leyenda.
        top += 54

    scale_max = max(float(table[value_col].max()) for table, _, value_col, _ in cleaned) * 1.15

    panel_gap = 70
    margin = 70
    panel_width = (width - 2 * margin - panel_gap * (len(cleaned) - 1)) / len(cleaned)
    boxes = []
    for i in range(len(cleaned)):
        box_left = margin + i * (panel_width + panel_gap)
        boxes.append((box_left, box_left + panel_width))

    value_width = 110
    for (table, label_col, value_col, panel_title), (box_left, box_right), label_width in zip(cleaned, boxes, label_widths):
        _draw_bar_panel(
            draw, table, label_col, value_col, panel_title,
            box_left, box_right, top, row_height, scale_max,
            label_width=label_width, value_width=value_width, color=color, percent=percent,
            color_by_label=color_by_label, color_column=color_column,
        )

    if axis_label is None:
        axis_label = "Participación de ocupados" if percent else "Puntaje promedio de potencial de automatización (0 a 1)"
    label_font = image_font(23)
    chart_bottom = top + row_height * n_rows
    for (box_left, box_right), label_width in zip(boxes, label_widths):
        plot_left = box_left + label_width
        plot_right = box_right - value_width
        axis_box = draw.textbbox((0, 0), axis_label, font=label_font)
        draw.text(
            ((plot_left + plot_right - (axis_box[2] - axis_box[0])) / 2, chart_bottom + 50),
            axis_label,
            font=label_font,
            fill="#3E4A56",
        )

    draw.text((70, height - 55), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_panel_grid_bar_chart(
    rows: list[list[tuple[pd.DataFrame, str, str, str]]],
    filename: str,
    title: str,
    subtitle: str,
    percent: bool = False,
    color: str = BLUE,
    axis_label: str | None = None,
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
    label_widths: list[list[float]] | None = None,
) -> None:
    """Figura de paneles organizados en filas (ej. 2 arriba y 1 abajo).

    ``rows`` es una lista de filas; cada fila es una lista de paneles
    ``(tabla, columna_etiqueta, columna_valor, titulo_panel)`` que se
    reparten el ancho de esa fila en partes iguales. Todos los paneles,
    en todas las filas, comparten la misma escala del eje de valores.
    """
    cleaned_rows = [
        [(table[[label_col, value_col]].dropna(), label_col, value_col, panel_title) for table, label_col, value_col, panel_title in row]
        for row in rows
    ]
    if label_widths is None:
        label_widths = [[260] * len(row) for row in cleaned_rows]

    width = 2600
    row_height = 92
    margin = 70
    panel_gap = 70
    row_gap = 90
    header_space = 50
    axis_space = 100
    value_width = 110

    scale_max = max(
        float(table[value_col].max())
        for row in cleaned_rows
        for table, _, value_col, _ in row
    ) * 1.15

    label_font = image_font(23)
    if axis_label is None:
        axis_label = "Participación de ocupados" if percent else "Puntaje promedio de potencial de automatización (0 a 1)"

    top_estimate = 260
    row_heights = []
    for row in cleaned_rows:
        n_rows = max(len(table) for table, _, _, _ in row)
        row_heights.append(header_space + row_height * n_rows + axis_space)
    height = top_estimate + sum(row_heights) + row_gap * (len(cleaned_rows) - 1) + 40

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)
    top += 40

    y_cursor = top
    for row, widths, row_extent in zip(cleaned_rows, label_widths, row_heights):
        panel_top = y_cursor + header_space
        panel_width = (width - 2 * margin - panel_gap * (len(row) - 1)) / len(row)
        for i, ((table, label_col, value_col, panel_title), label_width) in enumerate(zip(row, widths)):
            box_left = margin + i * (panel_width + panel_gap)
            box_right = box_left + panel_width
            _draw_bar_panel(
                draw, table, label_col, value_col, panel_title,
                box_left, box_right, panel_top, row_height, scale_max,
                label_width=label_width, value_width=value_width, color=color, percent=percent,
            )
            plot_left = box_left + label_width
            plot_right = box_right - value_width
            chart_bottom = panel_top + row_height * len(table)
            axis_box = draw.textbbox((0, 0), axis_label, font=label_font)
            draw.text(
                ((plot_left + plot_right - (axis_box[2] - axis_box[0])) / 2, chart_bottom + 50),
                axis_label,
                font=label_font,
                fill="#3E4A56",
            )
        y_cursor += row_extent + row_gap

    draw.text((70, height - 55), source, font=image_font(20), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def save_two_panel_bar_chart(
    panel_a: tuple[pd.DataFrame, str, str, str],
    panel_b: tuple[pd.DataFrame, str, str, str],
    filename: str,
    title: str,
    subtitle: str,
    percent: bool = False,
    color: str = BLUE,
    axis_label: str | None = None,
    source: str = "Fuente: cálculos propios con GEIH 2025 del DANE e índice OIT-NASK (2025).",
) -> None:
    """Figura de dos paneles (A y B) uno al lado del otro, con el mismo eje."""
    save_multi_panel_bar_chart(
        [panel_a, panel_b],
        filename,
        title,
        subtitle,
        percent=percent,
        color=color,
        axis_label=axis_label,
        source=source,
        label_widths=[230, 330],
    )


def save_scatter_chart(
    table: pd.DataFrame,
    x_column: str,
    y_column: str,
    size_column: str,
    color_column: str,
    filename: str,
    title: str,
    subtitle: str,
    color_map: dict[str, str],
    x_label: str,
    y_label: str,
    x_vline: float | None = None,
    y_hline: float | None = None,
    quadrant_labels: dict[str, str] | None = None,
    quadrant_tints: dict[str, str] | None = None,
    callouts: list[dict] | None = None,
) -> None:
    """Cuadrante 2x2 con las ocupaciones más grandes rotuladas directamente.

    ``quadrant_labels``/``quadrant_tints`` esperan las llaves
    "arriba_derecha", "abajo_derecha" e "izquierda" (esta última cubre
    todo el lado izquierdo de ``x_vline``, sin dividir por ``y_hline``).
    ``callouts`` es una lista de diccionarios con ``x``, ``y``, ``text``
    y, opcionalmente, ``dx``/``dy`` (desplazamiento en píxeles de la
    etiqueta respecto al punto).
    """
    plot = table.dropna(subset=[x_column, y_column, size_column]).copy()
    width, height = 2200, 1500
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = draw_header(draw, title, subtitle, width)

    left, right = 230, 2120
    bottom = height - 170
    x_min, x_max = float(plot[x_column].min()), float(plot[x_column].max())
    y_min, y_max = float(plot[y_column].min()), float(plot[y_column].max())
    x_pad = (x_max - x_min) * 0.08 or 0.1
    y_pad = (y_max - y_min) * 0.10 or 0.1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    def to_x(value: float) -> float:
        return left + (right - left) * (value - x_min) / (x_max - x_min)

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * (value - y_min) / (y_max - y_min)

    tick_font = image_font(20)
    label_font = image_font(26, bold=True)
    quadrant_font = image_font(30, bold=True)
    callout_font = image_font(21, bold=True)

    if x_vline is not None and y_hline is not None:
        tints = quadrant_tints or {}
        x_split = to_x(x_vline)
        y_split = to_y(y_hline)
        if "izquierda" in tints:
            draw.rectangle((left, top, x_split, bottom), fill=tints["izquierda"])
        if "arriba_derecha" in tints:
            draw.rectangle((x_split, top, right, y_split), fill=tints["arriba_derecha"])
        if "abajo_derecha" in tints:
            draw.rectangle((x_split, y_split, right, bottom), fill=tints["abajo_derecha"])

    for step in range(6):
        x_value = x_min + (x_max - x_min) * step / 5
        x = to_x(x_value)
        tick = f"{x_value:.2f}".replace(".", ",")
        box = draw.textbbox((0, 0), tick, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 12), tick, font=tick_font, fill="#5A6570")
        y_value = y_min + (y_max - y_min) * step / 5
        y = to_y(y_value)
        tick_y = f"{y_value:.2f}".replace(".", ",")
        box_y = draw.textbbox((0, 0), tick_y, font=tick_font)
        draw.text((left - 14 - (box_y[2] - box_y[0]), y - 10), tick_y, font=tick_font, fill="#5A6570")

    if quadrant_labels:
        positions = {
            "izquierda": ((left + to_x(x_vline)) / 2 if x_vline is not None else left, top + 46),
            "arriba_derecha": ((to_x(x_vline) + right) / 2 if x_vline is not None else right, top + 46),
            "abajo_derecha": ((to_x(x_vline) + right) / 2 if x_vline is not None else right, bottom - 46),
        }
        for key, text in quadrant_labels.items():
            if key not in positions:
                continue
            cx, cy = positions[key]
            box = draw.textbbox((0, 0), text, font=quadrant_font)
            draw.text((cx - (box[2] - box[0]) / 2, cy), text, font=quadrant_font, fill="#8B95A1")

    if x_vline is not None:
        x = to_x(x_vline)
        draw.line((x, top, x, bottom), fill="#71808F", width=3)
    if y_hline is not None:
        y = to_y(y_hline)
        draw.line((to_x(x_vline) if x_vline is not None else left, y, right, y), fill="#71808F", width=3)

    max_size = float(plot[size_column].max()) or 1.0
    for _, row in plot.iterrows():
        x = to_x(float(row[x_column]))
        y = to_y(float(row[y_column]))
        radius = 4 + 26 * (float(row[size_column]) / max_size) ** 0.5
        color = color_map.get(row[color_column], BLUE)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="white", width=1)

    for callout in callouts or []:
        x = to_x(float(callout["x"]))
        y = to_y(float(callout["y"]))
        dx = callout.get("dx", 20)
        dy = callout.get("dy", -20)
        text = callout["text"]
        box = draw.textbbox((0, 0), text, font=callout_font)
        text_w, text_h = box[2] - box[0], box[3] - box[1]
        tx = x + dx - (text_w if dx < 0 else 0)
        ty = y + dy - (text_h if dy < 0 else 0)
        draw.line((x, y, tx + (text_w / 2 if dx < 0 else 0), ty + (text_h if dy < 0 else 0)), fill="#3E4A56", width=1)
        draw.rectangle((tx - 4, ty - 2, tx + text_w + 4, ty + text_h + 4), fill="white", outline="#C7CDD3")
        draw.text((tx, ty), text, font=callout_font, fill="#1F2933")

    draw.line((left, top, left, bottom), fill="#71808F", width=2)
    draw.line((left, bottom, right, bottom), fill="#71808F", width=2)
    x_box = draw.textbbox((0, 0), x_label, font=label_font)
    draw.text(((left + right - (x_box[2] - x_box[0])) / 2, bottom + 55), x_label, font=label_font, fill="#27313B")
    draw.text((left, top - 34), y_label, font=label_font, fill="#27313B")

    source = "Fuente: cálculos propios con GEIH 2025, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión). El tamaño del punto es proporcional al empleo."
    draw.text((70, height - 45), source, font=image_font(19), fill="#5A6570")
    image.save(FIG_DIR / filename, dpi=(220, 220))


def build_charts(tables: dict[str, pd.DataFrame]) -> None:
    groups = tables["02_grupos_exposicion"].copy()
    groups["grupo_exposicion_es"] = pd.Categorical(
        groups["grupo_exposicion_es"],
        categories=REPORT_GROUP_ORDER,
        ordered=True,
    )
    groups = groups.sort_values("grupo_exposicion_es", na_position="last")
    save_bar_chart(
        groups,
        "grupo_exposicion_es",
        "participacion",
        "fig_01_distribucion_exposicion.png",
        "Distribución de la población ocupada por potencial de automatización de la IA generativa",
        "Colombia, 2025. Correspondencia exacta a cuatro dígitos; el no cruce se muestra por separado.",
        percent=True,
        color=BLUE,
        preserve_order=True,
    )

    quintiles = tables["03_quintiles_ingreso_mensual"].copy()
    quintiles["quintil"] = "Quintil " + quintiles["quintil_ingreso"].astype(str)
    save_bar_chart(
        quintiles,
        "quintil",
        "exposicion_promedio_4d",
        "fig_02_quintiles_ingreso.png",
        "Puntaje de potencial de automatización por quintil de ingreso laboral",
        "Promedio ponderado del puntaje ocupacional (0 a 1) entre ocupados con ingreso y horas válidas, Colombia, 2025.",
        preserve_order=True,
    )

    save_two_panel_bar_chart(
        (quintiles, "quintil", "exposicion_promedio_4d", "A. Quintil de ingreso laboral"),
        (tables["07_logro_educativo"], "educacion", "exposicion_promedio_4d", "B. Logro educativo"),
        "fig_14_panel_ingreso_educacion.png",
        "Puntaje de potencial de automatización por ingreso laboral y logro educativo",
        "Promedio ponderado del puntaje ocupacional (0 a 1), Colombia, 2025.",
    )

    save_percentile_chart(tables["04_percentiles_ingreso_mensual"])
    save_percentile_chart(
        tables["04_percentiles_ingreso_mensual"],
        value_column="aioe_promedio",
        filename="fig_12_aioe_percentiles_ingreso.png",
        title="AIOE promedio por percentil de ingreso laboral",
        subtitle="Promedio ponderado del AIOE (Felten, Raj y Seamans, 2021); los empates de ingreso permanecen en el mismo grupo, Colombia, 2025.",
        y_label_format="{:.2f}",
        min_y_max=6.6,
        y_min=5.0,
        color=BLUE,
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
    )

    save_vertical_bar_chart(
        tables["05_departamentos_24"],
        "departamento",
        "exposicion_promedio_4d",
        "fig_04_departamentos.png",
        "Puntaje de potencial de automatización por departamento",
        "Promedio ponderado del puntaje ocupacional (0 a 1) entre ocupados con correspondencia exacta, 24 departamentos, 2025.",
    )
    save_bar_chart(
        tables["06_actividad_economica"],
        "sector",
        "exposicion_promedio_4d",
        "fig_05_actividad_economica.png",
        "Puntaje de potencial de automatización por actividad económica",
        "Promedio ponderado del puntaje ocupacional (0 a 1) entre ocupados con correspondencia exacta, Colombia, 2025.",
    )
    save_bar_chart(
        tables["07_logro_educativo"],
        "educacion",
        "exposicion_promedio_4d",
        "fig_06_logro_educativo.png",
        "Puntaje de potencial de automatización por logro educativo",
        "La base disponible agrupa el logro en seis categorías, Colombia, 2025.",
        preserve_order=True,
    )

    sex = tables["08_sexo"].copy()
    sex["sexo"] = pd.Categorical(
        sex["sexo"],
        categories=["Mujer", "Hombre"],
        ordered=True,
    )
    sex = sex.sort_values("sexo")
    save_bar_chart(
        sex,
        "sexo",
        "exposicion_promedio_4d",
        "fig_07_genero.png",
        "Puntaje de potencial de automatización por género",
        "Promedio ponderado del puntaje ocupacional (0 a 1), mujeres y hombres, Colombia, 2025.",
        preserve_order=True,
    )

    formality_2 = tables["09_formalidad"][tables["09_formalidad"]["formalidad"].isin(["Formal", "Informal"])].copy()
    formality_2["formalidad"] = pd.Categorical(formality_2["formalidad"], categories=["Formal", "Informal"], ordered=True)
    formality_2 = formality_2.sort_values("formalidad")
    save_two_panel_bar_chart(
        (sex, "sexo", "exposicion_promedio_4d", "A. Género"),
        (formality_2, "formalidad", "exposicion_promedio_4d", "B. Formalidad"),
        "fig_15_panel_genero_formalidad.png",
        "Puntaje de potencial de automatización por género y formalidad",
        "Promedio ponderado del puntaje ocupacional (0 a 1), Colombia, 2025.",
    )

    high = tables["11_ocupaciones_alta_exposicion_empleo"].head(12).copy()
    high["ocupacion_plot"] = high["oficio_c8_label"].fillna(
        high["occupation_name_isco08"]
    )
    save_bar_chart(
        high,
        "ocupacion_plot",
        "participacion_empleo",
        "fig_08_ocupaciones_alta_exposicion.png",
        "Ocupaciones con alto potencial de automatización y mayor peso en el empleo",
        "Alto potencial de automatización, ordenadas por participación en la población ocupada, Colombia, 2025.",
        percent=True,
        color=BLUE,
    )

    occupations_aioe = tables["10_ocupaciones"].dropna(subset=["aioe_all", "theta"]).copy()
    median_aioe = weighted_quantile(
        occupations_aioe["aioe_all"], occupations_aioe["ocupados"], np.array([0.5])
    )[0]
    median_theta = weighted_quantile(
        occupations_aioe["theta"], occupations_aioe["ocupados"], np.array([0.5])
    )[0]
    occupation_callouts = [
        {"label": "Vendedores y auxiliares de venta en tiendas, almacenes y afines", "text": "Vendedores en tiendas", "dx": 15, "dy": 48},
        {"label": "Personal doméstico", "text": "Personal doméstico", "dx": 25, "dy": 10},
        {"label": "Obreros y peones de explotaciones agrícolas", "text": "Peones agrícolas", "dx": 25, "dy": -48},
        {"label": "Guardias de seguridad", "text": "Guardias de seguridad", "dx": 15, "dy": -44},
        {"label": "Gerentes de comercios al por mayor y al por menor", "text": "Gerentes y comerciantes de comercio", "dx": -20, "dy": -48},
        {"label": "Oficinistas generales", "text": "Oficinistas generales", "dx": -30, "dy": 42},
        {"label": "Representantes comerciales", "text": "Representantes comerciales", "dx": -40, "dy": -44},
    ]
    callouts = []
    for item in occupation_callouts:
        match = occupations_aioe.loc[occupations_aioe["oficio_c8_label"] == item["label"]]
        if match.empty:
            continue
        row = match.iloc[0]
        callouts.append(
            {
                "x": float(row["aioe_all"]),
                "y": float(row["theta"]),
                "text": item["text"],
                "dx": item["dx"],
                "dy": item["dy"],
            }
        )
    save_scatter_chart(
        occupations_aioe,
        "aioe_all",
        "theta",
        "ocupados",
        "cuadrante_aioe_caioe",
        "fig_09_cuadrante_exposicion_complementariedad.png",
        "Potencial de automatización (AIOE) y complementariedad potencial por ocupación",
        "Cada punto es una ocupación a cuatro dígitos; se rotulan las de mayor empleo en cada zona. Colombia, 2025.",
        QUADRANT_COLORS,
        "AIOE (potencial de automatización)",
        "Complementariedad potencial (theta)",
        x_vline=median_aioe,
        y_hline=median_theta,
        quadrant_labels={
            "izquierda": "BAJO POTENCIAL DE AUTOMATIZACIÓN",
            "arriba_derecha": "ALTA COMPLEMENTARIEDAD",
            "abajo_derecha": "RIESGO DE SUSTITUCIÓN",
        },
        quadrant_tints={
            "izquierda": "#F2F4F6",
            "arriba_derecha": "#EAF2FB",
            "abajo_derecha": "#FBECEA",
        },
        callouts=callouts,
    )

    risk_column = quadrant_column(QUADRANT_ALTA_SUSTITUYE)
    save_bar_chart(
        tables["06_actividad_economica"].sort_values(risk_column),
        "sector",
        risk_column,
        "fig_10_riesgo_sustitucion_sector.png",
        "Participación del empleo en riesgo de sustitución por actividad económica",
        "Ocupados en el cuadrante de alto potencial de automatización (AIOE) y baja complementariedad potencial (CAIOE/theta), Colombia, 2025.",
        percent=True,
        color=BLUE,
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
    )

    education_ratio = tables["07_logro_educativo"]
    education_ratio = education_ratio[education_ratio["observaciones"] >= 100].copy()
    save_bar_chart(
        education_ratio,
        "educacion",
        "razon_complementariedad_sustitucion",
        "fig_11_razon_complementariedad_educacion.png",
        "Razón entre complementariedad y riesgo de sustitución por logro educativo",
        "Participación en el cuadrante de alta complementariedad dividida por la de riesgo de sustitución; valores por encima de 1 indican más empleo complementario que en riesgo, Colombia, 2025.",
        preserve_order=True,
        color=BLUE,
        axis_label="Razón complementariedad / riesgo de sustitución",
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
    )

    income_ratio = tables["03_quintiles_ingreso_mensual"].copy()
    income_ratio["quintil"] = income_ratio["quintil_ingreso"].map(
        {1: "Quintil 1 (más bajo)", 2: "Quintil 2", 3: "Quintil 3", 4: "Quintil 4", 5: "Quintil 5 (más alto)"}
    )
    save_bar_chart(
        income_ratio.sort_values("quintil_ingreso"),
        "quintil",
        "razon_complementariedad_sustitucion",
        "fig_16_razon_complementariedad_ingreso.png",
        "Complementariedad/riesgo por quintil de ingreso",
        "Participación en el cuadrante de alta complementariedad dividida por la de riesgo de sustitución; valores por encima de 1 indican más empleo complementario que en riesgo, Colombia, 2025.",
        preserve_order=True,
        color=BLUE,
        axis_label="Razón complementariedad / riesgo de sustitución",
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
        min_height=680,
    )

    save_panel_grid_bar_chart(
        [
            [
                (sex, "sexo", "razon_complementariedad_sustitucion", "A. Género"),
                (formality_2, "formalidad", "razon_complementariedad_sustitucion", "B. Formalidad"),
            ],
            [
                (education_ratio, "educacion", "razon_complementariedad_sustitucion", "C. Logro educativo"),
            ],
        ],
        "fig_17_razon_complementariedad_relativa.png",
        "Complementariedad relativa por género, formalidad y logro educativo",
        "Razón entre la participación en el cuadrante de alta complementariedad y la de riesgo de sustitución; valores por encima de 1 indican más empleo complementario que en riesgo, Colombia, 2025.",
        color=BLUE,
        axis_label="Razón complementariedad / riesgo de sustitución",
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
        label_widths=[[190, 190], [260]],
    )

    department_ratio = tables["05_departamentos_24"].copy()
    save_vertical_bar_chart(
        department_ratio,
        "departamento",
        "razon_complementariedad_sustitucion",
        "fig_13_razon_complementariedad_departamento.png",
        "Razón entre complementariedad y riesgo de sustitución por departamento",
        "Participación en el cuadrante de alta complementariedad dividida por la de riesgo de sustitución, 24 departamentos, Colombia, 2025.",
        color=BLUE,
        axis_label="Razón complementariedad / riesgo de sustitución",
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
    )

    sector_by_quintile = tables["18_actividad_economica_por_quintil"]
    q1 = sector_by_quintile[sector_by_quintile["quintil_ingreso"] == 1].sort_values(
        "ocupados", ascending=False
    ).copy()
    q5 = sector_by_quintile[sector_by_quintile["quintil_ingreso"] == 5].sort_values(
        "ocupados", ascending=False
    ).copy()
    q1["ocupados_millones"] = q1["ocupados"] / 1_000_000
    q5["ocupados_millones"] = q5["ocupados"] / 1_000_000
    save_multi_panel_bar_chart(
        [
            (q1, "sector", "ocupados_millones", "A. Quintil 1 (más pobre)"),
            (q5, "sector", "ocupados_millones", "B. Quintil 5 (más rico)"),
        ],
        "fig_18_actividad_economica_por_quintil.png",
        "¿En qué actividad económica están los más pobres y los más ricos?",
        "Ocupados por actividad económica dentro de cada quintil de ingreso laboral, misma escala en ambos paneles, Colombia, 2025.",
        color=BLUE,
        axis_label="Ocupados (millones)",
        label_widths=[300, 300],
        row_height=78,
    )

    high_exposure_by_quintile = tables["19_ocupaciones_alta_exposicion_por_quintil"]
    occ_q1 = high_exposure_by_quintile[
        high_exposure_by_quintile["quintil_ingreso"] == 1
    ].sort_values("ocupados", ascending=False).head(12).copy()
    occ_q5 = high_exposure_by_quintile[
        high_exposure_by_quintile["quintil_ingreso"] == 5
    ].sort_values("ocupados", ascending=False).head(12).copy()
    occ_q1["ocupados_millones"] = occ_q1["ocupados"] / 1_000_000
    occ_q5["ocupados_millones"] = occ_q5["ocupados"] / 1_000_000
    save_multi_panel_bar_chart(
        [
            (occ_q1, "oficio_c8_label", "ocupados_millones", "A. Quintil 1 (más pobre)"),
            (occ_q5, "oficio_c8_label", "ocupados_millones", "B. Quintil 5 (más rico)"),
        ],
        "fig_19_ocupaciones_alta_exposicion_por_quintil.png",
        "Ocupaciones con alto potencial de automatización: más pobres vs. más ricos",
        "Ocupados en ocupaciones con alto potencial de automatización (índice OIT-NASK), dentro de cada quintil de ingreso laboral, misma escala en ambos paneles, Colombia, 2025.",
        color=BLUE,
        axis_label="Ocupados (millones)",
        label_widths=[300, 300],
        row_height=78,
    )

    high_exposure_aioe_by_quintile = tables["20_ocupaciones_alta_exposicion_aioe_por_quintil"]
    aioe_q1 = high_exposure_aioe_by_quintile[
        high_exposure_aioe_by_quintile["quintil_ingreso"] == 1
    ].sort_values("ocupados", ascending=False).head(12).copy()
    aioe_q5 = high_exposure_aioe_by_quintile[
        high_exposure_aioe_by_quintile["quintil_ingreso"] == 5
    ].sort_values("ocupados", ascending=False).head(12).copy()
    aioe_q1["ocupados_millones"] = aioe_q1["ocupados"] / 1_000_000
    aioe_q5["ocupados_millones"] = aioe_q5["ocupados"] / 1_000_000
    save_multi_panel_bar_chart(
        [
            (aioe_q1, "oficio_c8_label", "ocupados_millones", "A. Quintil 1 (más pobre)"),
            (aioe_q5, "oficio_c8_label", "ocupados_millones", "B. Quintil 5 (más rico)"),
        ],
        "fig_20_ocupaciones_alta_exposicion_aioe_por_quintil.png",
        "Ocupaciones con alto potencial de automatización según AIOE: más pobres vs. más ricos",
        "Ocupados en ocupaciones de AIOE alto (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión), dentro de cada quintil de ingreso laboral, misma escala en ambos paneles. Azul: alta complementariedad; rojo: riesgo de sustitución. Colombia, 2025.",
        color=BLUE,
        axis_label="Ocupados (millones)",
        label_widths=[300, 300],
        row_height=78,
        color_by_label={
            QUADRANT_ALTA_COMPLEMENTA: QUADRANT_COLORS[QUADRANT_ALTA_COMPLEMENTA],
            QUADRANT_ALTA_SUSTITUYE: QUADRANT_COLORS[QUADRANT_ALTA_SUSTITUYE],
        },
        color_column="cuadrante_aioe_caioe",
        source="Fuente: cálculos propios con GEIH 2025 del DANE, AIOE/CAIOE (Felten, Raj y Seamans, 2021; Pizzinelli et al., en revisión).",
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
    aioe_national = tables["14_aioe_caioe_resumen_nacional"].iloc[0]
    print("Análisis terminado")
    print(f"Ocupados 2025: {national['ocupados']:,.0f}")
    print(f"Cobertura exacta 4d (OIT): {national['cobertura_4d']:.2%}")
    print(f"Exposición promedio OIT (muestra con cruce): {national['exposicion_promedio_4d']:.3f}")
    print(f"Cobertura AIOE/CAIOE: {aioe_national['cobertura_aioe']:.2%}")
    print(f"AIOE promedio: {aioe_national['aioe_all_promedio']:.3f}")
    print(f"CAIOE promedio: {aioe_national['caioe_promedio']:.3f}")
    print(
        "Correlación OIT-AIOE (Spearman, a nivel ocupación): "
        f"{aioe_national['correlacion_spearman_oit_aioe_all']:.3f}"
    )
    print(f"Tablas: {TABLE_DIR}")
    print(f"Figuras: {FIG_DIR}")


if __name__ == "__main__":
    main()
