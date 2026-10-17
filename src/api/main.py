"""API REST para predicción de fallas en tiempo real y dashboard de mantenimiento."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine

from src.api.dashboard import router as dashboard_router
from src.api.schemas import BatchRequest, BatchResponse, Health, MachineWindow, ModelInfo, Prediction
from src.config import (
    DATABASE_URL,
    FRONTEND_DIR,
    PREDICTIONS_TABLE,
    PROCESSED_DIR,
    SIM_TICK_SECONDS,
    SIMULATION_ENABLED,
)
from src.models.predict import FailurePredictor, get_predictor
from src.monitoring.replay import FleetReplay

logger = logging.getLogger("predictive_maintenance")
LOG_PREDICTIONS = os.getenv("LOG_PREDICTIONS", "true").lower() == "true"

state: dict = {"predictor": None, "engine": None}


def create_fleet(predictor: FailurePredictor) -> FleetReplay:
    return FleetReplay(predictor, data_dir=PROCESSED_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.update(predictor=None, engine=None)
    try:
        state["predictor"] = get_predictor()
    except FileNotFoundError as exc:
        logger.warning(str(exc))
    if LOG_PREDICTIONS:
        try:
            state["engine"] = create_engine(DATABASE_URL)
        except Exception as exc:  # la API debe funcionar aunque la BD no esté disponible
            logger.warning("No se pudo conectar a la BD de predicciones: %s", exc)

    app.state.fleet = None
    task = None
    if SIMULATION_ENABLED and state["predictor"] is not None:
        try:
            app.state.fleet = create_fleet(state["predictor"])
            task = asyncio.create_task(run_replay(app.state.fleet))
        except FileNotFoundError as exc:
            logger.warning("Monitorización de flota deshabilitada: %s", exc)
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    if state["engine"] is not None:
        state["engine"].dispose()


async def run_replay(fleet: FleetReplay) -> None:
    """Avanza la reproducción de telemetría en segundo plano."""
    while True:
        await asyncio.sleep(SIM_TICK_SECONDS)
        try:
            await asyncio.to_thread(fleet.step)
        except Exception:  # un fallo puntual no debe detener la reproducción
            logger.exception("Error al avanzar la reproducción")


app = FastAPI(
    title="Sistema de Mantenimiento Predictivo Industrial",
    description=(
        "Predice qué componente fallará en las próximas horas a partir de la telemetría, "
        "los errores y el historial de mantenimiento de cada máquina."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


def predictor() -> FailurePredictor:
    if state["predictor"] is None:
        raise HTTPException(
            status_code=503,
            detail="Modelo no disponible. Ejecute el pipeline: python run_pipeline.py",
        )
    return state["predictor"]


def log_predictions(rows: list[dict]) -> None:
    if state["engine"] is None or not rows:
        return
    try:
        flat = [
            {
                "machine_id": r["machine_id"], "timestamp": r["timestamp"],
                "failure_probability": r["failure_probability"], "risk_level": r["risk_level"],
                "predicted_component": r["predicted_component"],
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
            for r in rows
        ]
        pd.DataFrame(flat).to_sql(PREDICTIONS_TABLE, state["engine"], if_exists="append", index=False)
    except Exception as exc:
        logger.warning("No se pudo registrar la predicción: %s", exc)


def predict_machine(window: MachineWindow) -> dict:
    tel = pd.DataFrame([r.model_dump() for r in window.telemetry])
    errors = pd.DataFrame([e.model_dump() for e in window.errors], columns=["datetime", "errorID"])
    maint = pd.DataFrame([m.model_dump() for m in window.maintenance], columns=["datetime", "comp"])
    for df in (tel, errors, maint):
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)
    machine = {"machineID": 0, "model": window.model, "age": window.age}
    return {"machine_id": window.machine_id, **predictor().predict_window(tel, errors, maint, machine)}


app.include_router(dashboard_router)
if FRONTEND_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard/")


@app.get("/health", response_model=Health)
def health():
    loaded = state["predictor"] is not None
    return Health(status="ok" if loaded else "degraded", model_loaded=loaded)


@app.get("/model/info", response_model=ModelInfo)
def model_info():
    model = predictor()
    return ModelInfo(
        model_name=model.model_name,
        features=model.features,
        horizon_hours=model.horizon_hours,
        decision_threshold=round(model.threshold, 4),
        alert_threshold=round(model.alert_threshold, 4),
        trained_at=model.trained_at,
        has_predictive_signal=model.has_predictive_signal,
        test_metrics=model.metrics,
        test_events=model.events,
    )


@app.post("/predict", response_model=Prediction)
def predict(window: MachineWindow):
    result = predict_machine(window)
    log_predictions([result])
    return result


@app.post("/predict/batch", response_model=BatchResponse)
def predict_batch(request: BatchRequest):
    results = [predict_machine(w) for w in request.machines]
    log_predictions(results)
    return BatchResponse(
        predictions=results,
        total=len(results),
        high_risk_count=sum(r["risk_level"] == "ALTO" for r in results),
    )
