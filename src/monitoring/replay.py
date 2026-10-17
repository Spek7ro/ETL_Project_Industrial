"""Reproducción en tiempo real de la telemetría de la flota (Azure Predictive Maintenance).

Reproduce hora a hora el periodo de test del dataset, que el modelo no vio durante el
entrenamiento. En cada hora calcula las características de cada máquina con su historia
reciente (el mismo código que usa la API), estima el riesgo de falla y registra los
eventos reales: fallas, mantenimientos programados y errores del controlador.

Como las fallas reales son conocidas, se mide en vivo el desempeño del modelo: fallas
anticipadas, antelación de la alarma y falsas alarmas. Para conectar telemetría real
(OPC-UA, MQTT, historiador) basta con alimentar `_process_hour` desde esa fuente.
"""
import json
import threading
from collections import deque
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import (
    COMPONENTS,
    PROCESSED_DIR,
    REPAIR_HOURS,
    REPLAY_HISTORY_HOURS,
    REPLAY_HOURS_PER_TICK,
    SENSOR_LIMITS_FILE,
    SENSORS,
)
from src.models.features import build_features

STATUS_OK, STATUS_ALERT, STATUS_CRITICAL, STATUS_FAILED = "OPERATIVO", "ALERTA", "CRITICO", "FALLA"
STATUSES = [STATUS_OK, STATUS_ALERT, STATUS_CRITICAL, STATUS_FAILED]
WARMUP_HOURS = 72
MAX_EVENTS = 600
HOUR = pd.Timedelta(hours=1)


def machine_label(machine_id: int) -> str:
    return f"M-{machine_id:03d}"


def sensor_state(limits: dict, value: float) -> str:
    if value <= limits["critical_low"] or value >= limits["critical_high"]:
        return "critical"
    if value <= limits["alarm_low"] or value >= limits["alarm_high"]:
        return "warning"
    return "normal"


@dataclass
class MachineState:
    id: int
    model: str
    age: float
    risk: deque = field(default_factory=lambda: deque(maxlen=REPLAY_HISTORY_HOURS))
    prediction: dict | None = None
    features: dict | None = None
    status: str = STATUS_OK
    failed_until: pd.Timestamp | None = None
    last_failure: dict | None = None
    alarm_event: dict | None = None      # alarma de predicción abierta
    armed: bool = True                   # puede emitir una nueva alarma


class FleetReplay:
    def __init__(self, predictor, data_dir: Path = PROCESSED_DIR, start: str | None = None,
                 hours_per_tick: int = REPLAY_HOURS_PER_TICK):
        data_dir = Path(data_dir)
        self.predictor = predictor
        self.hours_per_tick = hours_per_tick
        self.horizon = pd.Timedelta(hours=predictor.horizon_hours)
        self.lock = threading.RLock()

        tel = pd.read_parquet(data_dir / "telemetry.parquet").sort_values("datetime")
        self.telemetry = tel.reset_index(drop=True)
        self._tel_times = self.telemetry["datetime"].to_numpy()
        self.by_machine = {mid: g.set_index("datetime").sort_index() for mid, g in tel.groupby("machineID")}
        self.errors = pd.read_parquet(data_dir / "errors.parquet")
        self.maint = pd.read_parquet(data_dir / "maint.parquet")
        self.failures = pd.read_parquet(data_dir / "failures.parquet")
        self.machines_df = pd.read_parquet(data_dir / "machines.parquet")
        self.limits = json.loads((data_dir / SENSOR_LIMITS_FILE.name).read_text())

        first = self.telemetry["datetime"].min() + pd.Timedelta(hours=WARMUP_HOURS + 24)
        self.start = max(pd.Timestamp(start or predictor.test_start or first).floor("h"), first)
        self.end = self.telemetry["datetime"].max()
        self._event_ids = count(1)
        self._warming = False
        self._reset(self.start)

    # ------------------------------------------------------------- ciclo
    def _reset(self, start: pd.Timestamp) -> None:
        self.cursor = start - pd.Timedelta(hours=WARMUP_HOURS)
        self.events: deque = deque(maxlen=MAX_EVENTS)
        self.stats = {"failures": 0, "anticipated": 0, "false_alarms": 0, "leads": [], "correct_component": 0}
        self.machines = {
            int(r.machineID): MachineState(id=int(r.machineID), model=r.model, age=float(r.age))
            for r in self.machines_df.itertuples()
        }
        # Precarga: las últimas WARMUP_HOURS horas se procesan en bloque; sus eventos
        # quedan como historial ya reconocido
        hours = pd.date_range(self.cursor + HOUR, start, freq="h")
        feats = self._features(hours)
        preds = self.predictor.predict_features(feats)
        feats = feats.assign(pred=preds)
        self._warming = True
        for h, group in feats.groupby("datetime", sort=True):
            self._process_hour(h, group)
        self._warming = False
        for m in self.machines.values():  # alarmas aún abiertas: pendientes de reconocer
            if m.alarm_event is not None:
                m.alarm_event["acknowledged"] = False
        self.cursor = start

    def step(self) -> None:
        with self.lock:
            for _ in range(self.hours_per_tick):
                nxt = self.cursor + HOUR
                if nxt > self.end:
                    self._reset(self.start)
                    self._emit(None, "info", "system", "Fin del periodo reproducido: la reproducción vuelve a empezar.")
                    return
                feats = self._features(pd.DatetimeIndex([nxt]))
                feats = feats.assign(pred=self.predictor.predict_features(feats))
                self._process_hour(nxt, feats)
                self.cursor = nxt

    def _features(self, hours: pd.DatetimeIndex) -> pd.DataFrame:
        lo = hours.min() - pd.Timedelta(hours=24)
        hi = hours.max()
        i0 = np.searchsorted(self._tel_times, lo.to_datetime64(), side="right")
        i1 = np.searchsorted(self._tel_times, hi.to_datetime64(), side="right")
        tel = self.telemetry.iloc[i0:i1]
        err = self.errors[(self.errors["datetime"] > lo) & (self.errors["datetime"] <= hi)]
        maint = self.maint[self.maint["datetime"] <= hi]
        return build_features(tel, err, maint, self.machines_df, times=hours)

    def _process_hour(self, h: pd.Timestamp, rows: pd.DataFrame) -> None:
        h = pd.Timestamp(h)
        self.cursor = h
        failures_now = self.failures[self.failures["datetime"] == h]
        failed_keys = set()
        for mid, comps in failures_now.groupby("machineID")["failure"]:
            self._on_failure(self.machines[int(mid)], h, sorted(comps))
            failed_keys.add(int(mid))
        for r in self.maint[self.maint["datetime"] == h].itertuples():
            if int(r.machineID) not in failed_keys:
                self._emit(self.machines[int(r.machineID)], "info", "maintenance",
                           f"Mantenimiento programado: reemplazo de {r.comp}.")
        for r in self.errors[self.errors["datetime"] == h].itertuples():
            self._emit(self.machines[int(r.machineID)], "info", "error",
                       f"El controlador registró {r.errorID}.")

        for r in rows.itertuples(index=False):
            m = self.machines[int(r.machineID)]
            pred = r.pred
            m.prediction = pred
            m.features = r._asdict()
            m.risk.append((h, pred["failure_probability"]))
            self._update_alarm(m, h, pred)
            if m.failed_until is not None and h < m.failed_until:
                m.status = STATUS_FAILED
            elif pred["failure_probability"] >= self.predictor.threshold:
                m.status = STATUS_CRITICAL
            elif pred["failure_probability"] >= self.predictor.alert_threshold:
                m.status = STATUS_ALERT
            else:
                m.status = STATUS_OK
        self._expire_alarms(h)

    def _update_alarm(self, m: MachineState, h: pd.Timestamp, pred: dict) -> None:
        p = pred["failure_probability"]
        if m.alarm_event is not None and p >= self.predictor.threshold:
            # La predicción se renueva mientras el riesgo siga sobre el umbral
            m.alarm_event["last_above_threshold"] = h.isoformat()
        elif m.armed and p >= self.predictor.threshold:
            m.armed = False
            m.alarm_event = self._emit(
                m, "serious", "prediction",
                f"Falla probable de {pred['predicted_component']} en las próximas "
                f"{self.predictor.horizon_hours} h (probabilidad {p:.0%}).",
                resolution="pending", component=pred["predicted_component"],
                last_above_threshold=h.isoformat(),
            )
        elif not m.armed and m.alarm_event is None and p < self.predictor.alert_threshold:
            m.armed = True  # el riesgo bajó: se puede volver a alarmar

    def _expire_alarms(self, h: pd.Timestamp) -> None:
        """Una alarma es falsa si pasa todo un horizonte desde la última hora en riesgo
        sin que ocurra la falla."""
        for m in self.machines.values():
            ev = m.alarm_event
            if ev is not None and h >= pd.Timestamp(ev["last_above_threshold"]) + self.horizon:
                ev["resolution"] = "false_alarm"
                self.stats["false_alarms"] += 1
                m.alarm_event = None

    def _on_failure(self, m: MachineState, h: pd.Timestamp, comps: list[str]) -> None:
        self.stats["failures"] += 1
        ev = m.alarm_event
        note = "no anticipada por el modelo"
        if ev is not None:
            lead = (h - pd.Timestamp(ev["timestamp"])).total_seconds() / 3600
            self.stats["anticipated"] += 1
            self.stats["leads"].append(lead)
            self.stats["correct_component"] += int(ev.get("component") in comps)
            ev["resolution"] = "confirmed"
            note = f"anticipada {lead:.0f} h antes por el modelo"
        m.alarm_event = None
        m.armed = True
        m.failed_until = h + pd.Timedelta(hours=REPAIR_HOURS)
        m.last_failure = {"timestamp": h.isoformat(), "components": comps}
        self._emit(m, "critical", "failure", f"Falla de {', '.join(comps)}: reemplazo correctivo ({note}).",
                   resolution="anticipated" if ev is not None else "missed")

    def _emit(self, m: MachineState | None, severity: str, kind: str, message: str, **extra) -> dict:
        event = {
            "id": next(self._event_ids),
            "timestamp": self.cursor.isoformat(),
            "machine_id": machine_label(m.id) if m else None,
            "model": m.model if m else None,
            "severity": severity,   # info | warning | serious | critical
            "kind": kind,           # prediction | failure | maintenance | error | workorder | system
            "message": message,
            "acknowledged": self._warming or kind not in ("prediction", "failure"),
            **extra,
        }
        self.events.appendleft(event)
        return event

    # ----------------------------------------------------------- acciones
    def _machine(self, label: str) -> MachineState:
        try:
            mid = int(label.split("-")[-1])
        except ValueError:
            raise KeyError(label) from None
        if mid not in self.machines:
            raise KeyError(label)
        return self.machines[mid]

    def has_machine(self, label: str) -> bool:
        try:
            self._machine(label)
            return True
        except KeyError:
            return False

    def register_work_order(self, label: str, technician: str | None, component: str | None,
                            notes: str | None) -> dict:
        """Registra una orden de trabajo y reconoce las alarmas abiertas de la máquina.
        La telemetría reproducida es histórica: la orden no altera los datos."""
        with self.lock:
            m = self._machine(label)
            parts = ["Orden de trabajo registrada"]
            if component:
                parts.append(f"para {component}")
            if technician:
                parts.append(f"por {technician}")
            msg = " ".join(parts) + "." + (f" Notas: {notes}" if notes else "")
            for e in self.events:
                if e["machine_id"] == label:
                    e["acknowledged"] = True
            self._emit(m, "info", "workorder", msg)
            return self.machine_summary(m)

    def acknowledge(self, event_id: int) -> dict | None:
        with self.lock:
            for e in self.events:
                if e["id"] == event_id:
                    e["acknowledged"] = True
                    return e
        return None

    # ------------------------------------------------------------ lecturas
    def _latest(self, m: MachineState) -> dict:
        df = self.by_machine[m.id]
        row = df.loc[: self.cursor].iloc[-1]
        return {s: round(float(row[s]), 2) for s in SENSORS}

    def machine_summary(self, m: MachineState) -> dict:
        pred = m.prediction or {}
        sensors = self._latest(m)
        f = m.features or {}
        trend = [round(p, 4) for _, p in list(m.risk)[-48:]]
        return {
            "id": machine_label(m.id),
            "machine_id": m.id,
            "model": m.model,
            "age": m.age,
            "status": m.status,
            "failure_probability": pred.get("failure_probability"),
            "risk_level": pred.get("risk_level"),
            "predicted_component": pred.get("predicted_component"),
            "component_probabilities": pred.get("component_probabilities"),
            "sensors": sensors,
            "sensor_states": {s: sensor_state(self.limits[s], v) for s, v in sensors.items()},
            "risk_trend": trend,
            "errors_24h": int(sum(f.get(f"error{i}_count_24h", 0) for i in range(1, 6))),
            "days_since_replacement": {
                c: (None if pd.isna(f.get(f"{c}_days_since")) else round(float(f[f"{c}_days_since"]), 1))
                for c in COMPONENTS
            },
            "last_failure": m.last_failure,
            "alarm_since": m.alarm_event["timestamp"] if m.alarm_event else None,
        }

    def fleet(self) -> dict:
        with self.lock:
            machines = [self.machine_summary(m) for m in self.machines.values()]
            counts = {s: sum(m["status"] == s for m in machines) for s in STATUSES}
            st = self.stats
            span = (self.end - self.start).total_seconds()
            return {
                "sim_time": self.cursor.isoformat(),
                "hours_per_tick": self.hours_per_tick,
                "replay": {
                    "start": self.start.isoformat(),
                    "end": self.end.isoformat(),
                    "progress_pct": round(100 * (self.cursor - self.start).total_seconds() / span, 1) if span else 100,
                },
                "thresholds": {"alert": self.predictor.alert_threshold, "decision": self.predictor.threshold},
                "horizon_hours": self.predictor.horizon_hours,
                "machines": machines,
                "kpis": {
                    "total": len(machines),
                    "status_counts": counts,
                    "availability_pct": round(100 * (1 - counts[STATUS_FAILED] / len(machines)), 1),
                    "avg_risk": round(float(np.mean([m["failure_probability"] or 0 for m in machines])), 4),
                    "at_risk": counts[STATUS_CRITICAL],
                    "active_alarms": sum(not e["acknowledged"] for e in self.events),
                    "replay_failures": st["failures"],
                    "replay_anticipated": st["anticipated"],
                    "replay_anticipated_rate": round(st["anticipated"] / st["failures"], 4) if st["failures"] else None,
                    "replay_false_alarms": st["false_alarms"],
                    "replay_median_lead_hours": round(float(np.median(st["leads"])), 1) if st["leads"] else None,
                    "replay_correct_component_rate": (
                        round(st["correct_component"] / st["anticipated"], 4) if st["anticipated"] else None
                    ),
                },
            }

    def machine_detail(self, label: str, hours: int = REPLAY_HISTORY_HOURS) -> dict:
        with self.lock:
            m = self._machine(label)
            since = self.cursor - pd.Timedelta(hours=hours)
            tel = self.by_machine[m.id].loc[since + HOUR: self.cursor]
            window = lambda df: df[(df["machineID"] == m.id) & (df["datetime"] > since) & (df["datetime"] <= self.cursor)]
            return {
                **self.machine_summary(m),
                "history": [
                    {"timestamp": t.isoformat(), **{s: round(float(r[s]), 2) for s in SENSORS}}
                    for t, r in tel.iterrows()
                ],
                "risk_history": [{"timestamp": t.isoformat(), "p": round(p, 4)} for t, p in m.risk if t > since],
                "failures": [{"timestamp": r.datetime.isoformat(), "component": r.failure}
                             for r in window(self.failures).itertuples()],
                "maintenance": [{"timestamp": r.datetime.isoformat(), "component": r.comp}
                                for r in window(self.maint).itertuples()],
                "events": [e for e in self.events if e["machine_id"] == label][:50],
            }

    def machine_inputs(self, label: str) -> dict:
        """Entradas actuales de la máquina para el análisis what-if."""
        with self.lock:
            m = self._machine(label)
            f = m.features or {}
            return {
                "model": m.model,
                "age": m.age,
                "sensors": {s: round(float(f.get(f"{s}_mean_24h", 0)), 2) for s in SENSORS},
                "errors_24h": {f"error{i}": int(f.get(f"error{i}_count_24h", 0)) for i in range(1, 6)},
                "days_since": {
                    c: (None if pd.isna(f.get(f"{c}_days_since")) else round(float(f[f"{c}_days_since"]), 1))
                    for c in COMPONENTS
                },
            }

    def event_list(self, active_only: bool = False, limit: int = 200) -> list[dict]:
        with self.lock:
            return [e for e in self.events if not (active_only and e["acknowledged"])][:limit]

