"""Endpoints de monitorización de flota, análisis what-if y analítica para el dashboard."""
import json

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.schemas import Component, WhatIfRequest
from src.config import (
    COMPONENTS,
    DATASET_SUMMARY_FILE,
    METRICS_FILE,
    QUALITY_REPORT_FILE,
    SENSOR_LABELS,
    SENSOR_LIMITS_FILE,
    SENSOR_UNITS,
    SENSORS,
)
from src.models.features import NUMERIC_FEATURES
from src.monitoring.replay import sensor_state

router = APIRouter(prefix="/api", tags=["dashboard"])


class WorkOrderRequest(BaseModel):
    technician: str | None = Field(None, max_length=80)
    component: Component | None = None
    notes: str | None = Field(None, max_length=500)


def _read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def fleet_service(request: Request):
    fleet = getattr(request.app.state, "fleet", None)
    if fleet is None:
        raise HTTPException(
            status_code=503,
            detail="Monitorización de flota no disponible: ejecute `python run_pipeline.py` y reinicie la API.",
        )
    return fleet


def machine_or_404(fleet, machine_id: str) -> None:
    if not fleet.has_machine(machine_id):
        raise HTTPException(status_code=404, detail=f"Máquina '{machine_id}' no encontrada.")


@router.get("/config")
def dashboard_config(request: Request):
    from src.api.main import state  # import diferido: main incluye este router

    model = state["predictor"]
    return {
        "sensors": SENSORS,
        "sensor_labels": SENSOR_LABELS,
        "sensor_units": SENSOR_UNITS,
        "sensor_limits": _read_json(SENSOR_LIMITS_FILE),
        "components": COMPONENTS,
        "thresholds": (
            {"alert": model.alert_threshold, "decision": model.threshold, "horizon_hours": model.horizon_hours}
            if model else None
        ),
    }


@router.get("/fleet")
def fleet(request: Request):
    return fleet_service(request).fleet()


@router.get("/fleet/{machine_id}")
def machine_detail(machine_id: str, request: Request, hours: int = 168):
    svc = fleet_service(request)
    machine_or_404(svc, machine_id)
    return svc.machine_detail(machine_id, hours=max(24, min(hours, 168)))


@router.get("/fleet/{machine_id}/inputs")
def machine_inputs(machine_id: str, request: Request):
    svc = fleet_service(request)
    machine_or_404(svc, machine_id)
    return svc.machine_inputs(machine_id)


@router.post("/fleet/{machine_id}/work-orders")
def work_order(machine_id: str, body: WorkOrderRequest, request: Request):
    svc = fleet_service(request)
    machine_or_404(svc, machine_id)
    return svc.register_work_order(machine_id, body.technician, body.component, body.notes)


@router.get("/events")
def events(request: Request, active: bool = False, limit: int = 200):
    return fleet_service(request).event_list(active_only=active, limit=max(1, min(limit, 600)))


@router.post("/events/{event_id}/ack")
def acknowledge(event_id: int, request: Request):
    event = fleet_service(request).acknowledge(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    return event


@router.post("/diagnose")
def diagnose(body: WhatIfRequest):
    """Análisis what-if: riesgo para un estado resumido de máquina. Las variables no
    indicadas (p. ej. la variabilidad de los sensores) toman su valor típico."""
    from src.api.main import predictor

    model = predictor()
    row = dict(model.feature_defaults)
    for s, v in body.sensors.items():
        row[f"{s}_mean_3h"] = row[f"{s}_mean_24h"] = v
    for e, n in body.errors_24h.items():
        row[f"{e}_count_24h"] = n
    for c, d in body.days_since.items():
        row[f"{c}_days_since"] = d
    row.update(age=body.age, model=body.model)
    features = pd.DataFrame([row])
    features[NUMERIC_FEATURES] = features[NUMERIC_FEATURES].astype(float)
    result = model.predict_features(features)[0]
    limits = _read_json(SENSOR_LIMITS_FILE)
    states = {s: sensor_state(limits[s], v) for s, v in body.sensors.items()} if limits else {}
    return {**result, "sensor_states": states}


@router.get("/analytics")
def analytics():
    """Resumen del dataset, calidad del ETL y métricas del entrenamiento."""
    return {
        "dataset": _read_json(DATASET_SUMMARY_FILE),
        "quality": _read_json(QUALITY_REPORT_FILE),
        "training": _read_json(METRICS_FILE),
    }
