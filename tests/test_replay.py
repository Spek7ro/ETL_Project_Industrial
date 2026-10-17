import pandas as pd
import pytest

from src.models.predict import FailurePredictor
from src.monitoring.replay import FleetReplay, sensor_state


@pytest.fixture
def fleet(pipeline_dirs):
    return FleetReplay(FailurePredictor(pipeline_dirs["model"]), data_dir=pipeline_dirs["processed"])


def test_starts_at_test_period(fleet, pipeline_dirs):
    test_start = pd.Timestamp(pipeline_dirs["metrics"]["splits"]["test"]["start"])
    assert fleet.cursor == fleet.start == test_start.floor("h")
    f = fleet.fleet()
    assert f["kpis"]["total"] == 8 == len(f["machines"])
    assert sum(f["kpis"]["status_counts"].values()) == 8
    assert all(len(m["risk_trend"]) > 0 for m in f["machines"])


def test_replay_anticipates_real_failures(fleet):
    for _ in range(24 * 10):
        fleet.step()
    k = fleet.fleet()["kpis"]
    assert k["replay_failures"] > 0
    assert k["replay_anticipated"] / k["replay_failures"] >= 0.8
    failures = [e for e in fleet.event_list() if e["kind"] == "failure"]
    assert failures and failures[0]["severity"] == "critical"
    assert {e["resolution"] for e in failures} <= {"anticipated", "missed"}


def test_failed_machine_status(fleet):
    for _ in range(24 * 10):
        fleet.step()
        if any(m.status == "FALLA" for m in fleet.machines.values()):
            break
    failed = [m for m in fleet.fleet()["machines"] if m["status"] == "FALLA"]
    assert failed and failed[0]["last_failure"]["components"]


def test_work_order_acknowledges_alarms(fleet):
    for _ in range(48):
        fleet.step()
    target = next((e["machine_id"] for e in fleet.event_list(active_only=True) if e["machine_id"]), "M-001")
    fleet.register_work_order(target, "Ana", "comp2", "Reemplazo preventivo")
    events = fleet.machine_detail(target)["events"]
    assert events[0]["kind"] == "workorder" and "Ana" in events[0]["message"]
    assert all(e["acknowledged"] for e in events)


def test_machine_detail_and_inputs(fleet):
    d = fleet.machine_detail("M-003")
    assert len(d["history"]) == 168 and d["risk_history"]
    assert set(d["days_since_replacement"]) == {"comp1", "comp2", "comp3", "comp4"}
    inputs = fleet.machine_inputs("M-003")
    assert set(inputs["sensors"]) == {"volt", "rotate", "pressure", "vibration"}
    with pytest.raises(KeyError):
        fleet.machine_detail("M-999")


def test_wraps_around_at_the_end(fleet):
    fleet.cursor = fleet.end - pd.Timedelta(hours=1)
    fleet.step()   # última hora
    fleet.step()   # fin -> reinicio
    assert fleet.cursor == fleet.start
    assert fleet.event_list()[0]["kind"] == "system"


def test_sensor_state():
    lim = {"critical_low": 10, "alarm_low": 20, "nominal": 50, "alarm_high": 80, "critical_high": 90}
    assert [sensor_state(lim, v) for v in (5, 15, 50, 85, 95)] == ["critical", "warning", "normal", "warning", "critical"]


def _clean_alarms(fleet):
    for m in fleet.machines.values():
        m.alarm_event, m.armed = None, True
    return dict(fleet.stats, leads=list(fleet.stats["leads"]))


def test_alarm_stays_open_while_risk_persists(fleet):
    """Una alarma emitida más de un horizonte antes de la falla, con el riesgo alto todo
    el tiempo, debe contar como anticipada (no como falsa alarma + falla no anticipada)."""
    base = _clean_alarms(fleet)
    m = fleet.machines[1]
    t0 = fleet.cursor
    high = {"failure_probability": 0.99, "predicted_component": "comp1"}
    fleet._update_alarm(m, t0, high)
    for k in range(1, 30):                      # 29 h seguidas en riesgo
        fleet.cursor = t0 + pd.Timedelta(hours=k)
        fleet._update_alarm(m, fleet.cursor, high)
        fleet._expire_alarms(fleet.cursor)
    assert m.alarm_event is not None and fleet.stats["false_alarms"] == base["false_alarms"]
    fleet._on_failure(m, fleet.cursor, ["comp1"])
    assert fleet.stats["anticipated"] == base["anticipated"] + 1 and fleet.stats["leads"][-1] == 29
    assert fleet.event_list()[0]["resolution"] == "anticipated"


def test_alarm_expires_after_horizon_without_failure(fleet):
    base = _clean_alarms(fleet)
    m = fleet.machines[2]
    t0 = fleet.cursor
    fleet._update_alarm(m, t0, {"failure_probability": 0.99, "predicted_component": "comp2"})
    low = {"failure_probability": 0.0, "predicted_component": None}
    for k in range(1, 26):
        fleet.cursor = t0 + pd.Timedelta(hours=k)
        fleet._update_alarm(m, fleet.cursor, low)
        fleet._expire_alarms(fleet.cursor)
    assert m.alarm_event is None and fleet.stats["false_alarms"] == base["false_alarms"] + 1
