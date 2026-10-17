"""API REST para predicción de fallos en tiempo real."""
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

from src.api.schemas import BatchRequest, BatchResponse, Health, ModelInfo, Prediction, SensorReading
from src.config import (
    DATABASE_URL,
    FRONTEND_DIR,
    PREDICTIONS_TABLE,
    SIM_TICK_SECONDS,
    SIMULATION_ENABLED,
)
from src.models.predict import FailurePredictor, get_predictor
from src.monitoring.health import health_index, sensor_state, status_from_health
from src.monitoring.simulator import FleetSimulator

logger = logging.getLogger("predictive_maintenance")
LOG_PREDICTIONS = os.getenv("LOG_PREDICTIONS", "true").lower() == "true"

state: dict = {"predictor": None, "engine": None}


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

    app.state.simulator = None
    task = None
    if SIMULATION_ENABLED:
        app.state.simulator = FleetSimulator(predictor=state["predictor"])
        task = asyncio.create_task(run_simulation(app.state.simulator))
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    if state["engine"] is not None:
        state["engine"].dispose()


async def run_simulation(sim: FleetSimulator) -> None:
    """Avanza la telemetría simulada de la flota en segundo plano."""
    while True:
        await asyncio.sleep(SIM_TICK_SECONDS)
        try:
            await asyncio.to_thread(sim.step)
        except Exception:  # un fallo puntual no debe detener la simulación
            logger.exception("Error al avanzar la simulación")


app = FastAPI(
    title="Sistema de Mantenimiento Predictivo Industrial",
    description="Predicción en tiempo real del riesgo de fallo de máquinas a partir de sensores.",
    version="1.0.0",
    lifespan=lifespan,
)


def predictor() -> FailurePredictor:
    if state["predictor"] is None:
        raise HTTPException(
            status_code=503,
            detail="Modelo no disponible. Ejecute el entrenamiento: python -m src.models.train",
        )
    return state["predictor"]


def log_predictions(readings: list[SensorReading], results: list[dict]) -> None:
    if state["engine"] is None:
        return
    try:
        rows = [
            {**r.model_dump(), **res, "predicted_at": datetime.now(timezone.utc).isoformat()}
            for r, res in zip(readings, results)
        ]
        pd.DataFrame(rows).to_sql(PREDICTIONS_TABLE, state["engine"], if_exists="append", index=False)
    except Exception as exc:
        logger.warning("No se pudo registrar la predicción: %s", exc)


def run_prediction(readings: list[SensorReading]) -> list[Prediction]:
    model = predictor()
    results = model.predict([r.model_dump(exclude={"machine_id"}) for r in readings])
    log_predictions(readings, results)
    return [Prediction(machine_id=r.machine_id, **res) for r, res in zip(readings, results)]


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
        decision_threshold=round(model.threshold, 4),
        trained_at=model.trained_at,
        has_predictive_signal=model.has_predictive_signal,
        test_metrics=model.metrics,
    )


@app.post("/predict", response_model=Prediction)
def predict(reading: SensorReading):
    return run_prediction([reading])[0]


@app.post("/predict/batch", response_model=BatchResponse)
def predict_batch(request: BatchRequest):
    predictions = run_prediction(request.readings)
    return BatchResponse(
        predictions=predictions,
        total=len(predictions),
        high_risk_count=sum(p.risk_level == "ALTO" for p in predictions),
    )


@app.post("/api/diagnose", tags=["dashboard"])
def diagnose(reading: SensorReading):
    """Diagnóstico de una lectura: índice de salud por condición + predicción del modelo."""
    values = reading.model_dump(exclude={"machine_id"})
    health = health_index(values)
    ml = None
    if state["predictor"] is not None:
        ml = run_prediction([reading])[0].model_dump()
    return {
        "health": health,
        "status": status_from_health(health),
        "sensor_states": {k: sensor_state(k, values[k]) for k in ("Temperature", "Vibration", "Power_Usage", "Humidity")},
        "ml": ml,
    }
