from src.models.predict import FailurePredictor, risk_level


def test_training_learns_signal(trained_model):
    _, metrics = trained_model
    assert metrics["has_predictive_signal"] is True
    assert metrics["test_metrics"]["roc_auc"] > 0.85
    assert metrics["best_model"] in metrics["cv_results"]


def test_predictor_outputs(trained_model):
    model_path, _ = trained_model
    predictor = FailurePredictor(model_path)
    hot = {"Temperature": 100, "Vibration": 65, "Power_Usage": 10, "Humidity": 30, "Machine_Type": "Mill"}
    cold = {"Temperature": 55, "Vibration": 42, "Power_Usage": 10, "Humidity": 30, "Machine_Type": "Drill"}
    high, low = predictor.predict([hot, cold])

    assert high["failure_probability"] > low["failure_probability"]
    assert high["failure_predicted"] and not low["failure_predicted"]
    assert high["risk_level"] == "ALTO" and low["risk_level"] == "BAJO"


def test_risk_level_boundaries():
    assert risk_level(0.1) == "BAJO"
    assert risk_level(0.4) == "MEDIO"
    assert risk_level(0.7) == "ALTO"
