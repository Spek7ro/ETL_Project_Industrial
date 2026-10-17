"""Configuración central del proyecto (rutas, columnas y parámetros)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Rutas -----------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "Data"))
LANDING_DIR = DATA_DIR / "landing"
PROCESSED_DIR = DATA_DIR / "processed"
QUALITY_REPORT_FILE = PROCESSED_DIR / "data_quality_report.json"
SENSOR_LIMITS_FILE = PROCESSED_DIR / "sensor_limits.json"
FEATURES_FILE = PROCESSED_DIR / "features.parquet"
DATASET_SUMMARY_FILE = PROCESSED_DIR / "dataset_summary.json"

MODELS_DIR = Path(os.getenv("MODELS_DIR", BASE_DIR / "models"))
MODEL_FILE = MODELS_DIR / "failure_model.joblib"
METRICS_FILE = MODELS_DIR / "metrics.json"
FRONTEND_DIR = BASE_DIR / "frontend"

# Base de datos destino de la etapa Load (SQLite por defecto; admite PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'warehouse.db'}")
PREDICTIONS_TABLE = os.getenv("PREDICTIONS_TABLE", "predictions_log")

# --- Dataset: Microsoft Azure Predictive Maintenance -------------------------
# 100 máquinas, telemetría horaria de 2015, errores, mantenimientos y fallas.
KAGGLE_DATASET = "arnabbiswas1/microsoft-azure-predictive-maintenance"
# Réplica pública en GitHub (verificada contra la copia publicada por Microsoft)
MIRROR_BASE_URL = (
    "https://raw.githubusercontent.com/ashishpatel26/"
    "Predictive_Maintenance_using_Machine-Learning_Microsoft_Casestudy/master/data"
)
SOURCE_FILES = {
    "telemetry": "PdM_telemetry.csv",
    "errors": "PdM_errors.csv",
    "maint": "PdM_maint.csv",
    "failures": "PdM_failures.csv",
    "machines": "PdM_machines.csv",
}
# Filas esperadas en la versión original (control de integridad de la descarga)
EXPECTED_ROWS = {"telemetry": 876100, "errors": 3919, "maint": 3286, "failures": 761, "machines": 100}

SENSORS = ["volt", "rotate", "pressure", "vibration"]
COMPONENTS = ["comp1", "comp2", "comp3", "comp4"]
ERROR_TYPES = ["error1", "error2", "error3", "error4", "error5"]
MACHINE_MODELS = ["model1", "model2", "model3", "model4"]
NO_FAILURE = "none"
CLASSES = [NO_FAILURE] + COMPONENTS

# Rangos físicamente plausibles: lecturas fuera de ellos se tratan como error de sensor
VALID_RANGES = {
    "volt": (0.0, 400.0),
    "rotate": (0.0, 1000.0),
    "pressure": (0.0, 300.0),
    "vibration": (0.0, 150.0),
}

# --- Modelo ----------------------------------------------------------------
HORIZON_HOURS = int(os.getenv("HORIZON_HOURS", "24"))   # ¿falla en las próximas N horas?
SAMPLE_EVERY_HOURS = 3                                 # muestreo de filas de entrenamiento
SPLIT_FRACTIONS = (0.6, 0.75)                          # train | validación | test (por tiempo)
RANDOM_STATE = 42
# Costes relativos para elegir el umbral: una falla no anticipada (parada no
# planificada) cuesta mucho más que una inspección por falsa alarma.
COST_MISSED_FAILURE = float(os.getenv("COST_MISSED_FAILURE", "10"))
COST_FALSE_ALARM = float(os.getenv("COST_FALSE_ALARM", "1"))
# Por debajo de este ROC-AUC se considera que los datos no tienen señal útil
MIN_USEFUL_ROC_AUC = 0.6

# --- Monitorización de flota (dashboard) ------------------------------------
# Reproduce la telemetría real del periodo de test (no visto en entrenamiento)
SIMULATION_ENABLED = os.getenv("SIMULATION_ENABLED", "true").lower() == "true"
SIM_TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "3"))       # segundos reales por ciclo
REPLAY_HOURS_PER_TICK = int(os.getenv("REPLAY_HOURS_PER_TICK", "1"))  # horas de planta por ciclo
REPLAY_HISTORY_HOURS = 168   # historial visible en el detalle de máquina (7 días)
REPAIR_HOURS = 8             # horas que una máquina figura "en falla" tras una falla real

SENSOR_LABELS = {"volt": "Voltaje", "rotate": "Rotación", "pressure": "Presión", "vibration": "Vibración"}
# El dataset original no especifica unidades para presión y vibración
SENSOR_UNITS = {"volt": "V", "rotate": "rpm", "pressure": "", "vibration": ""}
