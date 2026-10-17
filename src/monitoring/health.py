"""Índice de salud, estado operativo y estimación de vida útil restante (RUL)."""
import numpy as np

from src.config import (
    HEALTH_ALERT,
    HEALTH_CRITICAL,
    HEALTH_FAILURE,
    SENSOR_LIMITS,
)

# Peso de cada sensor en el índice (la humedad es ambiental y pesa menos)
SENSOR_WEIGHTS = {"Temperature": 0.35, "Vibration": 0.35, "Power_Usage": 0.2, "Humidity": 0.1}

STATUS_OK, STATUS_ALERT, STATUS_CRITICAL, STATUS_FAILED = "OPERATIVO", "ALERTA", "CRITICO", "FALLA"
STATUS_SEVERITY = {STATUS_OK: 0, STATUS_ALERT: 1, STATUS_CRITICAL: 2, STATUS_FAILED: 3}


def sensor_severity(name: str, value: float) -> float:
    """0 en el valor nominal, 1 en el límite crítico."""
    nominal, _, critical = SENSOR_LIMITS[name]
    return float(np.clip((value - nominal) / (critical - nominal), 0.0, 1.0))


def sensor_state(name: str, value: float) -> str:
    _, alarm, critical = SENSOR_LIMITS[name]
    if value >= critical:
        return "critical"
    if value >= alarm:
        return "warning"
    return "normal"


def health_index(reading: dict) -> float:
    """Combina la peor desviación con la media ponderada: una sola variable
    cerca del límite crítico ya degrada fuertemente la salud."""
    sev = {k: sensor_severity(k, reading[k]) for k in SENSOR_LIMITS}
    weighted = sum(SENSOR_WEIGHTS[k] * s for k, s in sev.items())
    return round(100.0 * (1.0 - (0.6 * max(sev.values()) + 0.4 * weighted)), 2)


def status_from_health(health: float, running: bool = True) -> str:
    if not running:
        return STATUS_FAILED
    if health < HEALTH_CRITICAL:
        return STATUS_CRITICAL
    if health < HEALTH_ALERT:
        return STATUS_ALERT
    return STATUS_OK


def estimate_rul(health_series: list[float], minutes_per_tick: int, window: int = 24,
                 max_hours: float = 24 * 30) -> dict:
    """Extrapola linealmente la tendencia reciente de salud hasta el umbral de falla.

    Devuelve horas restantes (None si la tendencia es estable o mejora) y la
    pendiente en puntos de salud por hora.
    """
    recent = np.asarray(health_series[-window:], dtype=float)
    if len(recent) < 6:
        return {"rul_hours": None, "slope_per_hour": 0.0}
    hours = np.arange(len(recent)) * minutes_per_tick / 60.0
    slope, intercept = np.polyfit(hours, recent, 1)
    current = float(intercept + slope * hours[-1])
    if current <= HEALTH_FAILURE:
        return {"rul_hours": 0.0, "slope_per_hour": round(float(slope), 3)}
    if slope >= -0.05:  # deriva insignificante: estable
        return {"rul_hours": None, "slope_per_hour": round(float(slope), 3)}
    rul = (current - HEALTH_FAILURE) / -slope
    return {
        "rul_hours": round(float(min(rul, max_hours)), 1),
        "slope_per_hour": round(float(slope), 3),
    }
