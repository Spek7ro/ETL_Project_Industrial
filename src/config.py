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
