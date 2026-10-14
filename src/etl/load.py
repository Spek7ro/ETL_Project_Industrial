"""Load: persistencia del dataset limpio en CSV y en base de datos."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from src.config import (
    DATABASE_URL,
    PROCESSED_FILE,
    QUALITY_REPORT_FILE,
    TABLE_NAME,
)


def load(
    df: pd.DataFrame,
    report: dict,
    csv_path: Path = PROCESSED_FILE,
    report_path: Path = QUALITY_REPORT_FILE,
    database_url: str = DATABASE_URL,
    table_name: str = TABLE_NAME,
) -> None:
    csv_path, report_path = Path(csv_path), Path(report_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    report = {**report, "loaded_at": datetime.now(timezone.utc).isoformat()}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    out = df.copy()
    out["ingested_at"] = report["loaded_at"]
    out.to_sql(table_name, engine, if_exists="replace", index_label="reading_id")
    engine.dispose()
    print(f"[load] {len(df)} filas -> {csv_path} y tabla '{table_name}'")
