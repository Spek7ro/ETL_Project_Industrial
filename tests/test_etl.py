import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from src.config import SOURCE_FILES
from src.etl.extract import extract
from src.etl.transform import clean_tables, sensor_limits
from src.models.features import NUMERIC_FEATURES, add_labels, build_features


def test_extract_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="ingesta"):
        extract(tmp_path)


def test_extract_missing_columns(tmp_path, raw):
    for key, df in raw.items():
        df.to_csv(tmp_path / SOURCE_FILES[key], index=False)
    raw["errors"].drop(columns="errorID").to_csv(tmp_path / SOURCE_FILES["errors"], index=False)
    with pytest.raises(ValueError, match="faltan columnas"):
        extract(tmp_path)


def test_clean_tables_handles_dirty_data(raw):
    tel = raw["telemetry"]
    dirty = pd.concat([tel, tel.iloc[[0, 1]]])                     # 2 duplicados
    dirty.loc[dirty.index[5], "volt"] = 9999                       # fuera de rango -> interpolado
    dirty.loc[dirty.index[6], "rotate"] = np.nan                   # nulo -> interpolado
    unknown = tel.iloc[[0]].assign(machineID=999)                  # máquina desconocida
    raw["telemetry"] = pd.concat([dirty, unknown])
    raw["failures"] = pd.concat([raw["failures"], pd.DataFrame(
        [{"datetime": "2015-01-10 06:00:00", "machineID": 1, "failure": "comp9"}])])
    already_duplicated = int(raw["maint"].duplicated().sum())
    raw["maint"] = pd.concat([raw["maint"], raw["maint"].iloc[[0]]])

    tables, report = clean_tables(raw)

    t = report["telemetry"]
    assert t["duplicates_removed"] == 2
    assert t["out_of_range_set_null"]["volt"] == 1
    assert t["nulls_interpolated"]["rotate"] == 1
    assert tables["telemetry"][["volt", "rotate"]].isna().sum().sum() == 0
    assert tables["telemetry"]["volt"].max() < 400
    assert 999 not in set(tables["telemetry"]["machineID"])
    assert report["failures"]["invalid_removed"] == 1
    assert report["maint"]["duplicates_removed"] == already_duplicated + 1


def test_feature_values():
    t0 = pd.Timestamp("2015-01-01 00:00")
    tel = pd.DataFrame({
        "datetime": pd.date_range(t0, periods=30, freq="h"), "machineID": 1,
        "volt": np.arange(30, dtype=float), "rotate": 400.0, "pressure": 100.0, "vibration": 40.0,
    })
    errors = pd.DataFrame({"datetime": [t0 + pd.Timedelta(hours=2), t0 + pd.Timedelta(hours=28)],
                           "machineID": 1, "errorID": ["error1", "error1"]})
    maint = pd.DataFrame({"datetime": [t0 - pd.Timedelta(days=2)], "machineID": 1, "comp": ["comp3"]})
    machines = pd.DataFrame({"machineID": [1], "model": ["model2"], "age": [7]})
    at = t0 + pd.Timedelta(hours=29)
    f = build_features(tel, errors, maint, machines, times=pd.DatetimeIndex([at])).iloc[0]

    assert f["volt_mean_3h"] == pytest.approx(28.0)          # media de 27, 28, 29
    assert f["volt_mean_24h"] == pytest.approx(np.mean(np.arange(6, 30)))
    assert f["rotate_std_24h"] == pytest.approx(0.0)
    assert f["error1_count_24h"] == 1                        # el error de la hora 2 ya salió de la ventana
    assert f["comp3_days_since"] == pytest.approx(2 + 29 / 24)
    assert np.isnan(f["comp1_days_since"])                   # sin historial de reemplazo
    assert f["model"] == "model2" and f["age"] == 7


def test_labels_look_only_at_the_horizon():
    feats = pd.DataFrame({"machineID": 1, "datetime": pd.to_datetime(
        ["2015-01-01 00:00", "2015-01-01 12:00", "2015-01-02 06:00", "2015-01-02 07:00"])})
    fails = pd.DataFrame({"datetime": pd.to_datetime(["2015-01-02 06:00"]), "machineID": [1], "failure": ["comp2"]})
    labeled = add_labels(feats, fails, horizon_hours=24)
    # a 30 h: fuera del horizonte; a 18 h: dentro; en la hora de la falla y después: ya no
    assert labeled["target"].tolist() == ["none", "comp2", "none", "none"]


def test_features_use_only_past_data(pipeline_dirs):
    """Sin fuga de información: recalcular con datos <= t da exactamente lo mismo."""
    p = pipeline_dirs["processed"]
    feats = pd.read_parquet(p / "features.parquet")
    tables = {k: pd.read_parquet(p / f"{k}.parquet") for k in ("telemetry", "errors", "maint", "machines")}
    sample = pd.concat([feats[feats["target"] != "none"].sample(8, random_state=0),
                        feats[feats["target"] == "none"].sample(4, random_state=0)])
    for row in sample.itertuples():
        past = {k: df[(df["machineID"] == row.machineID) & (df["datetime"] <= row.datetime)]
                for k, df in tables.items() if k != "machines"}
        one = build_features(past["telemetry"], past["errors"], past["maint"], tables["machines"],
                             times=pd.DatetimeIndex([row.datetime])).iloc[0]
        stored = feats.loc[row.Index]
        np.testing.assert_allclose(one[NUMERIC_FEATURES].astype(float), stored[NUMERIC_FEATURES].astype(float),
                                   equal_nan=True)


def test_sensor_limits_are_ordered(raw):
    tables, _ = clean_tables(raw)
    for lim in sensor_limits(tables["telemetry"]).values():
        assert lim["critical_low"] < lim["alarm_low"] < lim["nominal"] < lim["alarm_high"] < lim["critical_high"]


def test_load_outputs(pipeline_dirs):
    p = pipeline_dirs["processed"]
    for name in ("telemetry", "errors", "maint", "failures", "machines", "features"):
        assert (p / f"{name}.parquet").exists()
    summary = json.loads((p / "dataset_summary.json").read_text())
    assert set(summary["failure_signature"]) == {"comp1", "comp2", "comp3", "comp4"}
    # La firma sintética: comp2 baja la rotación, comp3 sube la presión
    assert summary["failure_signature"]["comp2"]["rotate"] < -2
    assert summary["failure_signature"]["comp3"]["pressure"] > 2
    engine = create_engine(f"sqlite:///{pipeline_dirs['db']}")
    assert pd.read_sql("SELECT COUNT(*) AS n FROM failures", engine)["n"][0] == 85
