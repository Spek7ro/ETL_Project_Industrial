"""Endpoints de monitorización de flota y analítica para el dashboard."""
import json

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import (
    HEALTH_ALERT,
    HEALTH_CRITICAL,
    HEALTH_FAILURE,
    METRICS_FILE,
    NUMERIC_FEATURES,
    PROCESSED_FILE,
    QUALITY_REPORT_FILE,
    SENSOR_LIMITS,
    SENSOR_UNITS,
    TARGET,
)

router = APIRouter(prefix="/api", tags=["dashboard"])


class MaintenanceRequest(BaseModel):
    technician: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=500)


def simulator(request: Request):
    sim = getattr(request.app.state, "simulator", None)
    if sim is None:
        raise HTTPException(status_code=503, detail="La simulación de flota está deshabilitada.")
    return sim


def machine_or_404(sim, machine_id: str):
    if machine_id not in sim.machines:
        raise HTTPException(status_code=404, detail=f"Máquina '{machine_id}' no encontrada.")


@router.get("/config")
def dashboard_config():
    return {
        "sensor_limits": {k: dict(zip(["nominal", "alarm", "critical"], v)) for k, v in SENSOR_LIMITS.items()},
        "sensor_units": SENSOR_UNITS,
        "health_thresholds": {"alert": HEALTH_ALERT, "critical": HEALTH_CRITICAL, "failure": HEALTH_FAILURE},
    }


@router.get("/fleet")
def fleet(request: Request):
    return simulator(request).fleet()


@router.get("/fleet/{machine_id}")
def machine_detail(machine_id: str, request: Request, points: int = 288):
    sim = simulator(request)
    machine_or_404(sim, machine_id)
    return sim.machine_detail(machine_id, points=max(10, min(points, 576)))


@router.post("/fleet/{machine_id}/maintenance")
def maintenance(machine_id: str, body: MaintenanceRequest, request: Request):
    sim = simulator(request)
    machine_or_404(sim, machine_id)
    return sim.perform_maintenance(machine_id, body.technician, body.notes)


@router.get("/events")
def events(request: Request, active: bool = False, limit: int = 100):
    return simulator(request).event_list(active_only=active, limit=max(1, min(limit, 300)))


@router.post("/events/{event_id}/ack")
def acknowledge(event_id: int, request: Request):
    event = simulator(request).acknowledge(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    return event


@router.get("/analytics")
def analytics():
    """Resumen del dataset procesado por el ETL y del entrenamiento del modelo."""
    result = {"dataset": None, "quality": None, "training": None}
    if PROCESSED_FILE.exists():
        df = pd.read_csv(PROCESSED_FILE)
        by_type = df.groupby("Machine_Type")[TARGET].agg(["mean", "count"]).reset_index()
        distributions = {}
        for col in NUMERIC_FEATURES:
            edges = pd.Series(pd.cut(df[col], bins=20, retbins=True)[1])
            binned = pd.cut(df[col], bins=edges, include_lowest=True)
            counts = df.groupby([binned, TARGET], observed=False).size().unstack(fill_value=0)
            distributions[col] = {
                "bin_centers": [round(float(i.mid), 2) for i in counts.index],
                "ok": counts.get(0, pd.Series(0, index=counts.index)).astype(int).tolist(),
                "failure": counts.get(1, pd.Series(0, index=counts.index)).astype(int).tolist(),
            }
        result["dataset"] = {
            "rows": int(len(df)),
            "failure_rate": round(float(df[TARGET].mean()), 4),
            "by_machine_type": [
                {"machine_type": r.Machine_Type, "failure_rate": round(float(r["mean"]), 4), "count": int(r["count"])}
                for _, r in by_type.iterrows()
            ],
            "distributions": distributions,
            "class_means": df.groupby(TARGET)[NUMERIC_FEATURES].mean().round(3).to_dict(orient="index"),
        }
    if QUALITY_REPORT_FILE.exists():
        result["quality"] = json.loads(QUALITY_REPORT_FILE.read_text())
    if METRICS_FILE.exists():
        result["training"] = json.loads(METRICS_FILE.read_text())
    return result
