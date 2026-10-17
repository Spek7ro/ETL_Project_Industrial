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
  prediction: "Alarma del modelo",
  failure: "Falla real",
  maintenance: "Mantenimiento programado",
  error: "Error del controlador",
  workorder: "Orden de trabajo",
  system: "Sistema",
};
export const RESOLUTION = {
  pending: { label: "En ventana", tone: "warning" },
  confirmed: { label: "Confirmada", tone: "good" },
  false_alarm: { label: "Falsa alarma", tone: "serious" },
  anticipated: { label: "Anticipada", tone: "good" },
  missed: { label: "No anticipada", tone: "critical" },
};

export const SENSORS = ["volt", "rotate", "pressure", "vibration"];
export const SENSOR_LABEL = { volt: "Voltaje", rotate: "Rotación", pressure: "Presión", vibration: "Vibración" };
export const SENSOR_SHORT = { volt: "Volt.", rotate: "Rot.", pressure: "Pres.", vibration: "Vibr." };
export const SENSOR_STATE_ICON = { warning: "i-warning", critical: "i-critical" };
export const COMPONENTS = ["comp1", "comp2", "comp3", "comp4"];
export const MODEL_LABEL = (m) => (m ? m.replace("model", "Modelo ") : "—");

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

/** Probabilidad como porcentaje legible; < 1 % se muestra como "< 1 %". */
export function riskPct(p) {
  if (p == null) return "—";
  if (p > 0 && p < 0.01) return "< 1 %";
  return `${num(p * 100, 0)} %`;
}

export const STATUS_TONE = { OPERATIVO: "", ALERTA: "warning", CRITICO: "serious", FALLA: "critical" };

export function fmtDays(d) {
  if (d == null) return "sin registro";
  if (d < 1) return `${num(d * 24, 0)} h`;
  return `${num(d, 0)} d`;
}

const dtFmt = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const tFmt = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });

export const fmtDateTime = (iso) => (iso ? dtFmt.format(new Date(iso)) : "—");
export const fmtTime = (ms) => tFmt.format(new Date(ms));
export const fmtDay = (ms) => dayFmt.format(new Date(ms));
