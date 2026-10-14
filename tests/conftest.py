import numpy as np
import pandas as pd
import pytest


def make_raw_df() -> pd.DataFrame:
    """Datos sintéticos con una relación real entre sensores y fallo."""
    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame(
        {
            "Temperature": rng.normal(70, 10, n),
            "Vibration": rng.normal(50, 5, n),
            "Power_Usage": rng.normal(10, 1, n),
            "Humidity": rng.normal(30, 5, n),
            "Machine_Type": rng.choice(["Drill", "Lathe", "Mill"], n),
        }
    )
    score = (df.Temperature - 70) / 10 + (df.Vibration - 50) / 5 + rng.normal(0, 0.5, n)
    df["Failure_Risk"] = (score > 1.0).astype(int)
    return df


@pytest.fixture
def raw_df() -> pd.DataFrame:
    return make_raw_df()


@pytest.fixture(scope="session")
def trained_model(tmp_path_factory):
    from src.etl.transform import transform
    from src.models.train import train

    tmp_path = tmp_path_factory.mktemp("model")
    clean, _ = transform(make_raw_df())
    data = tmp_path / "clean.csv"
    clean.to_csv(data, index=False)
    model_path = tmp_path / "model.joblib"
    metrics = train(data, model_path, tmp_path / "metrics.json")
    return model_path, metrics
