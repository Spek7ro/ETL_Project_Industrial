"""Load: tablas limpias y características en Parquet, reportes en JSON y tablas en la BD."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from src.config import (
    DATABASE_URL,
    DATASET_SUMMARY_FILE,
    FEATURES_FILE,
    PROCESSED_DIR,
    QUALITY_REPORT_FILE,
    SENSOR_LIMITS_FILE,
)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def load(
    tables: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    limits: dict,
    summary: dict,
    report: dict,
    processed_dir: Path = PROCESSED_DIR,
    database_url: str = DATABASE_URL,
) -> None:
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(processed_dir / f"{name}.parquet", index=False)
    features_file = processed_dir / FEATURES_FILE.name
    features.to_parquet(features_file, index=False)

    loaded_at = datetime.now(timezone.utc).isoformat()
    _write_json(processed_dir / QUALITY_REPORT_FILE.name, {**report, "loaded_at": loaded_at})
    _write_json(processed_dir / SENSOR_LIMITS_FILE.name, limits)
    _write_json(processed_dir / DATASET_SUMMARY_FILE.name, summary)

    # Las tablas limpias van a la base de datos (las características se quedan en Parquet)
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    for name, df in tables.items():
        df.to_sql(name, engine, if_exists="replace", index=False, chunksize=50_000)
    engine.dispose()
    print(f"[load] Tablas -> {processed_dir} y base de datos; {len(features)} filas de características")
