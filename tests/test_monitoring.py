import pytest

from src.config import HEALTH_FAILURE, SENSOR_LIMITS
from src.monitoring.health import estimate_rul, health_index, sensor_state, status_from_health
from src.monitoring.simulator import FleetSimulator

NOMINAL = {k: v[0] for k, v in SENSOR_LIMITS.items()}
CRITICAL = {k: v[2] for k, v in SENSOR_LIMITS.items()}


def test_health_index_bounds():
    assert health_index(NOMINAL) == 100.0
    assert health_index(CRITICAL) == 0.0
    degraded = {**NOMINAL, "Temperature": 95.0}
    assert 0 < health_index(degraded) < 100


def test_sensor_state_and_status():
    assert sensor_state("Vibration", 50) == "normal"
    assert sensor_state("Vibration", 60) == "warning"
    assert sensor_state("Vibration", 70) == "critical"
    assert status_from_health(90) == "OPERATIVO"
    assert status_from_health(60) == "ALERTA"
    assert status_from_health(30) == "CRITICO"
    assert status_from_health(90, running=False) == "FALLA"


def test_estimate_rul_linear_trend():
    # Pierde 6 puntos por hora (1 punto cada 10 min) desde 80
    series = [80 - i for i in range(24)]
    rul = estimate_rul(series, minutes_per_tick=10)
    current = series[-1]
    assert rul["slope_per_hour"] == pytest.approx(-6, abs=0.01)
    assert rul["rul_hours"] == pytest.approx((current - HEALTH_FAILURE) / 6, abs=0.1)


def test_estimate_rul_stable_series():
    assert estimate_rul([95.0] * 24, minutes_per_tick=10)["rul_hours"] is None


@pytest.fixture(scope="module")
def sim():
    return FleetSimulator(predictor=None, seed=1, history_ticks=120)


def test_simulator_fleet_shape(sim):
    fleet = sim.fleet()
    assert fleet["kpis"]["total"] == 12 == len(fleet["machines"])
    assert sum(fleet["kpis"]["status_counts"].values()) == 12
    m = fleet["machines"][0]
    assert set(m["sensors"]) == {"Temperature", "Vibration", "Power_Usage", "Humidity"}
    assert 0 <= m["health"] <= 100


def test_simulator_is_deterministic():
    a = FleetSimulator(seed=3, history_ticks=50).fleet()["machines"]
    b = FleetSimulator(seed=3, history_ticks=50).fleet()["machines"]
    assert [m["health"] for m in a] == [m["health"] for m in b]


def test_maintenance_restores_machine(sim):
    worst = min(sim.fleet()["machines"], key=lambda m: m["health"])
    result = sim.perform_maintenance(worst["id"], technician="Ana", notes="Cambio de rodamientos")
    assert result["running"] and result["status"] == "OPERATIVO"
    events = sim.machine_detail(worst["id"])["events"]
    assert events[0]["kind"] == "maintenance" and "Ana" in events[0]["message"]


def test_degradation_eventually_triggers_alarms():
    sim = FleetSimulator(seed=5, history_ticks=10)
    for _ in range(400):
        sim.step()
    active = sim.event_list(active_only=True)
    assert active, "una flota con desgaste debe generar alarmas"
    assert sim.acknowledge(active[0]["id"])["acknowledged"] is True
