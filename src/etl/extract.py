"""Extract: lectura de las cinco tablas crudas y validación del esquema."""
from pathlib import Path

import pandas as pd

from src.config import LANDING_DIR, SOURCE_FILES

REQUIRED_COLUMNS = {
    "telemetry": ["datetime", "machineID", "volt", "rotate", "pressure", "vibration"],
    "errors": ["datetime", "machineID", "errorID"],
    "maint": ["datetime", "machineID", "comp"],
    "failures": ["datetime", "machineID", "failure"],
    "machines": ["machineID", "model", "age"],
}


def extract(landing_dir: Path = LANDING_DIR) -> dict[str, pd.DataFrame]:
    landing_dir = Path(landing_dir)
    tables = {}
    for key, name in SOURCE_FILES.items():
        path = landing_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"No se encontró {path}. Ejecute primero la ingesta: python -m src.etl.ingest_data"
            )
        df = pd.read_csv(path)
        missing = set(REQUIRED_COLUMNS[key]) - set(df.columns)
        if missing:
            raise ValueError(f"{name}: faltan columnas requeridas {sorted(missing)}")
        tables[key] = df
        print(f"[extract] {name}: {len(df)} filas")
    return tables
