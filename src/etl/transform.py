"""Transform: limpieza, validación de calidad y tratamiento de outliers."""
import pandas as pd

from src.config import (
    CATEGORICAL_FEATURES,
    MACHINE_TYPES,
    NUMERIC_FEATURES,
    TARGET,
    VALID_RANGES,
)


def transform(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Devuelve el dataset limpio y un reporte de calidad de datos."""
    report = {"rows_in": int(len(df))}
    df = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET]].copy()

    # Tipos
    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce")
    df["Machine_Type"] = df["Machine_Type"].astype(str).str.strip().str.title()

    # Duplicados
    dupes = int(df.duplicated().sum())
    df = df.drop_duplicates()
    report["duplicates_removed"] = dupes

    # Objetivo inválido o ausente: no se puede imputar
    invalid_target = ~df[TARGET].isin([0, 1])
    report["invalid_target_removed"] = int(invalid_target.sum())
    df = df[~invalid_target]
    df[TARGET] = df[TARGET].astype(int)

    # Tipos de máquina desconocidos
    unknown_type = ~df["Machine_Type"].isin(MACHINE_TYPES)
    report["unknown_machine_type_removed"] = int(unknown_type.sum())
    df = df[~unknown_type]

    # Lecturas fuera de rango físico -> nulas (error de sensor)
    out_of_range = {}
    for col, (lo, hi) in VALID_RANGES.items():
        mask = (df[col] < lo) | (df[col] > hi)
        out_of_range[col] = int(mask.sum())
        df.loc[mask, col] = pd.NA
    report["out_of_range_set_null"] = out_of_range

    # Imputación de nulos con la mediana por tipo de máquina
    report["nulls_imputed"] = {c: int(df[c].isna().sum()) for c in NUMERIC_FEATURES}
    for col in NUMERIC_FEATURES:
        df[col] = df.groupby("Machine_Type")[col].transform(lambda s: s.fillna(s.median()))
        df[col] = df[col].fillna(df[col].median())

    # Winsorización de outliers estadísticos (IQR 3x) para no perder filas
    clipped = {}
    for col in NUMERIC_FEATURES:
        q1, q3 = df[col].quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
        clipped[col] = int(((df[col] < lo) | (df[col] > hi)).sum())
        df[col] = df[col].clip(lo, hi)
    report["outliers_clipped"] = clipped

    df = df.reset_index(drop=True)
    report["rows_out"] = int(len(df))
    report["failure_rate"] = round(float(df[TARGET].mean()), 4) if len(df) else None
    report["stats"] = df[NUMERIC_FEATURES].describe().round(3).to_dict()
    print(f"[transform] {report['rows_in']} -> {report['rows_out']} filas")
    return df, report
