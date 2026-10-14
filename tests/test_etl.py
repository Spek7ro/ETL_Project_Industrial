import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from src.etl.extract import extract
from src.etl.load import load
from src.etl.transform import transform


def test_extract_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "nope.csv")


def test_extract_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"Temperature": [1.0]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Faltan columnas"):
        extract(path)


def test_transform_cleans_dirty_data(raw_df):
    dirty = raw_df.head(10).copy()
    dirty.loc[0, "Temperature"] = np.nan          # nulo -> imputado
    dirty.loc[1, "Humidity"] = 150                # fuera de rango -> imputado
    dirty.loc[2, "Failure_Risk"] = 7              # objetivo inválido -> eliminado
    dirty.loc[3, "Machine_Type"] = " mill "       # se normaliza
    dirty.loc[4, "Machine_Type"] = "Robot"        # tipo desconocido -> eliminado
    dirty = pd.concat([dirty, dirty.iloc[[5]]])   # duplicado -> eliminado

    clean, report = transform(dirty)

    assert len(clean) == 8
    assert report["duplicates_removed"] == 1
    assert report["invalid_target_removed"] == 1
    assert report["unknown_machine_type_removed"] == 1
    assert report["out_of_range_set_null"]["Humidity"] == 1
    assert clean.isna().sum().sum() == 0
    assert clean["Humidity"].between(0, 100).all()
    assert set(clean["Machine_Type"]) <= {"Drill", "Lathe", "Mill"}
    assert set(clean["Failure_Risk"]) <= {0, 1}


def test_load_writes_csv_report_and_db(tmp_path, raw_df):
    clean, report = transform(raw_df)
    db_url = f"sqlite:///{tmp_path / 'wh.db'}"
    load(clean, report, tmp_path / "c.csv", tmp_path / "r.json", db_url, "readings")

    assert len(pd.read_csv(tmp_path / "c.csv")) == len(clean)
    assert json.loads((tmp_path / "r.json").read_text())["rows_out"] == len(clean)
    stored = pd.read_sql("SELECT * FROM readings", create_engine(db_url))
    assert len(stored) == len(clean)
