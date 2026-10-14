# Sistema inteligente de mantenimiento predictivo industrial

Sistema de mantenimiento predictivo basado en datos de sensores industriales
(temperatura, vibración, consumo eléctrico y humedad). Incluye un **pipeline ETL**,
**modelos de machine learning** y una **API REST** para predicción en tiempo real.

```
Kaggle ──► Data/landing ──► Extract ──► Transform ──► Load ──► Data/processed + BD (SQLite/PostgreSQL)
                                                                   │
                                                                   ▼
                          API FastAPI ◄── models/failure_model.joblib ◄── Entrenamiento
                         /predict ...                                      (CV + selección)
                              │
                              └──► predictions_log (BD)
```

## Estructura

```
├── Data/landing/                  # Datos crudos (zona de aterrizaje)
├── src/
│   ├── config.py                  # Rutas, columnas, rangos válidos y parámetros
│   ├── etl/
│   │   ├── ingest_data.py         # Descarga del dataset desde Kaggle
│   │   ├── extract.py             # Lectura y validación del esquema
│   │   ├── transform.py           # Limpieza, validación de calidad y outliers
│   │   ├── load.py                # CSV limpio + reporte de calidad + tabla SQL
│   │   └── pipeline.py            # Orquestador ETL
│   ├── models/
│   │   ├── features.py            # Ingeniería de características + preprocesado
│   │   ├── train.py               # Comparación de modelos, umbral y persistencia
│   │   └── predict.py             # Servicio de inferencia
│   └── api/
│       ├── schemas.py             # Esquemas Pydantic (validación de entrada)
│       └── main.py                # Aplicación FastAPI
├── tests/                         # Pruebas de ETL, modelo y API
├── run_pipeline.py                # ETL + entrenamiento en un solo comando
├── Dockerfile / docker-compose.yml
```

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python run_pipeline.py                 # ETL + entrenamiento (usa Data/landing)
python run_pipeline.py --download      # descarga antes el dataset desde Kaggle

uvicorn src.api.main:app --reload      # API en http://localhost:8000/docs
python -m pytest                       # pruebas
```

Cada etapa también puede ejecutarse por separado:
`python -m src.etl.ingest_data`, `python -m src.etl.pipeline`, `python -m src.models.train`.

Con Docker (API + PostgreSQL):

```bash
docker compose up --build
```

## Pipeline ETL

| Etapa | Qué hace |
|---|---|
| **Ingesta** | Descarga `mujtabamatin/dataset-for-machine-failure-detection` de Kaggle a `Data/landing` (se omite si ya hay datos; `--force` para re-descargar). |
| **Extract** | Lee el CSV y valida que existan las columnas requeridas. |
| **Transform** | Conversión de tipos, normalización de `Machine_Type`, eliminación de duplicados, objetivos inválidos y tipos de máquina desconocidos; lecturas fuera de rango físico → nulas; imputación por mediana según tipo de máquina; winsorización de outliers (IQR × 3). Genera un reporte de calidad. |
| **Load** | Escribe `Data/processed/machine_failure_clean.csv`, `data_quality_report.json` y la tabla `sensor_readings` en la base de datos (`DATABASE_URL`, SQLite por defecto). |

## Modelo

- Características derivadas: `Temp_x_Vibration`, `Power_per_Vibration`, `Thermal_Stress`,
  más escalado y one-hot de `Machine_Type`. Todo va dentro de un `Pipeline` de scikit-learn,
  por lo que la API recibe las lecturas crudas.
- Candidatos: regresión logística, Random Forest y Gradient Boosting, comparados con
  validación cruzada estratificada (5 folds, ROC-AUC) frente a un baseline aleatorio.
- El umbral de decisión se ajusta con el estadístico J de Youden sobre predicciones
  out-of-fold; las métricas finales se miden en un conjunto de test (20 %) y se guardan en
  `models/metrics.json`.

> **Nota sobre el dataset actual.** En `machine_failure_dataset.csv` la etiqueta
> `Failure_Risk` es estadísticamente independiente de los sensores (la tasa de fallo es
> ~30 % en todos los quintiles de cada variable), por lo que ningún modelo supera el azar
> (ROC-AUC ≈ 0.5). El entrenamiento lo detecta, emite una advertencia, usa el umbral por
> defecto y expone `has_predictive_signal: false` en `/model/info`. El código es genérico:
> con datos reales etiquetados con el mismo esquema, el pipeline aprende la relación
> (las pruebas lo verifican con datos sintéticos con señal: ROC-AUC > 0.85).

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio y del modelo |
| GET | `/model/info` | Modelo seleccionado, umbral, métricas de test |
| POST | `/predict` | Predicción para una lectura |
| POST | `/predict/batch` | Predicción para hasta 1000 lecturas |

```bash
curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d '{
  "machine_id": "MILL-01", "Temperature": 85.2, "Vibration": 58.1,
  "Power_Usage": 9.4, "Humidity": 39.4, "Machine_Type": "Mill"}'
```

```json
{"machine_id": "MILL-01", "failure_probability": 0.36, "failure_predicted": false,
 "risk_level": "BAJO", "recommendation": "Operación normal; continuar con el monitoreo."}
```

Niveles de riesgo: `BAJO` (< 0.4), `MEDIO` (0.4–0.7), `ALTO` (≥ 0.7), cada uno con una
recomendación de mantenimiento. Las entradas fuera de rango o con tipo de máquina
desconocido se rechazan con `422`. Cada predicción se registra en la tabla
`predictions_log` (desactivable con `LOG_PREDICTIONS=false`).

## Configuración

Variables de entorno (ver `.env.example`): `DATABASE_URL`, `DECISION_THRESHOLD`,
`LOG_PREDICTIONS`, `DATA_DIR`, `MODELS_DIR`.
