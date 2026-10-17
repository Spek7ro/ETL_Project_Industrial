import pandas as pd
import pytest
from fastapi.testclient import TestClient

import src.api.dashboard as dashboard
import src.api.main as api
from src.models.predict import FailurePredictor
from src.monitoring.replay import FleetReplay


@pytest.fixture
def client(pipeline_dirs, monkeypatch):
    model = pipeline_dirs["model"]
    processed = pipeline_dirs["processed"]
    monkeypatch.setattr(api, "get_predictor", lambda: FailurePredictor(model))
    monkeypatch.setattr(api, "create_fleet", lambda p: FleetReplay(p, data_dir=processed))
    monkeypatch.setattr(api, "LOG_PREDICTIONS", False)
    monkeypatch.setattr(api, "SIM_TICK_SECONDS", 3600)  # sin avance en segundo plano
    monkeypatch.setattr(dashboard, "SENSOR_LIMITS_FILE", processed / "sensor_limits.json")
    monkeypatch.setattr(dashboard, "DATASET_SUMMARY_FILE", processed / "dataset_summary.json")
    monkeypatch.setattr(dashboard, "QUALITY_REPORT_FILE", processed / "data_quality_report.json")
    monkeypatch.setattr(dashboard, "METRICS_FILE", pipeline_dirs["metrics_file"])
    with TestClient(api.app) as c:
        yield c


def window(pipeline_dirs, target="comp4"):
    """Ventana de 24 h de una máquina justo antes de una falla real."""
    p = pipeline_dirs["processed"]
    feats = pd.read_parquet(p / "features.parquet")
    row = feats[feats["target"] == target].iloc[3]
    mid, t = int(row["machineID"]), row["datetime"]
    tel = pd.read_parquet(p / "telemetry.parquet")
    err = pd.read_parquet(p / "errors.parquet")
    mnt = pd.read_parquet(p / "maint.parquet")
    machine = pd.read_parquet(p / "machines.parquet").set_index("machineID").loc[mid]
    sel = lambda df, h=None: df[(df.machineID == mid) & (df.datetime <= t) & ((df.datetime > t - pd.Timedelta(hours=h)) if h else True)]
    iso = lambda d: d.isoformat()
    return {
        "machine_id": f"M-{mid:03d}", "model": machine["model"], "age": float(machine["age"]),
        "telemetry": [{"datetime": iso(r.datetime), "volt": r.volt, "rotate": r.rotate, "pressure": r.pressure,
                       "vibration": r.vibration} for r in sel(tel, 24).itertuples()],
        "errors": [{"datetime": iso(r.datetime), "errorID": r.errorID} for r in sel(err, 24).itertuples()],
        "maintenance": [{"datetime": iso(r.datetime), "comp": r.comp} for r in sel(mnt).itertuples()],
    }


def test_health_and_model_info(client):
    assert client.get("/health").json() == {"status": "ok", "model_loaded": True}
    info = client.get("/model/info").json()
    assert info["horizon_hours"] == 24 and info["has_predictive_signal"] is True


def test_predict_realtime_window(client, pipeline_dirs):
    r = client.post("/predict", json=window(pipeline_dirs, "comp4"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["risk_level"] == "ALTO" and body["predicted_component"] == "comp4"
    assert body["machine_id"].startswith("M-")


def test_predict_batch(client, pipeline_dirs):
    r = client.post("/predict/batch", json={"machines": [window(pipeline_dirs, "comp1"), window(pipeline_dirs, "comp2")]})
    assert r.status_code == 200
    assert r.json()["total"] == 2 and r.json()["high_risk_count"] == 2


@pytest.mark.parametrize("patch", [
    {"model": "model9"},
    {"telemetry": []},
    {"telemetry": [{"datetime": "2015-01-01T00:00:00", "volt": -5, "rotate": 1, "pressure": 1, "vibration": 1}]},
    {"errors": [{"datetime": "2015-01-01T00:00:00", "errorID": "error9"}]},
])
def test_predict_rejects_invalid_input(client, pipeline_dirs, patch):
    assert client.post("/predict", json={**window(pipeline_dirs), **patch}).status_code == 422


def test_dashboard_endpoints(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/dashboard/"
    assert "Mantenimiento Predictivo" in client.get("/dashboard/").text
    cfg = client.get("/api/config").json()
    assert cfg["sensor_limits"]["volt"]["critical_high"] > cfg["sensor_limits"]["volt"]["alarm_high"]
    fleet = client.get("/api/fleet").json()
    assert fleet["kpis"]["total"] == 8
    detail = client.get("/api/fleet/M-002").json()
    assert detail["id"] == "M-002" and detail["history"]
    assert client.get("/api/fleet/M-404").status_code == 404
    r = client.post("/api/fleet/M-002/work-orders", json={"technician": "Luis", "component": "comp1"})
    assert r.status_code == 200
    assert client.post("/api/fleet/M-002/work-orders", json={"component": "comp7"}).status_code == 422


def test_events_ack(client):
    events = client.get("/api/events").json()
    assert events
    r = client.post(f"/api/events/{events[0]['id']}/ack")
    assert r.status_code == 200 and r.json()["acknowledged"] is True
    assert client.post("/api/events/999999/ack").status_code == 404


def test_what_if(client):
    inputs = client.get("/api/fleet/M-001/inputs").json()
    base = client.post("/api/diagnose", json=inputs).json()
    # Precursor sintético de comp3: presión muy alta + error3
    risky = {**inputs, "sensors": {**inputs["sensors"], "pressure": 220}, "errors_24h": {"error3": 1}}
    r = client.post("/api/diagnose", json=risky).json()
    assert r["failure_probability"] > base["failure_probability"]
    assert r["predicted_component"] == "comp3"
    assert r["sensor_states"]["pressure"] == "critical"


def test_analytics(client):
    a = client.get("/api/analytics").json()
    assert a["training"]["best_model"] and a["dataset"]["machines"] == 8 and a["quality"]


def test_without_model_fleet_is_unavailable(monkeypatch):
    def missing():
        raise FileNotFoundError("sin modelo")

    monkeypatch.setattr(api, "get_predictor", missing)
    monkeypatch.setattr(api, "LOG_PREDICTIONS", False)
    with TestClient(api.app) as c:
        assert c.get("/health").json()["model_loaded"] is False
        assert c.get("/api/fleet").status_code == 503
        assert c.post("/api/diagnose", json={"model": "model1", "age": 1, "sensors": {"volt": 170}}).status_code == 503
