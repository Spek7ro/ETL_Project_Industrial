import pandas as pd
import pytest

from src.config import COMPONENTS
from src.models.features import build_features
from src.models.predict import FailurePredictor


@pytest.fixture(scope="module")
def predictor(pipeline_dirs):
    return FailurePredictor(pipeline_dirs["model"])


def test_training_learns_signal(pipeline_dirs):
    m = pipeline_dirs["metrics"]
    tm = m["test_metrics"]
    assert m["has_predictive_signal"] is True
    assert tm["pr_auc"] > 0.8 > tm["prevalence"]
    assert tm["events"]["anticipated_rate"] >= 0.8
    assert set(m["validation_results"]) == {"logistic_regression", "random_forest", "hist_gradient_boosting"}
    assert 0 < m["decision_threshold"] < 1 and m["alert_threshold"] <= m["decision_threshold"]


def test_splits_are_chronological(pipeline_dirs):
    s = pipeline_dirs["metrics"]["splits"]
    assert s["train"]["end"] < s["valid"]["start"] <= s["valid"]["end"] < s["test"]["start"]


def test_predict_output(predictor, pipeline_dirs):
    feats = pd.read_parquet(pipeline_dirs["processed"] / "features.parquet")
    pos = feats[feats["target"] == "comp3"].iloc[[0]]
    neg = feats[feats["target"] == "none"].iloc[[0]]
    hi, lo = predictor.predict_features(pd.concat([pos, neg]))
    assert hi["failure_probability"] > lo["failure_probability"]
    assert hi["predicted_component"] == "comp3" and hi["risk_level"] == "ALTO"
    assert set(hi["component_probabilities"]) == set(COMPONENTS)
    assert sum(hi["component_probabilities"].values()) == pytest.approx(hi["failure_probability"], abs=1e-3)


def test_realtime_window_matches_batch_features(predictor, pipeline_dirs):
    """La predicción en tiempo real (ventana de una máquina) usa las mismas
    características que el entrenamiento."""
    p = pipeline_dirs["processed"]
    tables = {k: pd.read_parquet(p / f"{k}.parquet") for k in ("telemetry", "errors", "maint", "machines")}
    feats = pd.read_parquet(p / "features.parquet")
    row = feats[feats["target"] != "none"].iloc[5]
    mid, t = row["machineID"], row["datetime"]
    win = lambda df, hours=None: df[(df["machineID"] == mid) & (df["datetime"] <= t)
                                    & ((df["datetime"] > t - pd.Timedelta(hours=hours)) if hours else True)]
    machine = tables["machines"].set_index("machineID").loc[mid]
    result = predictor.predict_window(
        win(tables["telemetry"], 24).drop(columns="machineID"),
        win(tables["errors"], 24).drop(columns="machineID"),
        win(tables["maint"]).drop(columns="machineID"),
        {"machineID": 0, "model": machine["model"], "age": machine["age"]},
    )
    batch = predictor.predict_features(feats.loc[[row.name]])[0]
    assert result["timestamp"] == t.isoformat()
    assert result["failure_probability"] == pytest.approx(batch["failure_probability"])


def test_missing_model_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m src.models.train"):
        FailurePredictor(tmp_path / "nope.joblib")
