"""Entrenamiento, comparación y selección del modelo de predicción de fallos."""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_validate, train_test_split
from sklearn.pipeline import Pipeline

from src.config import (
    CATEGORICAL_FEATURES,
    DECISION_THRESHOLD,
    METRICS_FILE,
    MODEL_FILE,
    NUMERIC_FEATURES,
    PROCESSED_FILE,
    RANDOM_STATE,
    TARGET,
    TEST_SIZE,
)
from src.models.features import build_preprocessor

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def candidate_models() -> dict:
    return {
        "logistic_regression": LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=RANDOM_STATE
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "gradient_boosting": GradientBoostingClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05, random_state=RANDOM_STATE
        ),
    }


def make_pipeline(model) -> Pipeline:
    return Pipeline([("preprocessor", build_preprocessor()), ("model", model)])


# Por debajo de este ROC-AUC en validación cruzada se considera que los datos no
# contienen señal predictiva útil (un clasificador aleatorio obtiene 0.5).
MIN_USEFUL_ROC_AUC = 0.6


def youden_threshold(y_true, proba) -> float:
    """Umbral que maximiza TPR - FPR (estadístico J de Youden)."""
    fpr, tpr, thresholds = roc_curve(y_true, proba)
    finite = np.isfinite(thresholds)
    best = int(np.argmax((tpr - fpr)[finite]))
    return float(np.clip(thresholds[finite][best], 0.0, 1.0))


def evaluate(y_true, proba, threshold: float) -> dict:
    pred = (proba >= threshold).astype(int)
    return {
        "roc_auc": round(float(roc_auc_score(y_true, proba)), 4),
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "confusion_matrix": confusion_matrix(y_true, pred).tolist(),
    }


def train(
    data_path: Path = PROCESSED_FILE,
    model_path: Path = MODEL_FILE,
    metrics_path: Path = METRICS_FILE,
) -> dict:
    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"No existe {data_path}. Ejecute el ETL: python -m src.etl.pipeline")
    df = pd.read_csv(data_path)
    X, y = df[FEATURES], df[TARGET].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)

    # 1) Comparación de candidatos con validación cruzada (frente a un baseline aleatorio)
    baseline = cross_validate(
        DummyClassifier(strategy="stratified", random_state=RANDOM_STATE),
        X_train, y_train, cv=cv, scoring="roc_auc",
    )
    baseline_auc = round(float(baseline["test_score"].mean()), 4)
    cv_results = {}
    for name, model in candidate_models().items():
        scores = cross_validate(
            make_pipeline(model), X_train, y_train, cv=cv, scoring=["roc_auc", "f1"]
        )
        cv_results[name] = {
            "roc_auc_mean": round(float(scores["test_roc_auc"].mean()), 4),
            "roc_auc_std": round(float(scores["test_roc_auc"].std()), 4),
            "f1_mean": round(float(scores["test_f1"].mean()), 4),
        }
        print(f"[train] {name}: CV ROC-AUC={cv_results[name]['roc_auc_mean']:.4f}")

    best_name = max(cv_results, key=lambda n: cv_results[n]["roc_auc_mean"])
    best_cv_auc = cv_results[best_name]["roc_auc_mean"]
    has_signal = best_cv_auc >= MIN_USEFUL_ROC_AUC
    if not has_signal:
        print(
            f"[train] ADVERTENCIA: el mejor ROC-AUC en CV ({best_cv_auc:.3f}) no supera "
            f"{MIN_USEFUL_ROC_AUC}; las variables apenas predicen el objetivo "
            f"(baseline aleatorio={baseline_auc:.3f}). Revise la calidad/etiquetado de los datos."
        )
    best_pipeline = make_pipeline(clone(candidate_models()[best_name]))

    # 2) Umbral de decisión: Youden sobre predicciones out-of-fold del train.
    #    Sin señal predictiva el umbral optimizado es ruido, se usa el configurado.
    if has_signal:
        oof = cross_val_predict(best_pipeline, X_train, y_train, cv=cv, method="predict_proba")[:, 1]
        threshold = youden_threshold(y_train, oof)
    else:
        threshold = DECISION_THRESHOLD

    # 3) Entrenamiento final y evaluación en test
    best_pipeline.fit(X_train, y_train)
    test_proba = best_pipeline.predict_proba(X_test)[:, 1]
    test_metrics = evaluate(y_test, test_proba, threshold)
    test_metrics_default = evaluate(y_test, test_proba, 0.5)

    trained_at = datetime.now(timezone.utc).isoformat()
    metrics = {
        "best_model": best_name,
        "decision_threshold": round(threshold, 4),
        "has_predictive_signal": has_signal,
        "baseline_cv_roc_auc": baseline_auc,
        "cv_results": cv_results,
        "test_metrics": test_metrics,
        "test_metrics_threshold_0_5": test_metrics_default,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": FEATURES,
        "trained_at": trained_at,
    }

    model_path, metrics_path = Path(model_path), Path(metrics_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": best_pipeline,
            "model_name": best_name,
            "threshold": threshold,
            "features": FEATURES,
            "metrics": test_metrics,
            "has_predictive_signal": has_signal,
            "trained_at": trained_at,
        },
        model_path,
    )
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"[train] Mejor modelo: {best_name} | test={test_metrics} | umbral={threshold:.3f}")
    print(f"[train] Modelo guardado en {model_path}")
    return metrics


if __name__ == "__main__":
    train()
