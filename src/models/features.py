"""Ingeniería de características compartida por el ETL y la inferencia en tiempo real.

Para cada máquina e instante t se resume su historia reciente:
- media y desviación de cada sensor en las últimas 3 h y 24 h (ventanas (t-w, t]),
- número de errores de cada tipo en las últimas 24 h,
- días desde el último reemplazo de cada componente,
- modelo y antigüedad de la máquina.

La etiqueta es el componente que falla en (t, t + HORIZON] o "none".
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import COMPONENTS, ERROR_TYPES, HORIZON_HOURS, MACHINE_MODELS, NO_FAILURE, SENSORS

WINDOWS = ["3h", "24h"]
SENSOR_FEATURES = [f"{s}_{stat}_{w}" for w in WINDOWS for s in SENSORS for stat in ("mean", "std")]
ERROR_FEATURES = [f"{e}_count_24h" for e in ERROR_TYPES]
COMPONENT_FEATURES = [f"{c}_days_since" for c in COMPONENTS]
NUMERIC_FEATURES = SENSOR_FEATURES + ERROR_FEATURES + COMPONENT_FEATURES + ["age"]
CATEGORICAL_FEATURES = ["model"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
KEYS = ["machineID", "datetime"]


def build_features(
    telemetry: pd.DataFrame,
    errors: pd.DataFrame,
    maint: pd.DataFrame,
    machines: pd.DataFrame,
    times: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Calcula las características en cada lectura de telemetría.

    `times` restringe la salida a esos instantes (p. ej. el instante actual), pero
    las ventanas se calculan siempre con toda la telemetría recibida.
    """
    telemetry, errors, maint = (_normalize(df) for df in (telemetry, errors, maint))
    tel = telemetry.sort_values(KEYS).reset_index(drop=True)
    out = tel[KEYS].copy()

    indexed = tel.set_index("datetime").groupby("machineID", sort=True)
    for w in WINDOWS:
        roll = indexed[SENSORS].rolling(w)
        means, stds = roll.mean(), roll.std()
        for s in SENSORS:
            out[f"{s}_mean_{w}"] = means[s].to_numpy()
            out[f"{s}_std_{w}"] = stds[s].to_numpy()

    # Errores por hora alineados con la telemetría y suma móvil de 24 h
    aligned = out[KEYS].copy()
    if len(errors):
        err = errors.assign(datetime=errors["datetime"].dt.floor("h"), n=1)
        counts = (
            err.pivot_table(index=KEYS, columns="errorID", values="n", aggfunc="sum")
            .reindex(columns=ERROR_TYPES)
            .fillna(0)
            .reset_index()
        )
        aligned = aligned.merge(counts, on=KEYS, how="left")
    aligned = aligned.reindex(columns=KEYS + ERROR_TYPES).fillna({e: 0.0 for e in ERROR_TYPES})
    rolled = aligned.set_index("datetime").groupby("machineID", sort=True)[ERROR_TYPES].rolling("24h").sum()
    for e in ERROR_TYPES:
        out[f"{e}_count_24h"] = rolled[e].to_numpy()

    # Días desde el último reemplazo de cada componente (mantenimientos <= t)
    by_time = out[KEYS].reset_index().sort_values("datetime")
    for c in COMPONENTS:
        repl = (
            maint.loc[maint["comp"] == c, KEYS]
            .rename(columns={"datetime": "last_repl"})
            .sort_values("last_repl")
        )
        joined = pd.merge_asof(by_time, repl, left_on="datetime", right_on="last_repl", by="machineID")
        days = (joined["datetime"] - joined["last_repl"]).dt.total_seconds() / 86400
        out.loc[joined["index"].to_numpy(), f"{c}_days_since"] = days.to_numpy()

    out = out.merge(machines[["machineID", "model", "age"]], on="machineID", how="left")
    # Con una sola lectura en la ventana la desviación no está definida
    out[SENSOR_FEATURES] = out[SENSOR_FEATURES].fillna(0.0)
    if times is not None:
        out = out[out["datetime"].isin(times)]
    return out.reset_index(drop=True)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Fechas en datetime64[ns] e IDs enteros: requisito de los cruces temporales."""
    df = df.copy()
    if "datetime" in df:
        df["datetime"] = pd.to_datetime(df["datetime"]).astype("datetime64[ns]")
    if "machineID" in df:
        df["machineID"] = df["machineID"].astype("int64")
    return df


def add_labels(features: pd.DataFrame, failures: pd.DataFrame, horizon_hours: int = HORIZON_HOURS) -> pd.DataFrame:
    """Etiqueta cada fila con el primer componente que falla en (t, t + horizonte]."""
    features, failures = _normalize(features), _normalize(failures)
    fails = failures.rename(columns={"datetime": "fail_time", "failure": "fail_comp"}).sort_values("fail_time")
    left = features[KEYS].reset_index().sort_values("datetime")
    nxt = pd.merge_asof(
        left, fails[["machineID", "fail_time", "fail_comp"]], left_on="datetime", right_on="fail_time",
        by="machineID", direction="forward", allow_exact_matches=False,
    ).set_index("index").sort_index()
    within = (nxt["fail_time"] - nxt["datetime"]) <= pd.Timedelta(hours=horizon_hours)
    labeled = features.copy()
    labeled["target"] = np.where(within, nxt["fail_comp"], NO_FAILURE)
    return labeled


def build_preprocessor(linear: bool) -> ColumnTransformer:
    """Preprocesado: imputación (falta de historial de mantenimiento) + one-hot del modelo.
    Los modelos lineales además necesitan escalado."""
    numeric = [("impute", SimpleImputer(strategy="median"))]
    if linear:
        numeric.append(("scale", StandardScaler()))
    return ColumnTransformer(
        [
            ("num", Pipeline(numeric), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(categories=[MACHINE_MODELS], handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
