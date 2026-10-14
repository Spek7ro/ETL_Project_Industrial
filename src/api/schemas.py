"""Esquemas de entrada/salida de la API."""
from typing import Literal

from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    machine_id: str | None = Field(None, description="Identificador opcional de la máquina")
    Temperature: float = Field(..., ge=-50, le=200, description="Temperatura (°C)")
    Vibration: float = Field(..., ge=0, le=200, description="Vibración (mm/s)")
    Power_Usage: float = Field(..., ge=0, le=100, description="Consumo eléctrico (kW)")
    Humidity: float = Field(..., ge=0, le=100, description="Humedad relativa (%)")
    Machine_Type: Literal["Drill", "Lathe", "Mill"]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "machine_id": "MILL-01",
                    "Temperature": 85.2,
                    "Vibration": 58.1,
                    "Power_Usage": 9.4,
                    "Humidity": 39.4,
                    "Machine_Type": "Mill",
                }
            ]
        }
    }


class BatchRequest(BaseModel):
    readings: list[SensorReading] = Field(..., min_length=1, max_length=1000)


class Prediction(BaseModel):
    machine_id: str | None = None
    failure_probability: float
    failure_predicted: bool
    risk_level: Literal["BAJO", "MEDIO", "ALTO"]
    recommendation: str


class BatchResponse(BaseModel):
    predictions: list[Prediction]
    total: int
    high_risk_count: int


class ModelInfo(BaseModel):
    model_name: str
    features: list[str]
    decision_threshold: float
    trained_at: str | None
    has_predictive_signal: bool
    test_metrics: dict


class Health(BaseModel):
    status: str
    model_loaded: bool
