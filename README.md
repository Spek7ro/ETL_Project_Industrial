# Sistema inteligente de mantenimiento predictivo industrial

Sistema de mantenimiento predictivo sobre el dataset **Microsoft Azure Predictive Maintenance**
(100 máquinas, telemetría horaria de un año, errores, mantenimientos y fallas por componente).
Incluye un **pipeline ETL**, un **modelo de machine learning** que predice *qué componente fallará
en las próximas 24 h*, una **API REST** para predicción en tiempo real y un **dashboard** que
reproduce la telemetría real hora a hora y mide en vivo si el modelo anticipa las fallas.

```
Kaggle / réplica GitHub ──► Data/landing (5 CSV) ──► Extract ──► Transform ──► Load
                                                                    │            ├─► Data/processed/*.parquet
                                                                    │            └─► Base de datos (SQLite/PostgreSQL)
                                                                    ▼
                                         características por máquina y hora + etiqueta (falla en 24 h)
                                                                    │
                                     Entrenamiento (split temporal, calibración, umbral por costes)
                                                                    │
                     models/failure_model.joblib ──► API FastAPI ──► /predict (ventana de una máquina)
                                                         │
                                                         └─► Dashboard: reproducción del periodo de test
```

## Estructura

```
├── Data/landing/                  # Datos crudos (se descargan; no se versionan)
├── src/
│   ├── config.py                  # Rutas, fuentes, columnas, horizonte, costes
│   ├── etl/
│   │   ├── ingest_data.py         # Descarga (Kaggle → réplica GitHub) + control de integridad
│   │   ├── extract.py             # Lectura y validación del esquema de las 5 tablas
│   │   ├── transform.py           # Limpieza, límites de sensores, características y etiquetas
│   │   ├── load.py                # Parquet + reportes JSON + tablas en la base de datos
│   │   └── pipeline.py            # Orquestador ETL
│   ├── models/
│   │   ├── features.py            # Características compartidas por ETL e inferencia
│   │   ├── train.py               # Comparación de modelos, calibración, umbral, evaluación
│   │   └── predict.py             # Servicio de inferencia
│   ├── monitoring/
│   │   └── replay.py              # Reproducción en tiempo real de la flota
│   └── api/
│       ├── schemas.py             # Esquemas Pydantic
│       ├── dashboard.py           # Endpoints de flota, what-if y analítica
│       └── main.py                # Aplicación FastAPI (sirve también el dashboard)
├── frontend/                      # Dashboard (HTML/CSS/JS + Chart.js local, sin compilación)
├── tests/                         # Pruebas con datos sintéticos en el mismo formato
├── run_pipeline.py                # Ingesta + ETL + entrenamiento en un solo comando
└── Dockerfile / docker-compose.yml
```

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

python run_pipeline.py                 # descarga (~80 MB, solo la 1.ª vez), ETL y entrenamiento (~2 min)
uvicorn src.api.main:app --reload      # Dashboard en http://localhost:8000 · API en /docs
python -m pytest                       # pruebas (no necesitan descargar el dataset)
```

Cada etapa también puede ejecutarse por separado:
`python -m src.etl.ingest_data`, `python -m src.etl.pipeline`, `python -m src.models.train`.

Con Docker (API + PostgreSQL): `docker compose up --build`.

## Datos

| Tabla | Filas | Contenido |
|---|---|---|
| `PdM_telemetry` | 876.100 | Voltaje, rotación, presión y vibración por máquina y hora (2015) |
| `PdM_errors` | 3.919 | Errores del controlador (`error1` … `error5`) |
| `PdM_maint` | 3.286 | Reemplazos de componentes (`comp1` … `comp4`), programados o por falla |
| `PdM_failures` | 761 | Fallas: componente reemplazado por avería |
| `PdM_machines` | 100 | Modelo (`model1` … `model4`) y antigüedad |

La ingesta intenta Kaggle (`arnabbiswas1/microsoft-azure-predictive-maintenance`) y, si no hay
acceso, descarga una réplica pública en GitHub. Esa réplica se verificó contra la copia publicada
por Microsoft (`microsoft/AMLWorkshop`): telemetría, fallas y errores coinciden al 100 %. Tras la
descarga se comprueba el número de filas de cada archivo.

> **El dataset es sintético.** Microsoft lo generó para un tutorial: cada falla va precedida de
> errores del controlador y de la desviación de un sensor concreto. Por eso el modelo alcanza
> métricas casi perfectas. Con telemetría real de planta los resultados serán más modestos,
> aunque el pipeline y la metodología de evaluación son los mismos.

## Pipeline ETL

| Etapa | Qué hace |
|---|---|
| **Extract** | Lee las 5 tablas y valida sus columnas. |
| **Transform** | Tipos y fechas; duplicados; lecturas fuera de rango físico → nulas e interpoladas por máquina; eventos con componente, error o máquina desconocidos se descartan. Calcula **límites de operación** por sensor (percentiles 0,5/2,5/97,5/99,5) y la **tabla de características**. |
| **Load** | Parquet en `Data/processed/`, reportes `data_quality_report.json`, `sensor_limits.json`, `dataset_summary.json`, y las tablas limpias en la base de datos (`DATABASE_URL`). |

**Características** (por máquina, cada 3 h): media y desviación de cada sensor en las últimas 3 h
y 24 h, número de errores de cada tipo en 24 h, días desde el último reemplazo de cada componente,
modelo y antigüedad. **Etiqueta**: componente que falla en las próximas 24 h, o `none`. El mismo
código (`src/models/features.py`) calcula las características en el ETL y en la API, y una prueba
verifica que cada fila solo usa datos anteriores a su instante (sin fuga de información).

## Modelo

- **División temporal**: train (ene–jul) → validación (ago–sep) → test (oct–dic), con un hueco
  de 24 h entre tramos. Nunca se mezclan datos futuros en el entrenamiento.
- **Candidatos**: regresión logística, Random Forest y Gradient Boosting (histogramas), con
  pesos de clase balanceados; se elige por **PR-AUC** en validación (las fallas son el 2 % de las filas).
- **Calibración isotónica** en validación: el dashboard muestra probabilidades interpretables.
- **Umbral de alarma por costes**: minimiza `10 × fallas no anticipadas + 1 × falsas alarmas`
  (configurable con `COST_MISSED_FAILURE` y `COST_FALSE_ALARM`).
- **Evaluación en test por evento**: qué fracción de las fallas reales tuvo una alarma previa,
  con cuánta antelación y si el componente predicho era el correcto.

Resultados en el periodo de test (oct–dic 2015, no visto al entrenar): PR-AUC 0,997 (azar 0,018),
**163 de 163 fallas anticipadas**, antelación mediana 24 h y componente acertado en todas.
Las variables más influyentes son los errores del controlador y la media de 24 h del sensor
asociado a cada componente (comp1 → voltaje, comp2 → rotación, comp3 → presión, comp4 → vibración).

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio y del modelo |
| GET | `/model/info` | Modelo, horizonte, umbrales y métricas de test |
| POST | `/predict` | Riesgo de falla de una máquina a partir de su historia reciente |
| POST | `/predict/batch` | Ídem para hasta 200 máquinas |

`/predict` recibe lo que enviaría una pasarela de planta cada hora: las últimas lecturas
(idealmente 24), los errores recientes y los últimos reemplazos de componentes.

```bash
curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d '{
  "machine_id": "M-012", "model": "model3", "age": 14,
  "telemetry": [
    {"datetime": "2015-10-03T05:00:00", "volt": 168.9, "rotate": 340.8, "pressure": 98.7, "vibration": 41.5},
    {"datetime": "2015-10-03T06:00:00", "volt": 170.4, "rotate": 331.0, "pressure": 99.2, "vibration": 39.8}],
  "errors": [{"datetime": "2015-10-03T05:00:00", "errorID": "error2"}],
  "maintenance": [{"datetime": "2015-09-15T06:00:00", "comp": "comp2"}]}'
```

La respuesta incluye la probabilidad de falla en 24 h, el nivel de riesgo (`BAJO`, `MEDIO`,
`ALTO`), el componente probable, la probabilidad por componente y una recomendación. Cada
predicción se registra en la tabla `predictions_log`.

## Dashboard

El dashboard **reproduce hora a hora la telemetría real del periodo de test** (por defecto, una
hora de planta cada 3 segundos). En cada hora calcula el riesgo de las 100 máquinas con el mismo
código que la API, registra las fallas y mantenimientos reales del dataset y comprueba si el
modelo las había anticipado.

| Vista | Contenido |
|---|---|
| **Resumen de planta** | KPIs (disponibilidad, máquinas por estado, fallas anticipadas, falsas alarmas, alarmas sin reconocer); mapa de las 100 máquinas, tarjetas o tabla; filtros por modelo, estado y búsqueda; máquinas en riesgo y alarmas activas. |
| **Detalle de máquina** | Riesgo de las últimas horas con umbrales y marcas de fallas y mantenimientos reales; probabilidad por componente y días desde su reemplazo; 7 días de sensores (lectura horaria y media de 24 h) con límites de operación; historial de eventos; registro de órdenes de trabajo. |
| **Alarmas y eventos** | Alarmas del modelo con su resultado (confirmada, falsa alarma, en ventana), fallas reales (anticipadas o no), mantenimientos, errores y órdenes de trabajo; reconocimiento individual o masivo. |
| **Análisis what-if** | Parte del estado actual de una máquina y permite cambiar sensores, errores y antigüedad de componentes para ver cómo cambia el riesgo. |
| **Modelo y datos** | Comparación de modelos, variables más influyentes, matriz de confusión, rendimiento por componente, firma de cada falla, datos de origen y calidad del ETL. |

Estados: **Operativo** (riesgo bajo), **En vigilancia** (por encima de la mitad del umbral),
**Crítico** (por encima del umbral de alarma: falla probable en 24 h) y **En falla** (8 h tras
una falla real). Siguiendo la filosofía HMI de ISA-101, el color se reserva para los estados
anómalos y siempre va con icono y texto. Tema claro/oscuro y diseño adaptable a móvil.

Para conectar telemetría real (OPC-UA, MQTT, historiador), basta con alimentar
`FleetReplay._process_hour` con las lecturas de cada hora en lugar de leerlas del dataset.

### Endpoints del dashboard

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/fleet` | Estado de la flota, KPIs y progreso de la reproducción |
| GET | `/api/fleet/{id}` | Detalle, telemetría (7 días), riesgo y eventos de una máquina |
| GET | `/api/fleet/{id}/inputs` | Estado resumido actual (punto de partida del what-if) |
| POST | `/api/fleet/{id}/work-orders` | Registra una orden de trabajo (`technician`, `component`, `notes`) |
| GET | `/api/events` | Eventos (`active=true` para los no reconocidos) |
| POST | `/api/events/{id}/ack` | Reconoce un evento |
| POST | `/api/diagnose` | Riesgo para un estado resumido (what-if) |
| GET | `/api/analytics` | Resumen del dataset, calidad del ETL y métricas del modelo |
| GET | `/api/config` | Sensores, límites de operación y umbrales |

## Configuración

Variables de entorno (ver `.env.example`): `DATABASE_URL`, `HORIZON_HOURS`,
`COST_MISSED_FAILURE`, `COST_FALSE_ALARM`, `LOG_PREDICTIONS`, `DATA_DIR`, `MODELS_DIR`,
`SIMULATION_ENABLED`, `SIM_TICK_SECONDS`, `REPLAY_HOURS_PER_TICK`.
