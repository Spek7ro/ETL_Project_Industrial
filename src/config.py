"""Configuración central del proyecto (rutas, columnas y parámetros)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "Data"))
LANDING_DIR = DATA_DIR / "landing"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_FILE = LANDING_DIR / "machine_failure_dataset.csv"
PROCESSED_FILE = PROCESSED_DIR / "machine_failure_clean.csv"
QUALITY_REPORT_FILE = PROCESSED_DIR / "data_quality_report.json"

MODELS_DIR = Path(os.getenv("MODELS_DIR", BASE_DIR / "models"))
MODEL_FILE = MODELS_DIR / "failure_model.joblib"
METRICS_FILE = MODELS_DIR / "metrics.json"

# Base de datos destino de la etapa Load (SQLite por defecto; admite PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'warehouse.db'}")
TABLE_NAME = os.getenv("TABLE_NAME", "sensor_readings")
PREDICTIONS_TABLE = os.getenv("PREDICTIONS_TABLE", "predictions_log")

KAGGLE_DATASET = "mujtabamatin/dataset-for-machine-failure-detection"

NUMERIC_FEATURES = ["Temperature", "Vibration", "Power_Usage", "Humidity"]
CATEGORICAL_FEATURES = ["Machine_Type"]
TARGET = "Failure_Risk"
MACHINE_TYPES = ["Drill", "Lathe", "Mill"]

# Rangos físicamente plausibles para validar lecturas de sensores
VALID_RANGES = {
    "Temperature": (-50.0, 200.0),   # °C
    "Vibration": (0.0, 200.0),       # mm/s
    "Power_Usage": (0.0, 100.0),     # kW
    "Humidity": (0.0, 100.0),        # %
}

RANDOM_STATE = 42
TEST_SIZE = 0.2
DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.5"))

# --- Monitorización de flota (dashboard) ---
FRONTEND_DIR = BASE_DIR / "frontend"
SIMULATION_ENABLED = os.getenv("SIMULATION_ENABLED", "true").lower() == "true"
SIM_TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "3"))      # segundos reales por tick
SIM_MINUTES_PER_TICK = int(os.getenv("SIM_MINUTES_PER_TICK", "10"))  # minutos simulados por tick
SIM_HISTORY_TICKS = 288  # historial precargado (48 h simuladas)
SIM_SEED = int(os.getenv("SIM_SEED", "7"))

# Límites operativos por sensor: (nominal, alarma, crítico). Derivados de la
# distribución del dataset (mediana, ~p93 y ~p99.9) para valores crecientes.
SENSOR_LIMITS = {
    "Temperature": (70.0, 85.0, 100.0),
    "Vibration": (50.0, 58.0, 66.0),
    "Power_Usage": (10.0, 11.5, 13.0),
    "Humidity": (30.0, 50.0, 70.0),
}
SENSOR_UNITS = {"Temperature": "°C", "Vibration": "mm/s", "Power_Usage": "kW", "Humidity": "%"}

# Índice de salud (0-100) -> estado operativo
HEALTH_ALERT = 70.0      # por debajo: ALERTA
HEALTH_CRITICAL = 45.0   # por debajo: CRÍTICO
HEALTH_FAILURE = 15.0    # umbral de falla funcional usado para estimar la vida útil restante
