"""Entrenamiento: ¿qué componente fallará en las próximas HORIZON_HOURS horas?

- División temporal (train → validación → test), con un hueco del tamaño del horizonte
  entre tramos para que las etiquetas no vean el futuro del tramo siguiente.
- Selección del modelo por PR-AUC en validación (las fallas son ~2 % de las filas).
- Calibración isotónica en validación: el dashboard muestra probabilidades.
- Umbral de alarma que minimiza el coste esperado (falla no anticipada vs. falsa alarma).
- Evaluación final en test, también por evento: ¿cuántas fallas se anticiparon y con
  cuánta antelación?
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from src.config import (
    CLASSES,
    COMPONENTS,
    COST_FALSE_ALARM,
    COST_MISSED_FAILURE,
    FEATURES_FILE,
    HORIZON_HOURS,
    METRICS_FILE,
    MIN_USEFUL_ROC_AUC,
    MODEL_FILE,
    NO_FAILURE,
    PROCESSED_DIR,
    RANDOM_STATE,
    SPLIT_FRACTIONS,
)
from src.models.features import FEATURES, NUMERIC_FEATURES, build_preprocessor


def candidate_models() -> dict:
    return {
        "logistic_regression": (
            LogisticRegression(max_iter=2000, class_weight="balanced"), True,
        ),
        "random_forest": (
            RandomForestClassifier(
                n_estimators=200, min_samples_leaf=3, max_features="sqrt",
                class_weight="balanced_subsample", n_jobs=-1, random_state=RANDOM_STATE,
            ),
            False,
        ),
        "hist_gradient_boosting": (
            HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
                class_weight="balanced", random_state=RANDOM_STATE,
            ),
            False,
        ),
    }


def make_pipeline(model, linear: bool) -> Pipeline:
    return Pipeline([("preprocessor", build_preprocessor(linear)), ("model", model)])


def failure_probability(model, X: pd.DataFrame) -> np.ndarray:
    """P(falla de cualquier componente en el horizonte) = 1 - P(none)."""
    proba = model.predict_proba(X)
    return 1.0 - proba[:, list(model.classes_).index(NO_FAILURE)]


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    start, end = df["datetime"].min(), df["datetime"].max()
    cut1 = start + (end - start) * SPLIT_FRACTIONS[0]
    cut2 = start + (end - start) * SPLIT_FRACTIONS[1]
    gap = pd.Timedelta(hours=HORIZON_HOURS)
    train = df[df["datetime"] < cut1 - gap]
    valid = df[(df["datetime"] >= cut1) & (df["datetime"] < cut2 - gap)]
    test = df[df["datetime"] >= cut2]
    ranges = {
        name: {"start": part["datetime"].min().isoformat(), "end": part["datetime"].max().isoformat(), "rows": len(part)}
        for name, part in (("train", train), ("valid", valid), ("test", test))
    }
    return train, valid, test, ranges


def cost_threshold(y_true: np.ndarray, p_fail: np.ndarray) -> float:
    """Umbral que minimiza COST_MISSED_FAILURE·FN + COST_FALSE_ALARM·FP."""
    candidates = np.unique(np.quantile(p_fail, np.linspace(0.5, 0.9995, 400)))
    costs = [
        COST_MISSED_FAILURE * np.sum((p_fail < t) & (y_true == 1)) + COST_FALSE_ALARM * np.sum((p_fail >= t) & (y_true == 0))
        for t in candidates
    ]
    return float(candidates[int(np.argmin(costs))])


def predicted_labels(proba: np.ndarray, classes: list[str], threshold: float) -> np.ndarray:
    none_idx = classes.index(NO_FAILURE)
    comp_idx = [classes.index(c) for c in COMPONENTS]
    p_fail = 1.0 - proba[:, none_idx]
    best_comp = np.array(COMPONENTS)[np.argmax(proba[:, comp_idx], axis=1)]
    return np.where(p_fail >= threshold, best_comp, NO_FAILURE)


def event_metrics(test: pd.DataFrame, p_fail: np.ndarray, labels: np.ndarray, failures: pd.DataFrame,
                  threshold: float) -> dict:
    """Métricas por evento de falla: anticipación y antelación de la primera alarma."""
    scored = test[["machineID", "datetime"]].assign(p=p_fail, label=labels)
    start, end = test["datetime"].min(), test["datetime"].max()
    events = failures[(failures["datetime"] > start + pd.Timedelta(hours=HORIZON_HOURS)) & (failures["datetime"] <= end)]
    events = events.groupby(["machineID", "datetime"])["failure"].apply(set).reset_index()
    anticipated, correct_component, leads = 0, 0, []
    for ev in events.itertuples():
        window = scored[(scored["machineID"] == ev.machineID)
                        & (scored["datetime"] >= ev.datetime - pd.Timedelta(hours=HORIZON_HOURS))
                        & (scored["datetime"] < ev.datetime)]
        alarms = window[window["p"] >= threshold]
        if len(alarms):
            anticipated += 1
            first = alarms.iloc[0]
            leads.append((ev.datetime - first["datetime"]).total_seconds() / 3600)
            correct_component += int(first["label"] in ev.failure)
    n = len(events)
    return {
        "failure_events": n,
        "anticipated": anticipated,
        "anticipated_rate": round(anticipated / n, 4) if n else None,
        "correct_component_rate": round(correct_component / anticipated, 4) if anticipated else None,
        "median_lead_hours": round(float(np.median(leads)), 1) if leads else None,
    }


def binary_metrics(y_true: np.ndarray, p_fail: np.ndarray, threshold: float) -> dict:
    pred = (p_fail >= threshold).astype(int)
    return {
        "roc_auc": round(float(roc_auc_score(y_true, p_fail)), 4),
        "pr_auc": round(float(average_precision_score(y_true, p_fail)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "prevalence": round(float(y_true.mean()), 4),
        "confusion_matrix": confusion_matrix(y_true, pred, labels=[0, 1]).tolist(),
    }


def train(
    features_path: Path = FEATURES_FILE,
    model_path: Path = MODEL_FILE,
    metrics_path: Path = METRICS_FILE,
    failures_path: Path | None = None,
) -> dict:
    features_path = Path(features_path)
    if not features_path.exists():
        raise FileNotFoundError(f"No existe {features_path}. Ejecute el ETL: python -m src.etl.pipeline")
    df = pd.read_parquet(features_path)
    failures = pd.read_parquet(failures_path or features_path.parent / "failures.parquet")
    train_df, valid_df, test_df, ranges = time_split(df)
    print(f"[train] train={len(train_df)} valid={len(valid_df)} test={len(test_df)} filas")

    y_valid_bin = (valid_df["target"] != NO_FAILURE).to_numpy().astype(int)
    results, fitted = {}, {}
    for name, (model, linear) in candidate_models().items():
        pipe = make_pipeline(model, linear).fit(train_df[FEATURES], train_df["target"])
        p = failure_probability(pipe, valid_df[FEATURES])
        results[name] = {
            "pr_auc": round(float(average_precision_score(y_valid_bin, p)), 4),
            "roc_auc": round(float(roc_auc_score(y_valid_bin, p)), 4),
        }
        fitted[name] = pipe
        print(f"[train] {name}: PR-AUC={results[name]['pr_auc']:.4f} ROC-AUC={results[name]['roc_auc']:.4f} (validación)")

    best_name = max(results, key=lambda n: results[n]["pr_auc"])
    has_signal = results[best_name]["roc_auc"] >= MIN_USEFUL_ROC_AUC
    if not has_signal:
        print(f"[train] ADVERTENCIA: ROC-AUC {results[best_name]['roc_auc']:.3f} < {MIN_USEFUL_ROC_AUC}; "
              "los datos apenas permiten anticipar fallas.")

    # Calibración sobre validación (el modelo base queda congelado)
    model = CalibratedClassifierCV(FrozenEstimator(fitted[best_name]), method="isotonic")
    model.fit(valid_df[FEATURES], valid_df["target"])
    classes = list(model.classes_)
    p_valid = failure_probability(model, valid_df[FEATURES])
    threshold = cost_threshold(y_valid_bin, p_valid)
    alert_threshold = max(0.02, threshold / 2)

    # Evaluación final en test
    proba_test = model.predict_proba(test_df[FEATURES])
    p_test = 1.0 - proba_test[:, classes.index(NO_FAILURE)]
    y_test_bin = (test_df["target"] != NO_FAILURE).to_numpy().astype(int)
    labels_test = predicted_labels(proba_test, classes, threshold)
    report = classification_report(test_df["target"], labels_test, labels=CLASSES, output_dict=True, zero_division=0)
    test_metrics = {
        **binary_metrics(y_test_bin, p_test, threshold),
        "events": event_metrics(test_df, p_test, labels_test, failures, threshold),
        "per_class": {c: {k: round(float(report[c][k]), 4) for k in ("precision", "recall", "f1-score", "support")}
                      for c in CLASSES},
        "multiclass_confusion_matrix": confusion_matrix(test_df["target"], labels_test, labels=CLASSES).tolist(),
    }

    # Importancia por permutación (caída de PR-AUC) sobre una muestra de validación
    sample = pd.concat([valid_df[valid_df["target"] != NO_FAILURE],
                        valid_df[valid_df["target"] == NO_FAILURE].sample(
                            min(15000, int((valid_df["target"] == NO_FAILURE).sum())), random_state=RANDOM_STATE)])
    imp = permutation_importance(
        model, sample[FEATURES], (sample["target"] != NO_FAILURE).astype(int),
        scoring=lambda est, X, y: average_precision_score(y, failure_probability(est, X)),
        n_repeats=3, random_state=RANDOM_STATE, n_jobs=1,
    )
    importance = sorted(
        ({"feature": f, "importance": round(float(m), 4)} for f, m in zip(FEATURES, imp.importances_mean)),
        key=lambda r: -r["importance"],
    )

    trained_at = datetime.now(timezone.utc).isoformat()
    metrics = {
        "best_model": best_name,
        "horizon_hours": HORIZON_HOURS,
        "decision_threshold": round(threshold, 4),
        "alert_threshold": round(alert_threshold, 4),
        "costs": {"missed_failure": COST_MISSED_FAILURE, "false_alarm": COST_FALSE_ALARM},
        "has_predictive_signal": has_signal,
        "validation_results": results,
        "validation_prevalence": round(float(y_valid_bin.mean()), 4),
        "test_metrics": test_metrics,
        "feature_importance": importance,
        "splits": ranges,
        "classes": classes,
        "trained_at": trained_at,
    }

    model_path, metrics_path = Path(model_path), Path(metrics_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "model_name": best_name,
            "classes": classes,
            "features": FEATURES,
            "threshold": threshold,
            "alert_threshold": alert_threshold,
            "horizon_hours": HORIZON_HOURS,
            # Valores típicos para completar entradas parciales en el análisis what-if
            "feature_defaults": train_df[NUMERIC_FEATURES].median().round(4).to_dict(),
            "metrics": {k: test_metrics[k] for k in ("roc_auc", "pr_auc", "precision", "recall")},
            "events": test_metrics["events"],
            "has_predictive_signal": has_signal,
            "test_start": ranges["test"]["start"],
            "trained_at": trained_at,
        },
        model_path,
    )
    metrics_path.write_text(json.dumps(metrics, indent=2))
    ev = test_metrics["events"]
    print(f"[train] Mejor modelo: {best_name} | test PR-AUC={test_metrics['pr_auc']} ROC-AUC={test_metrics['roc_auc']} "
          f"precision={test_metrics['precision']} recall={test_metrics['recall']} | umbral={threshold:.3f}")
    print(f"[train] Fallas anticipadas en test: {ev['anticipated']}/{ev['failure_events']} "
          f"(antelación mediana {ev['median_lead_hours']} h; componente correcto {ev['correct_component_rate']})")
    return metrics


if __name__ == "__main__":
    train(failures_path=PROCESSED_DIR / "failures.parquet")
