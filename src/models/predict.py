"""Servicio de inferencia: carga el modelo y genera predicciones."""
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

from src.config import DECISION_THRESHOLD, MODEL_FILE


def risk_level(probability: float) -> str:
    if probability >= 0.7:
        return "ALTO"
    if probability >= 0.4:
        return "MEDIO"
    return "BAJO"


RECOMMENDATIONS = {
    "ALTO": "Detener la máquina y programar mantenimiento inmediato.",
    "MEDIO": "Programar inspección preventiva en las próximas 48 horas.",
    "BAJO": "Operación normal; continuar con el monitoreo.",
}


class FailurePredictor:
    def __init__(self, model_path: Path = MODEL_FILE):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Modelo no encontrado en {model_path}. Entrene con: python -m src.models.train"
            )
        bundle = joblib.load(model_path)
        self.pipeline = bundle["pipeline"]
        self.model_name = bundle["model_name"]
        self.features = bundle["features"]
        self.threshold = float(bundle.get("threshold", DECISION_THRESHOLD))
        self.metrics = bundle.get("metrics", {})
        self.trained_at = bundle.get("trained_at")
        self.has_predictive_signal = bool(bundle.get("has_predictive_signal", True))

    def predict(self, records: list[dict]) -> list[dict]:
        df = pd.DataFrame(records)[self.features]
        probabilities = self.pipeline.predict_proba(df)[:, 1]
        results = []
        for p in probabilities:
            p = float(p)
            level = risk_level(p)
            results.append(
                {
                    "failure_probability": round(p, 4),
                    "failure_predicted": bool(p >= self.threshold),
                    "risk_level": level,
                    "recommendation": RECOMMENDATIONS[level],
                }
            )
        return results


@lru_cache(maxsize=1)
def get_predictor() -> FailurePredictor:
    return FailurePredictor()
