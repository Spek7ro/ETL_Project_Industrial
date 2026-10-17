"""Transform: limpieza y validación de las tablas, límites de sensores y tabla de características."""
import pandas as pd

from src.config import (
    COMPONENTS,
    ERROR_TYPES,
    MACHINE_MODELS,
    NO_FAILURE,
    SAMPLE_EVERY_HOURS,
    SENSORS,
    VALID_RANGES,
)
from src.models.features import KEYS, add_labels, build_features


def _parse_events(df: pd.DataFrame, value_col: str, allowed: list[str], machines: set, report: dict, name: str):
    rows_in = len(df)
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df[value_col] = df[value_col].astype(str).str.strip().str.lower()
    df = df.dropna(subset=["datetime", "machineID"])
    invalid = ~df[value_col].isin(allowed) | ~df["machineID"].isin(machines)
    df = df[~invalid]
    dupes = int(df.duplicated().sum())
    df = df.drop_duplicates().sort_values(KEYS).reset_index(drop=True)
    report[name] = {"rows_in": rows_in, "invalid_removed": int(invalid.sum()), "duplicates_removed": dupes,
                    "rows_out": len(df)}
    return df


def clean_tables(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    report: dict = {}

    machines = raw["machines"].copy()
    machines["model"] = machines["model"].astype(str).str.strip().str.lower()
    machines["age"] = pd.to_numeric(machines["age"], errors="coerce")
    machines = machines[machines["model"].isin(MACHINE_MODELS)].drop_duplicates("machineID")
    machines["age"] = machines["age"].fillna(machines["age"].median())
    report["machines"] = {"rows_in": len(raw["machines"]), "rows_out": len(machines)}
    known = set(machines["machineID"])

    tel = raw["telemetry"].copy()
    rows_in = len(tel)
    tel["datetime"] = pd.to_datetime(tel["datetime"], errors="coerce")
    tel = tel.dropna(subset=["datetime", "machineID"])
    tel = tel[tel["machineID"].isin(known)]
    dupes = int(tel.duplicated(subset=KEYS).sum())
    tel = tel.drop_duplicates(subset=KEYS).sort_values(KEYS).reset_index(drop=True)
    out_of_range = {}
    for s in SENSORS:
        tel[s] = pd.to_numeric(tel[s], errors="coerce")
        lo, hi = VALID_RANGES[s]
        bad = (tel[s] < lo) | (tel[s] > hi)
        out_of_range[s] = int(bad.sum())
        tel.loc[bad, s] = pd.NA
    nulls = {s: int(tel[s].isna().sum()) for s in SENSORS}
    # Huecos de sensor: interpolación temporal dentro de cada máquina
    tel[SENSORS] = tel.groupby("machineID")[SENSORS].transform(lambda c: c.interpolate(limit_direction="both"))
    report["telemetry"] = {
        "rows_in": rows_in, "duplicates_removed": dupes, "out_of_range_set_null": out_of_range,
        "nulls_interpolated": nulls, "rows_out": len(tel),
        "start": tel["datetime"].min().isoformat(), "end": tel["datetime"].max().isoformat(),
    }

    errors = _parse_events(raw["errors"], "errorID", ERROR_TYPES, known, report, "errors")
    maint = _parse_events(raw["maint"], "comp", COMPONENTS, known, report, "maint")
    failures = _parse_events(raw["failures"], "failure", COMPONENTS, known, report, "failures")
    return {"telemetry": tel, "errors": errors, "maint": maint, "failures": failures, "machines": machines}, report


def sensor_limits(telemetry: pd.DataFrame) -> dict:
    """Límites de operación derivados de la distribución horaria de cada sensor:
    alarma en los percentiles 2.5/97.5 y crítico en 0.5/99.5."""
    q = telemetry[SENSORS].quantile([0.005, 0.025, 0.5, 0.975, 0.995])
    return {
        s: {
            "critical_low": round(float(q.loc[0.005, s]), 2),
            "alarm_low": round(float(q.loc[0.025, s]), 2),
            "nominal": round(float(q.loc[0.5, s]), 2),
            "alarm_high": round(float(q.loc[0.975, s]), 2),
            "critical_high": round(float(q.loc[0.995, s]), 2),
        }
        for s in SENSORS
    }


def dataset_summary(tables: dict[str, pd.DataFrame], features: pd.DataFrame) -> dict:
    """Resumen para el dashboard, incluida la 'firma' de cada falla: desviación (en
    desviaciones estándar) de la media de 24 h de cada sensor antes de fallar."""
    normal = features[features["target"] == NO_FAILURE]
    signature = {}
    for comp in COMPONENTS:
        pre = features[features["target"] == comp]
        signature[comp] = {
            s: round(float((pre[f"{s}_mean_24h"].mean() - normal[f"{s}_mean_24h"].mean())
                           / normal[f"{s}_mean_24h"].std()), 2)
            for s in SENSORS
        }
    fails = tables["failures"].merge(tables["machines"], on="machineID")
    return {
        "machines": int(len(tables["machines"])),
        "telemetry_rows": int(len(tables["telemetry"])),
        "start": tables["telemetry"]["datetime"].min().isoformat(),
        "end": tables["telemetry"]["datetime"].max().isoformat(),
        "failures_by_component": tables["failures"]["failure"].value_counts().reindex(COMPONENTS, fill_value=0).to_dict(),
        "failures_by_model": fails["model"].value_counts().reindex(MACHINE_MODELS, fill_value=0).to_dict(),
        "maintenance_by_component": tables["maint"]["comp"].value_counts().reindex(COMPONENTS, fill_value=0).to_dict(),
        "errors_by_type": tables["errors"]["errorID"].value_counts().reindex(ERROR_TYPES, fill_value=0).to_dict(),
        "machines_by_model": tables["machines"]["model"].value_counts().reindex(MACHINE_MODELS, fill_value=0).to_dict(),
        "feature_rows": int(len(features)),
        "positive_rate": round(float((features["target"] != NO_FAILURE).mean()), 4),
        "failure_signature": signature,
    }


def transform(raw: dict[str, pd.DataFrame]):
    tables, report = clean_tables(raw)
    features = build_features(tables["telemetry"], tables["errors"], tables["maint"], tables["machines"])
    # Una fila cada SAMPLE_EVERY_HOURS horas: suficiente resolución, 3 veces menos filas
    features = features[features["datetime"].dt.hour % SAMPLE_EVERY_HOURS == 0]
    features = add_labels(features, tables["failures"])
    report["features"] = {
        "rows": int(len(features)),
        "label_counts": features["target"].value_counts().to_dict(),
    }
    print(f"[transform] {len(features)} filas de características "
          f"({report['features']['label_counts']})")
    return tables, features, sensor_limits(tables["telemetry"]), dataset_summary(tables, features), report
