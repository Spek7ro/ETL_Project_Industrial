"""Extract: lectura de los datos crudos y validación del esquema."""
from pathlib import Path

import pandas as pd

from src.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES, RAW_FILE, TARGET

REQUIRED_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET]


def extract(path: Path = RAW_FILE) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró {path}. Ejecute primero la ingesta: python -m src.etl.ingest_data"
        )
    df = pd.read_csv(path)
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas en el dataset: {sorted(missing)}")
    print(f"[extract] {len(df)} filas leídas desde {path}")
    return df
