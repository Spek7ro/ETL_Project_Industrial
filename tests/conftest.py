"""Datos sintéticos con el formato del dataset Azure Predictive Maintenance.

Cada falla de compN va precedida (24 h antes) por la desviación de un sensor y un
error del controlador, como en el dataset original, de modo que el pipeline completo
(ETL -> entrenamiento -> reproducción -> API) se puede probar en segundos.
"""
import numpy as np
import pandas as pd
import pytest

N_MACHINES = 8
DAYS = 90
START = pd.Timestamp("2015-01-01 06:00")
# sensor delator de cada componente y sentido de la desviación
PRECURSOR = {"comp1": ("volt", 1), "comp2": ("rotate", -1), "comp3": ("pressure", 1), "comp4": ("vibration", 1)}
BASE = {"volt": (170, 15), "rotate": (450, 50), "pressure": (100, 10), "vibration": (40, 5)}
ERROR_OF = {"comp1": "error1", "comp2": "error2", "comp3": "error3", "comp4": "error4"}


def make_raw(seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    hours = pd.date_range(START, periods=DAYS * 24, freq="h")
    tel, errors, maint, failures = [], [], [], []
    comps = list(PRECURSOR)
    for mid in range(1, N_MACHINES + 1):
        df = pd.DataFrame({"datetime": hours, "machineID": mid})
        for s, (mu, sd) in BASE.items():
            df[s] = rng.normal(mu, sd, len(hours))
        # Una falla cada ~8 días, ciclando componentes para que todos aparezcan
        day = int(rng.integers(5, 9))
        k = mid % 4
        while day < DAYS - 1:
            when = START.normalize() + pd.Timedelta(days=day, hours=6)
            comp = comps[k % 4]
            k += 1
            failures.append((when, mid, comp))
            maint.append((when, mid, comp))
            s, sign = PRECURSOR[comp]
            pre = (df["datetime"] > when - pd.Timedelta(hours=24)) & (df["datetime"] <= when)
            df.loc[pre, s] += sign * 5 * BASE[s][1]
            errors.append((when - pd.Timedelta(hours=int(rng.integers(12, 23))), mid, ERROR_OF[comp]))
            day += int(rng.integers(6, 11))
        # Mantenimiento programado y errores aleatorios (ruido)
        for d in range(0, DAYS, 15):
            maint.append((START + pd.Timedelta(days=d), mid, comps[int(rng.integers(0, 4))]))
        for h in rng.choice(len(hours), 6, replace=False):
            errors.append((hours[h], mid, "error5"))
        maint.append((START - pd.Timedelta(days=30), mid, "comp1"))
        tel.append(df)
    machines = pd.DataFrame({
        "machineID": range(1, N_MACHINES + 1),
        "model": [f"model{(i % 4) + 1}" for i in range(N_MACHINES)],
        "age": rng.integers(1, 20, N_MACHINES),
    })
    fmt = lambda rows, col: pd.DataFrame(rows, columns=["datetime", "machineID", col])
    return {
        "telemetry": pd.concat(tel, ignore_index=True),
        "errors": fmt(errors, "errorID"),
        "maint": fmt(maint, "comp"),
        "failures": fmt(failures, "failure"),
        "machines": machines,
    }


@pytest.fixture
def raw():
    return make_raw()


@pytest.fixture(scope="session")
def pipeline_dirs(tmp_path_factory):
    """Ejecuta ETL + entrenamiento una vez sobre datos sintéticos."""
    from src.config import SOURCE_FILES
    from src.etl.extract import extract
    from src.etl.load import load
    from src.etl.transform import transform
    from src.models.train import train

    root = tmp_path_factory.mktemp("pipeline")
    landing, processed, models = root / "landing", root / "processed", root / "models"
    landing.mkdir()
    for key, df in make_raw().items():
        df.to_csv(landing / SOURCE_FILES[key], index=False)
    tables, features, limits, summary, report = transform(extract(landing))
    load(tables, features, limits, summary, report, processed_dir=processed,
         database_url=f"sqlite:///{root / 'wh.db'}")
    metrics = train(processed / "features.parquet", models / "model.joblib", models / "metrics.json",
                    failures_path=processed / "failures.parquet")
    return {"root": root, "landing": landing, "processed": processed, "model": models / "model.joblib",
            "metrics_file": models / "metrics.json", "metrics": metrics, "db": root / "wh.db"}
