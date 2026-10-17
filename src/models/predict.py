"""Servicio de inferencia: carga el modelo y estima el riesgo de falla por componente."""
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.config import COMPONENTS, MODEL_FILE, NO_FAILURE
from src.models.features import FEATURES, build_features

RECOMMENDATIONS = {
    "ALTO": "Falla probable de {comp} en las próximas {h} h: programar su reemplazo antes del próximo turno.",
    "MEDIO": "Riesgo elevado en {comp}: inspeccionar el componente y vigilar la evolución.",
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
        self.model = bundle["model"]
        self.model_name = bundle["model_name"]
        self.classes = bundle["classes"]
        self.features = bundle["features"]
        self.threshold = float(bundle["threshold"])
        self.alert_threshold = float(bundle["alert_threshold"])
        self.horizon_hours = int(bundle["horizon_hours"])
        self.feature_defaults = bundle["feature_defaults"]
        self.metrics = bundle.get("metrics", {})
        self.events = bundle.get("events", {})
        self.has_predictive_signal = bool(bundle.get("has_predictive_signal", True))
        self.test_start = bundle.get("test_start")
        self.trained_at = bundle.get("trained_at")

    def risk_level(self, p: float) -> str:
        if p >= self.threshold:
            return "ALTO"
        if p >= self.alert_threshold:
            return "MEDIO"
        return "BAJO"

    def predict_features(self, features: pd.DataFrame) -> list[dict]:
        """Predicción a partir de filas de características ya calculadas."""
        proba = self.model.predict_proba(features[FEATURES])
        none_idx = self.classes.index(NO_FAILURE)
        comp_idx = [self.classes.index(c) for c in COMPONENTS]
        results = []
        for row in proba:
            p_fail = float(1.0 - row[none_idx])
            comps = {c: round(float(row[i]), 4) for c, i in zip(COMPONENTS, comp_idx)}
            comp = COMPONENTS[int(np.argmax([row[i] for i in comp_idx]))]
            level = self.risk_level(p_fail)
            results.append({
                "failure_probability": round(p_fail, 4),
                "failure_predicted": p_fail >= self.threshold,
                "risk_level": level,
                "predicted_component": comp if level != "BAJO" else None,
                "component_probabilities": comps,
                "horizon_hours": self.horizon_hours,
                "recommendation": RECOMMENDATIONS[level].format(comp=comp, h=self.horizon_hours),
            })
        return results

    def predict_window(self, telemetry: pd.DataFrame, errors: pd.DataFrame, maint: pd.DataFrame,
                       machine: dict) -> dict:
        """Predicción en tiempo real para una máquina a partir de su historia reciente.
        Se evalúa en la última lectura de telemetría recibida."""
        mid = machine["machineID"]
        tel = telemetry.assign(machineID=mid)
        now = pd.to_datetime(tel["datetime"]).max()
        feats = build_features(
            tel, errors.assign(machineID=mid), maint.assign(machineID=mid),
            pd.DataFrame([machine]), times=pd.DatetimeIndex([now]),
        )
        return {"timestamp": now.isoformat(), **self.predict_features(feats)[0]}


@lru_cache(maxsize=1)
def get_predictor() -> FailurePredictor:
    return FailurePredictor()
