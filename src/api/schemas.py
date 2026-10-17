"""Esquemas de entrada/salida de la API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Component = Literal["comp1", "comp2", "comp3", "comp4"]
ErrorType = Literal["error1", "error2", "error3", "error4", "error5"]
MachineModel = Literal["model1", "model2", "model3", "model4"]
RiskLevel = Literal["BAJO", "MEDIO", "ALTO"]


class TelemetryReading(BaseModel):
    datetime: datetime
    volt: float = Field(..., ge=0, le=400)
    rotate: float = Field(..., ge=0, le=1000)
    pressure: float = Field(..., ge=0, le=300)
    vibration: float = Field(..., ge=0, le=150)


class ErrorEvent(BaseModel):
    datetime: datetime
    errorID: ErrorType


class MaintenanceEvent(BaseModel):
    datetime: datetime
    comp: Component


class MachineWindow(BaseModel):
    """Historia reciente de una máquina: lo que enviaría una pasarela de planta cada hora.
    Se recomiendan las últimas 24 lecturas horarias, los errores de las últimas 24 h y el
    último reemplazo de cada componente."""
    machine_id: str | None = Field(None, description="Identificador de la máquina")
    model: MachineModel
    age: float = Field(..., ge=0, le=100, description="Antigüedad en años")
    telemetry: list[TelemetryReading] = Field(..., min_length=1, max_length=24 * 14)
    errors: list[ErrorEvent] = Field(default_factory=list, max_length=1000)
    maintenance: list[MaintenanceEvent] = Field(default_factory=list, max_length=1000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "machine_id": "M-012",
                    "model": "model3",
                    "age": 14,
                    "telemetry": [
                        {"datetime": "2015-10-03T04:00:00", "volt": 171.2, "rotate": 352.4, "pressure": 101.3, "vibration": 40.1},
                        {"datetime": "2015-10-03T05:00:00", "volt": 168.9, "rotate": 340.8, "pressure": 98.7, "vibration": 41.5},
                        {"datetime": "2015-10-03T06:00:00", "volt": 170.4, "rotate": 331.0, "pressure": 99.2, "vibration": 39.8},
                    ],
                    "errors": [{"datetime": "2015-10-03T05:00:00", "errorID": "error2"}],
                    "maintenance": [{"datetime": "2015-09-15T06:00:00", "comp": "comp2"}],
                }
            ]
        }
    }


class BatchRequest(BaseModel):
    machines: list[MachineWindow] = Field(..., min_length=1, max_length=200)


class Prediction(BaseModel):
    machine_id: str | None = None
    timestamp: str
    failure_probability: float
    failure_predicted: bool
    risk_level: RiskLevel
    predicted_component: Component | None
    component_probabilities: dict[str, float]
    horizon_hours: int
    recommendation: str


class BatchResponse(BaseModel):
    predictions: list[Prediction]
    total: int
    high_risk_count: int


class WhatIfRequest(BaseModel):
    """Estado resumido de una máquina para el análisis what-if."""
    model: MachineModel
    age: float = Field(..., ge=0, le=100)
    sensors: dict[Literal["volt", "rotate", "pressure", "vibration"], float] = Field(
        ..., description="Media de las últimas 24 h de cada sensor")
    errors_24h: dict[ErrorType, int] = Field(default_factory=dict)
    days_since: dict[Component, float | None] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    model_name: str
    features: list[str]
    horizon_hours: int
    decision_threshold: float
    alert_threshold: float
    trained_at: str | None
    has_predictive_signal: bool
    test_metrics: dict
    test_events: dict


class Health(BaseModel):
    status: str
    model_loaded: bool
