"""Simulador de una flota de máquinas con sensores y degradación progresiva.

Sustituye a la telemetría real de planta (OPC-UA / MQTT) para la demostración:
cada máquina tiene un desgaste acumulado que deriva sus sensores hacia los
límites críticos hasta provocar una falla, salvo que se le haga mantenimiento.
"""
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import count

import numpy as np

from src.config import (
    SIM_HISTORY_TICKS,
    SIM_MINUTES_PER_TICK,
    SIM_SEED,
)
from src.monitoring.health import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SEVERITY,
    estimate_rul,
    health_index,
    sensor_state,
    status_from_health,
)
from src.models.predict import risk_level

SENSORS = ["Temperature", "Vibration", "Power_Usage", "Humidity"]
# Deriva de cada sensor con desgaste total (d = 1)
DRIFT = {"Temperature": 34.0, "Vibration": 17.0, "Power_Usage": 3.6, "Humidity": 4.0}
NOISE = {"Temperature": 1.2, "Vibration": 0.7, "Power_Usage": 0.15, "Humidity": 1.0}
TYPE_LABELS = {"Lathe": "Torno CNC", "Mill": "Fresadora", "Drill": "Taladro de columna"}
TYPE_PREFIX = {"Lathe": "TRN", "Mill": "FRS", "Drill": "TLD"}
REPAIR_TICKS = 36            # una falla se repara automáticamente tras 6 h simuladas
MAX_HISTORY = 2 * SIM_HISTORY_TICKS
MAX_EVENTS = 300

FLEET_LAYOUT = [
    ("Línea A · Mecanizado", ["Lathe", "Mill", "Lathe", "Drill"]),
    ("Línea B · Fresado", ["Mill", "Mill", "Drill", "Lathe"]),
    ("Línea C · Perforado", ["Drill", "Drill", "Lathe", "Mill"]),
]


@dataclass
class Machine:
    id: str
    name: str
    machine_type: str
    line: str
    nominal: dict
    wear_rate: float
    wear: float = 0.0
    running: bool = True
    down_ticks: int = 0
    health_ewma: float = 100.0
    status: str = STATUS_OK
    rul_alerted: bool = False
    max_severity: int = 0  # peor estado alcanzado en el ciclo actual (histéresis de alarmas)
    last_maintenance: str | None = None
    ml_probability: float | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=MAX_HISTORY))


class FleetSimulator:
    def __init__(self, predictor=None, seed: int = SIM_SEED,
                 minutes_per_tick: int = SIM_MINUTES_PER_TICK, history_ticks: int = SIM_HISTORY_TICKS):
        self.rng = np.random.default_rng(seed)
        self.predictor = predictor
        self.minutes_per_tick = minutes_per_tick
        self.lock = threading.RLock()
        self.events: deque = deque(maxlen=MAX_EVENTS)
        self._event_ids = count(1)
        self.machines: dict[str, Machine] = {}
        self.sim_time = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
            minutes=minutes_per_tick * history_ticks
        )
        self._build_fleet()
        self._warming_up = True
        for _ in range(history_ticks):
            self.step()
        self._warming_up = False
        self._score_ml()

    # ------------------------------------------------------------------ flota
    def _build_fleet(self) -> None:
        n = 0
        for line_idx, (line, types) in enumerate(FLEET_LAYOUT):
            for pos, mtype in enumerate(types, start=1):
                n += 1
                mid = f"{TYPE_PREFIX[mtype]}-{'ABC'[line_idx]}{pos:02d}"
                nominal = {
                    "Temperature": self.rng.normal(66, 2.5),
                    "Vibration": self.rng.normal(48, 1.5),
                    "Power_Usage": self.rng.normal(9.6, 0.3),
                    "Humidity": self.rng.normal(30, 3),
                }
                # Perfiles de desgaste variados: estables, normales y aceleradas
                profile = self.rng.choice(["stable", "normal", "fast"], p=[0.35, 0.4, 0.25])
                rate = {"stable": 0.0001, "normal": 0.0006, "fast": 0.0015}[profile]
                self.machines[mid] = Machine(
                    id=mid,
                    name=f"{TYPE_LABELS[mtype]} {n:02d}",
                    machine_type=mtype,
                    line=line,
                    nominal=nominal,
                    wear_rate=float(rate * self.rng.uniform(0.7, 1.3)),
                    wear=float(self.rng.uniform(0.0, 0.3)),
                )

    # --------------------------------------------------------------- dinámica
    def _reading(self, m: Machine) -> dict:
        if not m.running:
            # Máquina detenida: se enfría y no vibra ni consume
            last = m.history[-1] if m.history else {"Temperature": 40.0, "Humidity": 30.0}
            return {
                "Temperature": max(25.0, last["Temperature"] - 4 + self.rng.normal(0, 0.5)),
                "Vibration": abs(self.rng.normal(0.3, 0.1)),
                "Power_Usage": abs(self.rng.normal(0.2, 0.05)),
                "Humidity": float(last["Humidity"] + self.rng.normal(0, 0.5)),
            }
        effect = m.wear ** 1.5
        return {
            s: float(m.nominal[s] + DRIFT[s] * effect + self.rng.normal(0, NOISE[s] * (1 + effect)))
            for s in SENSORS
        }

    def _emit(self, m: Machine, severity: str, kind: str, message: str) -> None:
        # Los eventos del historial precargado se consideran ya reconocidos
        self.events.appendleft(
            {
                "id": next(self._event_ids),
                "timestamp": self.sim_time.isoformat(),
                "machine_id": m.id,
                "machine_name": m.name,
                "line": m.line,
                "severity": severity,  # info | warning | serious | critical
                "kind": kind,          # alarm | prediction | maintenance
                "message": message,
                "acknowledged": self._warming_up,
            }
        )

    def step(self) -> None:
        with self.lock:
            self.sim_time += timedelta(minutes=self.minutes_per_tick)
            for m in self.machines.values():
                self._advance(m)
            if not self._warming_up:
                self._score_ml()

    def _advance(self, m: Machine) -> None:
        if m.running:
            m.wear = min(1.0, m.wear + m.wear_rate * (1 + 2.5 * m.wear) * self.rng.uniform(0.5, 1.5))
            if m.wear >= 1.0:
                m.running = False
                m.down_ticks = 0
        else:
            m.down_ticks += 1
            if m.down_ticks >= REPAIR_TICKS:
                self._repair(m, "Reparación correctiva completada; máquina de nuevo en servicio.")

        reading = self._reading(m)
        raw_health = health_index(reading) if m.running else 0.0
        m.health_ewma = raw_health if not m.running else 0.3 * raw_health + 0.7 * m.health_ewma
        health = round(m.health_ewma, 2)
        m.history.append({"timestamp": self.sim_time.isoformat(), **reading, "health": health})

        m.status = status_from_health(health, m.running)
        if STATUS_SEVERITY[m.status] > m.max_severity:
            m.max_severity = STATUS_SEVERITY[m.status]
            sev, msg = {
                "ALERTA": ("warning", f"Salud degradada a {health:.0f}/100. Programar inspección."),
                "CRITICO": ("serious", f"Salud crítica ({health:.0f}/100). Intervención prioritaria."),
                "FALLA": ("critical", "Parada por falla funcional. Requiere reparación."),
            }[m.status]
            self._emit(m, sev, "alarm", msg)

        rul = self.rul(m)["rul_hours"]
        if m.running and rul is not None and rul <= 24 and not m.rul_alerted:
            m.rul_alerted = True
            self._emit(m, "serious", "prediction", f"Falla estimada en {rul:.0f} h si no se interviene.")

    def _repair(self, m: Machine, message: str) -> None:
        m.wear = float(self.rng.uniform(0.0, 0.05))
        m.running = True
        m.down_ticks = 0
        m.health_ewma = 100.0
        m.rul_alerted = False
        m.max_severity = 0
        m.status = STATUS_OK
        m.last_maintenance = self.sim_time.isoformat()
        self._emit(m, "info", "maintenance", message)

    def _score_ml(self) -> None:
        if self.predictor is None:
            return
        running = [m for m in self.machines.values() if m.running]
        if not running:
            return
        records = [{**{s: m.history[-1][s] for s in SENSORS}, "Machine_Type": m.machine_type} for m in running]
        for m, res in zip(running, self.predictor.predict(records)):
            m.ml_probability = res["failure_probability"]
        for m in self.machines.values():
            if not m.running:
                m.ml_probability = None

    # -------------------------------------------------------------- acciones
    def perform_maintenance(self, machine_id: str, technician: str | None = None, notes: str | None = None) -> dict:
        with self.lock:
            m = self.machines[machine_id]
            who = f" por {technician}" if technician else ""
            extra = f" Notas: {notes}" if notes else ""
            self._repair(m, f"Mantenimiento preventivo realizado{who}.{extra}")
            self._score_ml()
            return self.machine_summary(m)

    def acknowledge(self, event_id: int) -> dict | None:
        with self.lock:
            for e in self.events:
                if e["id"] == event_id:
                    e["acknowledged"] = True
                    return e
        return None

    # -------------------------------------------------------------- lecturas
    def rul(self, m: Machine) -> dict:
        if not m.running:
            return {"rul_hours": 0.0, "slope_per_hour": 0.0}
        return estimate_rul([h["health"] for h in m.history], self.minutes_per_tick)

    def machine_summary(self, m: Machine) -> dict:
        last = m.history[-1]
        rul = self.rul(m)
        failure_at = None
        if m.running and rul["rul_hours"] is not None:
            failure_at = (self.sim_time + timedelta(hours=rul["rul_hours"])).isoformat()
        return {
            "id": m.id,
            "name": m.name,
            "machine_type": m.machine_type,
            "type_label": TYPE_LABELS[m.machine_type],
            "line": m.line,
            "status": m.status,
            "running": m.running,
            "health": last["health"],
            "rul_hours": rul["rul_hours"],
            "health_slope_per_hour": rul["slope_per_hour"],
            "predicted_failure_at": failure_at,
            "ml_probability": m.ml_probability,
            "ml_risk_level": risk_level(m.ml_probability) if m.ml_probability is not None else None,
            "last_maintenance": m.last_maintenance,
            "sensors": {s: round(last[s], 2) for s in SENSORS},
            "sensor_states": {s: sensor_state(s, last[s]) for s in SENSORS} if m.running else
                             {s: "normal" for s in SENSORS},
            "health_trend": [h["health"] for h in list(m.history)[-36:]],
        }

    def fleet(self) -> dict:
        with self.lock:
            machines = [self.machine_summary(m) for m in self.machines.values()]
            counts = {s: sum(m["status"] == s for m in machines) for s in STATUS_SEVERITY}
            upcoming = sorted(
                (m for m in machines if m["running"] and m["rul_hours"] is not None),
                key=lambda m: m["rul_hours"],
            )
            return {
                "sim_time": self.sim_time.isoformat(),
                "minutes_per_tick": self.minutes_per_tick,
                "machines": machines,
                "kpis": {
                    "total": len(machines),
                    "status_counts": counts,
                    "availability_pct": round(100 * sum(m["running"] for m in machines) / len(machines), 1),
                    "avg_health": round(float(np.mean([m["health"] for m in machines])), 1),
                    "failures_next_24h": sum(m["rul_hours"] <= 24 for m in upcoming),
                    "next_failure": (
                        {"id": upcoming[0]["id"], "name": upcoming[0]["name"], "rul_hours": upcoming[0]["rul_hours"]}
                        if upcoming else None
                    ),
                    "active_alarms": sum(
                        not e["acknowledged"] and e["kind"] != "maintenance" for e in self.events
                    ),
                },
            }

    def machine_detail(self, machine_id: str, points: int = SIM_HISTORY_TICKS) -> dict:
        with self.lock:
            m = self.machines[machine_id]
            return {
                **self.machine_summary(m),
                "history": list(m.history)[-points:],
                "events": [e for e in self.events if e["machine_id"] == machine_id][:50],
            }

    def event_list(self, active_only: bool = False, limit: int = 100) -> list[dict]:
        with self.lock:
            events = [e for e in self.events if not (active_only and (e["acknowledged"] or e["kind"] == "maintenance"))]
            return events[:limit]
