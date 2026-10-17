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
│   ├── monitoring/
│   │   ├── health.py              # Índice de salud, estados y vida útil restante (RUL)
│   │   └── simulator.py           # Telemetría simulada de la flota con degradación
│   └── api/
│       ├── schemas.py             # Esquemas Pydantic (validación de entrada)
│       ├── dashboard.py           # Endpoints de flota, eventos y analítica
│       └── main.py                # Aplicación FastAPI (sirve también el dashboard)
├── frontend/                      # Dashboard web (HTML/CSS/JS + Chart.js local)
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

uvicorn src.api.main:app --reload      # Dashboard en http://localhost:8000  ·  API en /docs
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

## Dashboard de mantenimiento

Al iniciar la API, `http://localhost:8000/` redirige al dashboard (`/dashboard/`). No requiere
compilación ni conexión a internet: Chart.js se sirve desde `frontend/vendor/`.

| Vista | Contenido |
|---|---|
| **Resumen de planta** | KPIs de disponibilidad, salud media, máquinas por estado, próxima falla estimada y fallas previstas en 24 h. Tarjetas por línea de producción con índice de salud, tendencia, vida útil restante y sensores fuera de límite; vista de tabla; filtros por línea, tipo, estado y búsqueda. Pronóstico de fallas a 72 h y alarmas activas. |
| **Detalle de máquina** | Índice de salud de las últimas 48 h con proyección de la tendencia hasta el umbral de falla funcional, fecha estimada de falla, gráficas de los 4 sensores con sus límites de alarma y críticos (o tabla de lecturas), probabilidad del modelo ML y registro de mantenimiento con técnico y trabajos realizados. |
| **Alarmas y eventos** | Registro de alarmas por condición, predicciones de falla y mantenimientos, con filtros y reconocimiento individual o masivo. |
| **Diagnóstico manual** | Evalúa una lectura puntual (p. ej., ronda de inspección): índice de salud, estado de cada sensor, probabilidad ML y acción recomendada. |
| **Modelo y datos** | Comparación de modelos en validación cruzada frente al baseline aleatorio, matriz de confusión, tasa de falla por tipo, reporte de calidad del ETL y distribución de cada sensor por clase. |

Diseño: siguiendo la filosofía HMI de ISA-101, el color se reserva para estados anómalos y
siempre va acompañado de icono y texto. Incluye tema claro/oscuro y es adaptable a móvil.

### Cómo se calcula el estado de una máquina

- **Índice de salud (0-100)**: desviación de cada sensor respecto a su valor nominal, normalizada
  entre el nominal y el límite crítico (`SENSOR_LIMITS` en `src/config.py`); combina la peor
  desviación con la media ponderada y se suaviza con una media móvil exponencial.
- **Estado**: Operativo (≥ 70), Alerta (45-70), Crítico (< 45), En falla (máquina detenida).
- **Vida útil restante (RUL)**: regresión lineal de la salud en las últimas 4 h, extrapolada hasta
  el umbral de falla funcional (15/100).
- **Probabilidad ML**: el modelo entrenado por el pipeline evalúa cada lectura. Con el dataset
  actual no tiene señal predictiva (ver nota más arriba), así que el dashboard la muestra como
  referencia y basa el estado en el índice de salud por condición.

### Telemetría simulada

Como el dataset no contiene series temporales ni identificadores de máquina, `FleetSimulator`
genera la telemetría de una planta con 12 máquinas en 3 líneas. Cada máquina acumula desgaste
(estable, normal o acelerado) que deriva sus sensores hacia los límites hasta provocar una falla,
que se repara automáticamente a las 6 h simuladas o al registrar un mantenimiento. La simulación
avanza en segundo plano (por defecto 1 ciclo = 10 min de planta cada 3 s) y precarga 48 h de
historial. Para conectar sensores reales (OPC-UA, MQTT, historiador) basta con sustituir el
simulador por una fuente que exponga la misma interfaz (`fleet`, `machine_detail`, `event_list`,
`perform_maintenance`, `acknowledge`).

### Endpoints del dashboard

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/fleet` | Estado actual de la flota y KPIs |
| GET | `/api/fleet/{id}` | Detalle e historial de una máquina |
| POST | `/api/fleet/{id}/maintenance` | Registra un mantenimiento (`technician`, `notes`) |
| GET | `/api/events` | Alarmas y eventos (`active=true` para solo los no reconocidos) |
| POST | `/api/events/{id}/ack` | Reconoce una alarma |
| POST | `/api/diagnose` | Índice de salud + predicción ML de una lectura |
| GET | `/api/analytics` | Resumen del dataset, calidad del ETL y métricas del modelo |
| GET | `/api/config` | Límites de sensores y umbrales de salud |

## Configuración

Variables de entorno (ver `.env.example`): `DATABASE_URL`, `DECISION_THRESHOLD`,
`LOG_PREDICTIONS`, `DATA_DIR`, `MODELS_DIR`, `SIMULATION_ENABLED`, `SIM_TICK_SECONDS`,
`SIM_MINUTES_PER_TICK`, `SIM_SEED`.
