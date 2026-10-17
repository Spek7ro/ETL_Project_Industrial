// Capa de gráficas: Chart.js con colores tomados de los tokens CSS del tema.
import { fmtDay, fmtTime, num } from "./format.js";

const Chart = window.Chart;

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

// ---------------------------------------------------------------- plugins
/** Líneas de umbral horizontales con su etiqueta (alarma, crítico, falla). */
const thresholdPlugin = {
  id: "thresholds",
  afterDatasetsDraw(chart, _args, opts) {
    const lines = opts?.lines;
    if (!lines?.length) return;
    const { ctx, chartArea: a, scales } = chart;
    const y = scales.y;
    const t = theme();
    ctx.save();
    ctx.font = "11px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.textBaseline = "bottom";
    ctx.textAlign = "right";
    // De arriba abajo; si dos etiquetas chocan, la siguiente se dibuja bajo su línea
    const sorted = [...lines].sort((p, q) => q.value - p.value);
    let prevLabelY = -Infinity;
    for (const l of sorted) {
      if (l.value < y.min || l.value > y.max) continue;
      const py = Math.round(y.getPixelForValue(l.value)) + 0.5;
      ctx.strokeStyle = l.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(a.left, py);
      ctx.lineTo(a.right, py);
      ctx.stroke();
      if (l.label) {
        ctx.setLineDash([]);
        const w = ctx.measureText(l.label).width;
        const below = py - 15 < prevLabelY + 2;
        const top = below ? py + 2 : py - 15;
        ctx.fillStyle = t.surface;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(a.right - w - 8, top, w + 6, 14);
        ctx.globalAlpha = 1;
        ctx.fillStyle = t.text2;
        ctx.fillText(l.label, a.right - 4, top + 13);
        prevLabelY = top + 14;
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

/** Línea vertical "ahora" que separa historia y proyección. */
const nowLinePlugin = {
  id: "nowLine",
  afterDatasetsDraw(chart, _args, opts) {
    if (opts?.value == null) return;
    const { ctx, chartArea: a, scales } = chart;
    const x = Math.round(scales.x.getPixelForValue(opts.value)) + 0.5;
    if (x < a.left || x > a.right) return;
    const t = theme();
    ctx.save();
    ctx.strokeStyle = t.muted;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, a.top);
    ctx.lineTo(x, a.bottom);
    ctx.stroke();
    ctx.fillStyle = t.text2;
    ctx.font = "11px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("Ahora", x + 4, a.top + 2);
    ctx.restore();
  },
};

Chart.register(thresholdPlugin, crosshairPlugin, nowLinePlugin);

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
  const spanH = (max - min) / 3.6e6;
  return {
    type: "linear",
    min,
    max,
    ...axisStyle(t),
    grid: { display: false },
    ticks: {
      color: t.muted,
      maxTicksLimit: 7,
      maxRotation: 0,
      callback: (v) => (spanH > 30 ? fmtDay(v) : fmtTime(v)),
    },
  };
}

// ------------------------------------------------------------ health chart
export function healthChart(canvas, detail, cfg) {
  const factory = () => {
    const t = theme();
    const pts = detail.history.map((p) => ({ x: Date.parse(p.timestamp), y: p.health }));
    const last = pts[pts.length - 1];
    const projection = [];
    let max = last.x;
    if (detail.running && detail.rul_hours != null && detail.health_slope_per_hour < 0) {
      const horizon = Math.min(detail.rul_hours, 72);
      const end = last.x + horizon * 3.6e6;
      projection.push({ x: last.x, y: last.y }, { x: end, y: Math.max(0, last.y + detail.health_slope_per_hour * horizon) });
      max = end;
    }
    max = Math.max(max, last.x + 6 * 3.6e6);
    const th = cfg.health_thresholds;
    return {
      type: "line",
      data: {
        datasets: [
          { label: "Índice de salud", data: pts, borderColor: t.s1, backgroundColor: t.s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 },
          { label: "Proyección", data: projection, borderColor: t.projection, backgroundColor: t.projection, borderWidth: 2, borderDash: [6, 5], pointRadius: [0, 4], pointHoverRadius: 4 },
        ],
      },
      options: {
        parsing: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: timeAxis(t, pts[0].x, max),
          y: { min: 0, max: 100, ...axisStyle(t), ticks: { color: t.muted, stepSize: 25, padding: 6 } },
        },
        plugins: {
          thresholds: {
            lines: [
              { value: th.alert, color: t.warning, label: `Alerta ${th.alert}` },
              { value: th.critical, color: t.serious, label: `Crítico ${th.critical}` },
              { value: th.failure, color: t.critical, label: `Falla funcional ${th.failure}` },
            ],
          },
          crosshair: { enabled: true },
          nowLine: { value: last.x },
          tooltip: {
            callbacks: {
              title: (items) => fmtDay(items[0].parsed.x),
              label: (item) => ` ${item.dataset.label}: ${num(item.parsed.y, 1)} / 100`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// ------------------------------------------------------------ sensor chart
export function sensorChart(canvas, history, sensor, limits, unit) {
  const factory = () => {
    const t = theme();
    const pts = history.map((p) => ({ x: Date.parse(p.timestamp), y: p[sensor] }));
    const values = pts.map((p) => p.y);
    const lo = Math.min(...values, limits.nominal);
    const hi = Math.max(...values, limits.critical);
    const pad = (hi - lo) * 0.08 || 1;
    return {
      type: "line",
      data: { datasets: [{ label: sensor, data: pts, borderColor: t.s1, backgroundColor: t.s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2 }] },
      options: {
        parsing: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: timeAxis(t, pts[0].x, pts[pts.length - 1].x),
          y: { suggestedMin: Math.max(0, lo - pad), suggestedMax: hi + pad, ...axisStyle(t), ticks: { color: t.muted, maxTicksLimit: 5, padding: 6 } },
        },
        plugins: {
          thresholds: {
            lines: [
              { value: limits.alarm, color: t.warning, label: `Alarma ${num(limits.alarm, 1)}` },
              { value: limits.critical, color: t.critical, label: `Crítico ${num(limits.critical, 1)}` },
            ],
          },
          crosshair: { enabled: true },
          tooltip: {
            callbacks: {
              title: (items) => fmtDay(items[0].parsed.x),
              label: (item) => ` ${num(item.parsed.y, 2)} ${unit}`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// ---------------------------------------------------------- forecast chart
export function forecastChart(canvas, rows) {
  const factory = () => {
    const t = theme();
    const color = { OPERATIVO: t.good, ALERTA: t.warning, CRITICO: t.serious, FALLA: t.critical };
    return {
      type: "bar",
      data: {
        labels: rows.map((r) => r.id),
        datasets: [{
          label: "Horas hasta la falla",
          data: rows.map((r) => Math.max(r.rul_hours, 0.5)),
          backgroundColor: rows.map((r) => color[r.status]),
          borderRadius: 4,
          borderSkipped: "start",
          barThickness: 14,
        }],
      },
      options: {
        indexAxis: "y",
        onHover: (e, els) => { e.native.target.style.cursor = els.length ? "pointer" : "default"; },
        onClick: (_e, els) => { if (els.length) location.hash = `#/machine/${rows[els[0].index].id}`; },
        scales: {
          x: { min: 0, max: 72, ...axisStyle(t), ticks: { color: t.muted, stepSize: 12, callback: (v) => `${v} h` } },
          y: { ...axisStyle(t), grid: { display: false }, ticks: { color: t.text2, font: { weight: "600" } } },
        },
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => `${rows[items[0].dataIndex].id} · ${rows[items[0].dataIndex].name}`,
              label: (item) => ` Falla estimada en ${num(rows[item.dataIndex].rul_hours, 1)} h`,
              afterLabel: (item) => ` Salud actual: ${num(rows[item.dataIndex].health, 0)} / 100`,
            },
          },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

// --------------------------------------------------------- analytics charts
export function barChart(canvas, { labels, values, format, max, reference, yTitle }) {
  const factory = () => {
    const t = theme();
    return {
      type: "bar",
      data: { labels, datasets: [{ data: values, backgroundColor: t.s1, borderRadius: 4, borderSkipped: "start", maxBarThickness: 48 }] },
      options: {
        scales: {
          x: { ...axisStyle(t), grid: { display: false }, ticks: { color: t.text2 } },
          y: { min: 0, max, ...axisStyle(t), title: { display: !!yTitle, text: yTitle, color: t.muted }, ticks: { color: t.muted, maxTicksLimit: 6, callback: format } },
        },
        plugins: {
          thresholds: { lines: reference ? [{ value: reference.value, color: t.projection, label: reference.label }] : [] },
          tooltip: { callbacks: { label: (item) => ` ${format(item.parsed.y)}` } },
        },
      },
      $factory: factory,
    };
  };
  return make(canvas, factory());
}

/** Distribución de un sensor por clase (porcentaje dentro de cada clase). */
export function distributionChart(canvas, dist, unit) {
  const factory = () => {
    const t = theme();
    const norm = (arr) => { const s = arr.reduce((a, b) => a + b, 0) || 1; return arr.map((v) => (100 * v) / s); };
    const ok = norm(dist.ok);
    const fail = norm(dist.failure);
    return {
      type: "line",
      data: {
        labels: dist.bin_centers,
        datasets: [
          { label: "Sin falla", data: ok, borderColor: t.s1, backgroundColor: t.s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.3 },
          { label: "Con falla", data: fail, borderColor: t.s2, backgroundColor: t.s2, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.3 },
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { type: "category", ...axisStyle(t), grid: { display: false }, ticks: { color: t.muted, maxTicksLimit: 6, maxRotation: 0, callback: (_v, i) => num(dist.bin_centers[i], 0) } },
          y: { min: 0, ...axisStyle(t), ticks: { color: t.muted, maxTicksLimit: 5, callback: (v) => `${v} %` } },
        },
        plugins: {
          crosshair: { enabled: true },
          tooltip: {
            callbacks: {
              title: (items) => `≈ ${num(dist.bin_centers[items[0].dataIndex], 1)} ${unit}`,
              label: (item) => ` ${item.dataset.label}: ${num(item.parsed.y, 1)} % de la clase`,
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
/** Mini tendencia de salud dibujada a mano (12+ por pantalla, sin Chart.js). */
export function sparkline(canvas, values, tone) {
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
  const min = Math.min(0, ...values);
  const max = 100;
  const x = (i) => 2 + (i / Math.max(values.length - 1, 1)) * (w - 6);
  const y = (v) => 3 + (1 - (v - min) / (max - min || 1)) * (hgt - 6);
  ctx.strokeStyle = t.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, y(70) + 0.5);
  ctx.lineTo(w, y(70) + 0.5);
  ctx.stroke();
  ctx.strokeStyle = t.s1;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.stroke();
  const lx = x(values.length - 1);
  const ly = y(values[values.length - 1]);
  ctx.fillStyle = t[tone] || t.s1;
  ctx.strokeStyle = t.surface;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(lx, ly, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}
