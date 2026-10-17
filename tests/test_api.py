import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.models.predict import FailurePredictor

READING = {
    "machine_id": "MILL-01",
    "Temperature": 95.0,
    "Vibration": 62.0,
    "Power_Usage": 10.0,
    "Humidity": 30.0,
    "Machine_Type": "Mill",
}


@pytest.fixture
def client(trained_model, tmp_path, monkeypatch):
    model_path, _ = trained_model
    monkeypatch.setattr(api, "get_predictor", lambda: FailurePredictor(model_path))
    monkeypatch.setattr(api, "DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(api.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "model_loaded": True}


def test_model_info(client):
    body = client.get("/model/info").json()
    assert body["features"][-1] == "Machine_Type"
    assert 0 <= body["decision_threshold"] <= 1


def test_predict(client):
    r = client.post("/predict", json=READING)
    assert r.status_code == 200
    body = r.json()
    assert body["machine_id"] == "MILL-01"
    assert 0 <= body["failure_probability"] <= 1
    assert body["risk_level"] in {"BAJO", "MEDIO", "ALTO"}


def test_predict_batch(client):
    r = client.post("/predict/batch", json={"readings": [READING, {**READING, "Temperature": 50}]})
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.parametrize(
    "patch", [{"Machine_Type": "Robot"}, {"Humidity": 150}, {"Temperature": "hot"}]
)
def test_predict_rejects_invalid_input(client, patch):
    assert client.post("/predict", json={**READING, **patch}).status_code == 422


def test_predict_without_model(monkeypatch):
    def missing():
        raise FileNotFoundError("sin modelo")

    monkeypatch.setattr(api, "get_predictor", missing)
    monkeypatch.setattr(api, "LOG_PREDICTIONS", False)
    with TestClient(api.app) as c:
        assert c.get("/health").json()["model_loaded"] is False
        assert c.post("/predict", json=READING).status_code == 503


@pytest.fixture
def dash(trained_model, tmp_path, monkeypatch):
    model_path, _ = trained_model
    monkeypatch.setattr(api, "get_predictor", lambda: FailurePredictor(model_path))
    monkeypatch.setattr(api, "LOG_PREDICTIONS", False)
    monkeypatch.setattr(api, "SIM_TICK_SECONDS", 3600)  # sin avance en segundo plano
    with TestClient(api.app) as c:
        yield c


def test_dashboard_is_served(dash):
    r = dash.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/dashboard/"
    page = dash.get("/dashboard/")
    assert page.status_code == 200 and "Mantenimiento Predictivo" in page.text


def test_fleet_endpoints(dash):
    fleet = dash.get("/api/fleet").json()
    assert fleet["kpis"]["total"] == len(fleet["machines"]) == 12
    machine_id = fleet["machines"][0]["id"]
    detail = dash.get(f"/api/fleet/{machine_id}").json()
    assert detail["id"] == machine_id and len(detail["history"]) > 10
    assert dash.get("/api/fleet/NOPE").status_code == 404

    r = dash.post(f"/api/fleet/{machine_id}/maintenance", json={"technician": "Luis"})
    assert r.status_code == 200 and r.json()["status"] == "OPERATIVO"


def test_events_ack(dash):
    events = dash.get("/api/events").json()
    assert events  # el historial precargado incluye eventos
    r = dash.post(f"/api/events/{events[0]['id']}/ack")
    assert r.status_code == 200 and r.json()["acknowledged"] is True
    assert dash.post("/api/events/999999/ack").status_code == 404


def test_config_and_analytics(dash):
    cfg = dash.get("/api/config").json()
    assert cfg["sensor_limits"]["Temperature"]["critical"] > cfg["sensor_limits"]["Temperature"]["alarm"]
    assert set(dash.get("/api/analytics").json()) == {"dataset", "quality", "training"}


def test_diagnose(dash):
    r = dash.post("/api/diagnose", json={**READING, "Temperature": 99.0}).json()
    assert r["sensor_states"]["Temperature"] == "warning"
    assert r["status"] in {"ALERTA", "CRITICO"}
    assert 0 <= r["ml"]["failure_probability"] <= 1
