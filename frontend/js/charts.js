// Capa de gráficas: Chart.js con colores tomados de los tokens CSS del tema.
import { fmtDay, num } from "./format.js";

const Chart = window.Chart;
const FONT = "11px system-ui, -apple-system, Segoe UI, sans-serif";

export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function theme() {
  return {
    text: token("--text-primary"),
    text2: token("--text-secondary"),
    muted: token("--axis-muted"),
    grid: token("--grid"),
    baseline: token("--baseline"),
    surface: token("--surface-1"),
    s1: token("--series-1"),
    s2: token("--series-2"),
    projection: token("--projection"),
    good: token("--good"),
    warning: token("--warning"),
    serious: token("--serious"),
    critical: token("--critical"),
  };
}

function label(ctx, text, x, y, align, t) {
  ctx.font = FONT;
  const w = ctx.measureText(text).width;
  const left = align === "right" ? x - w - 6 : x;
  ctx.fillStyle = t.surface;
  ctx.globalAlpha = 0.85;
  ctx.fillRect(left, y, w + 6, 14);
  ctx.globalAlpha = 1;
  ctx.fillStyle = t.text2;
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  ctx.fillText(text, left + 3, y + 1);
}

// ---------------------------------------------------------------- plugins
/** Líneas de umbral con etiqueta; horizontales (eje y) o verticales (eje x). */
const thresholdPlugin = {
  id: "thresholds",
  afterDatasetsDraw(chart, _args, opts) {
    const lines = opts?.lines;
    if (!lines?.length) return;
    const { ctx, chartArea: a, scales } = chart;
    const vertical = opts.axis === "x";
    const scale = vertical ? scales.x : scales.y;
    const t = theme();
    ctx.save();
    // De arriba abajo; si dos etiquetas chocan, la siguiente va bajo su línea
    const sorted = [...lines].sort((p, q) => q.value - p.value);
    let prevBottom = -Infinity;
    for (const l of sorted) {
      if (l.value < scale.min || l.value > scale.max) continue;
      const pos = Math.round(scale.getPixelForValue(l.value)) + 0.5;
      ctx.strokeStyle = l.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      if (vertical) { ctx.moveTo(pos, a.top); ctx.lineTo(pos, a.bottom); } else { ctx.moveTo(a.left, pos); ctx.lineTo(a.right, pos); }
      ctx.stroke();
      ctx.setLineDash([]);
      if (!l.label) continue;
      if (vertical) {
        label(ctx, l.label, pos + 4, a.top + 2, "left", t);
      } else {
        const top = pos - 15 < prevBottom + 2 ? pos + 2 : pos - 15;
        label(ctx, l.label, a.right - 2, top, "right", t);
        prevBottom = top + 14;
      }
    }
    ctx.restore();
  },
};

/** Marcadores verticales de eventos reales (fallas, mantenimientos). */
const markerPlugin = {
  id: "markers",
  afterDatasetsDraw(chart, _args, opts) {
    const marks = opts?.items;
    if (!marks?.length) return;
    const { ctx, chartArea: a, scales } = chart;
    const t = theme();
    ctx.save();
    let row = 0;
    for (const m of marks) {
      const x = Math.round(scales.x.getPixelForValue(m.x)) + 0.5;
      if (x < a.left || x > a.right) continue;
      ctx.strokeStyle = m.color;
      ctx.lineWidth = m.strong ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(x, a.top);
      ctx.lineTo(x, a.bottom);
      ctx.stroke();
      if (m.label) {
        const right = x > a.right - 90;
        label(ctx, m.label, right ? x - 3 : x + 3, a.top + 2 + (row % 3) * 16, right ? "right" : "left", t);
        row += 1;
      }
    }
    ctx.restore();
  },
};

/** Línea vertical de cursor para gráficas de serie temporal. */
const crosshairPlugin = {
  id: "crosshair",
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts?.enabled) return;
    const active = chart.tooltip?.getActiveElements?.() || [];
    if (!active.length) return;
    const x = Math.round(active[0].element.x) + 0.5;
    const { ctx, chartArea: a } = chart;
    ctx.save();
    ctx.strokeStyle = theme().baseline;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, a.top);
    ctx.lineTo(x, a.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

Chart.register(thresholdPlugin, markerPlugin, crosshairPlugin);

function applyDefaults() {
  const t = theme();
  Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = t.text2;
  Chart.defaults.borderColor = t.grid;
  Chart.defaults.animation = false;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.display = false;
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: t.surface,
    titleColor: t.text,
    bodyColor: t.text2,
    borderColor: t.baseline,
    borderWidth: 1,
    padding: 10,
    cornerRadius: 8,
    boxPadding: 4,
    usePointStyle: true,
    titleFont: { weight: "600" },
  });
}
applyDefaults();

const registry = new Set();

function axisStyle(t) {
  return {
    grid: { color: t.grid, drawTicks: false },
    border: { color: t.baseline },
    ticks: { color: t.muted, padding: 6 },
  };
}

function make(canvas, config) {
  const existing = Chart.getChart(canvas);
  if (existing && existing.config.type === config.type) {
    // Actualización en sitio: sin parpadeo y conservando el estado de hover
    existing.data = config.data;
    existing.options = config.options;
    existing.$factory = config.$factory;
    existing.update("none");
    return existing;
  }
  if (existing) { registry.delete(existing); existing.destroy(); }
  const chart = new Chart(canvas, config);
  chart.$factory = config.$factory;
  registry.add(chart);
  return chart;
}

/** Re-aplica el tema a todas las gráficas activas (cambio claro/oscuro). */
export function refreshTheme() {
  applyDefaults();
  for (const c of [...registry]) {
    if (!c.canvas?.isConnected) { registry.delete(c); c.destroy(); continue; }
    if (c.$factory) make(c.canvas, c.$factory());
  }
}

function timeAxis(t, min, max) {
  return {
    type: "linear",
    min,
    max,
    ...axisStyle(t),
    grid: { display: false },
    ticks: { color: t.muted, maxTicksLimit: 7, maxRotation: 0, callback: (v) => fmtDay(v) },
  };
}

// --------------------------------------------------------------- riesgo
export function riskChart(canvas, detail, thresholds) {
  const factory = () => {
    const t = theme();
    const pts = detail.risk_history.map((r) => ({ x: Date.parse(r.timestamp), y: r.p * 100 }));
    const min = pts.length ? pts[0].x : Date.now();
    const max = pts.length ? pts[pts.length - 1].x : Date.now();
    const markers = [
      ...detail.maintenance.map((m) => ({ x: Date.parse(m.timestamp), color: t.muted, label: `Mant. ${m.component}` })),
      ...detail.failures.map((f) => ({ x: Date.parse(f.timestamp), color: t.critical, label: `Falla ${f.component}`, strong: true })),
    ].sort((a, b) => a.x - b.x);
    return {
      type: "line",
      data: {
        datasets: [{
          label: "Riesgo de falla", data: pts, borderColor: t.s1, backgroundColor: t.s1,
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, stepped: false, tension: 0,
        }],
      },
      options: {
        parsing: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: timeAxis(t, min, max),
          y: { min: 0, max: 100, ...axisStyle(t), ticks: { color: t.muted, stepSize: 25, padding: 6, callback: (v) => `${v} %` } },
        },
        plugins: {
          thresholds: {
            lines: [
              { value: thresholds.decision * 100, color: t.critical, label: `Umbral de alarma ${num(thresholds.decision * 100, 0)} %` },
              { value: thresholds.alert * 100, color: t.warning, label: `Vigilancia ${num(thresholds.alert * 100, 0)} %` },
            ],
          },
          markers: { items: markers },
          crosshair: { enabled: true },
          tooltip: {
            callbacks: {
              title: (items) => fmtDay(items[0].parsed.x),
              label: (item) => ` Riesgo: ${num(item.parsed.y, 1)} %`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// ------------------------------------------------------------ sensores
export function sensorChart(canvas, history, sensor, limits, unit, events) {
  const factory = () => {
    const t = theme();
    const pts = history.map((p) => ({ x: Date.parse(p.timestamp), y: p[sensor] }));
    // Media móvil de 24 h: es donde aparece el precursor de la falla
    const mean = pts.map((p, i) => {
      const win = pts.slice(Math.max(0, i - 23), i + 1);
      return { x: p.x, y: win.reduce((acc, q) => acc + q.y, 0) / win.length };
    }).slice(Math.min(23, pts.length - 1));
    const values = pts.map((p) => p.y);
    const lo = Math.min(...values, limits.alarm_low);
    const hi = Math.max(...values, limits.alarm_high);
    const pad = (hi - lo) * 0.06;
    const u = unit ? ` ${unit}` : "";
    return {
      type: "line",
      data: {
        datasets: [
          { label: "Lectura horaria", data: pts, borderColor: t.baseline, backgroundColor: t.baseline, borderWidth: 1, pointRadius: 0, pointHoverRadius: 3, tension: 0 },
          { label: "Media 24 h", data: mean, borderColor: t.s1, backgroundColor: t.s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2 },
        ],
      },
      options: {
        parsing: false,
        interaction: { mode: "index", axis: "x", intersect: false },
        scales: {
          x: timeAxis(t, pts[0].x, pts[pts.length - 1].x),
          y: { suggestedMin: lo - pad, suggestedMax: hi + pad, ...axisStyle(t), ticks: { color: t.muted, maxTicksLimit: 5, padding: 6 } },
        },
        plugins: {
          thresholds: {
            lines: [
              { value: limits.critical_high, color: t.critical, label: `Crítico ${num(limits.critical_high, 0)}` },
              { value: limits.alarm_high, color: t.warning, label: `Alarma ${num(limits.alarm_high, 0)}` },
              { value: limits.alarm_low, color: t.warning, label: `Alarma ${num(limits.alarm_low, 0)}` },
              { value: limits.critical_low, color: t.critical, label: `Crítico ${num(limits.critical_low, 0)}` },
            ],
          },
          markers: { items: events.map((f) => ({ x: Date.parse(f.timestamp), color: t.critical, strong: true })) },
          crosshair: { enabled: true },
          tooltip: {
            callbacks: {
              title: (items) => fmtDay(items[0].parsed.x),
              label: (item) => ` ${item.dataset.label}: ${num(item.parsed.y, 1)}${u}`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// ---------------------------------------------------- barras genéricas
export function barChart(canvas, { labels, values, format, max, reference, horizontal = false, tooltipTitle }) {
  const factory = () => {
    const t = theme();
    const valueAxis = { min: 0, max, ...axisStyle(t), ticks: { color: t.muted, maxTicksLimit: 6, callback: format } };
    const catAxis = { ...axisStyle(t), grid: { display: false }, ticks: { color: t.text2, autoSkip: false } };
    return {
      type: "bar",
      data: { labels, datasets: [{ data: values, backgroundColor: t.s1, borderRadius: 4, borderSkipped: "start", maxBarThickness: horizontal ? 14 : 48 }] },
      options: {
        indexAxis: horizontal ? "y" : "x",
        scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
        plugins: {
          thresholds: {
            axis: horizontal ? "x" : "y",
            lines: reference ? [{ value: reference.value, color: t.projection, label: reference.label }] : [],
          },
          tooltip: {
            callbacks: {
              title: (items) => (tooltipTitle ? tooltipTitle(items[0].dataIndex) : items[0].label),
              label: (item) => ` ${format(horizontal ? item.parsed.x : item.parsed.y)}`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// --------------------------------------------------------------- sparkline
/** Mini tendencia de riesgo (decenas por pantalla: dibujada a mano, sin Chart.js). */
export function sparkline(canvas, values, tone, threshold) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 120;
  const hgt = canvas.clientHeight || 36;
  canvas.width = w * dpr;
  canvas.height = hgt * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, hgt);
  if (!values?.length) return;
  const t = theme();
  const x = (i) => 2 + (i / Math.max(values.length - 1, 1)) * (w - 6);
  const y = (v) => 3 + (1 - v) * (hgt - 6);
  ctx.strokeStyle = t.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, Math.round(y(threshold)) + 0.5);
  ctx.lineTo(w, Math.round(y(threshold)) + 0.5);
  ctx.stroke();
  ctx.strokeStyle = t.s1;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.stroke();
  ctx.fillStyle = t[tone] || t.s1;
  ctx.strokeStyle = t.surface;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x(values.length - 1), y(values[values.length - 1]), 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}
