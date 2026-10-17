// Etiquetas, iconos y formateadores compartidos.

export const STATUS = {
  OPERATIVO: { label: "Operativo", icon: "i-ok", tone: "good" },
  ALERTA: { label: "Alerta", icon: "i-warning", tone: "warning" },
  CRITICO: { label: "Crítico", icon: "i-serious", tone: "serious" },
  FALLA: { label: "En falla", icon: "i-critical", tone: "critical" },
};
export const STATUS_ORDER = ["FALLA", "CRITICO", "ALERTA", "OPERATIVO"];

export const SEVERITY = {
  critical: { label: "Crítica", icon: "i-critical", tone: "critical" },
  serious: { label: "Alta", icon: "i-serious", tone: "serious" },
  warning: { label: "Media", icon: "i-warning", tone: "warning" },
  info: { label: "Informativa", icon: "i-info", tone: "info" },
};
export const EVENT_KIND = {
  alarm: "Alarma por condición",
  prediction: "Predicción de falla",
  maintenance: "Mantenimiento",
};

export const SENSORS = ["Temperature", "Vibration", "Power_Usage", "Humidity"];
export const SENSOR_LABEL = {
  Temperature: "Temperatura",
  Vibration: "Vibración",
  Power_Usage: "Consumo eléctrico",
  Humidity: "Humedad",
};
export const SENSOR_SHORT = { Temperature: "Temp.", Vibration: "Vibr.", Power_Usage: "Pot.", Humidity: "Hum." };
export const SENSOR_STATE_ICON = { warning: "i-warning", critical: "i-critical" };
export const TYPE_LABEL = { Lathe: "Torno CNC", Mill: "Fresadora", Drill: "Taladro de columna" };

const esc = document.createElement("div");
export function h(value) {
  esc.textContent = value == null ? "" : String(value);
  return esc.innerHTML;
}

export function icon(id, cls = "") {
  return `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;
}

export function statusBadge(status, big = false) {
  const s = STATUS[status];
  return `<span class="status s-${status}${big ? " big" : ""}">${icon(s.icon)}${s.label}</span>`;
}

export function severityIcon(sev) {
  const s = SEVERITY[sev] || SEVERITY.info;
  return icon(s.icon, `ic-${s.tone}`);
}

export const num = (v, d = 1) =>
  v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });

export function pct(v, d = 0) {
  return v == null ? "—" : `${num(v * 100, d)} %`;
}

/** Vida útil restante en texto legible. */
export function fmtRul(hours, running = true) {
  if (!running) return "Detenida";
  if (hours == null) return "Estable";
  if (hours <= 0.5) return "Inminente";
  if (hours >= 720) return "> 30 días";
  if (hours < 48) return `${num(hours, hours < 10 ? 1 : 0)} h`;
  const d = Math.floor(hours / 24);
  const rem = Math.round(hours - d * 24);
  return rem ? `${d} d ${rem} h` : `${d} d`;
}

export function rulTone(hours, running = true) {
  if (!running) return "critical";
  if (hours == null) return "";
  if (hours <= 24) return "critical";
  if (hours <= 72) return "serious";
  if (hours <= 168) return "warning";
  return "";
}

const dtFmt = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const tFmt = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });

export const fmtDateTime = (iso) => (iso ? dtFmt.format(new Date(iso)) : "—");
export const fmtTime = (ms) => tFmt.format(new Date(ms));
export const fmtDay = (ms) => dayFmt.format(new Date(ms));
