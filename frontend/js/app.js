// Centro de Mantenimiento Predictivo: enrutado, sondeo de la API y vistas.
import {
  barChart, distributionChart, forecastChart, healthChart, refreshTheme, sensorChart, sparkline,
} from "./charts.js";
import {
  EVENT_KIND, SENSORS, SENSOR_LABEL, SENSOR_SHORT, SENSOR_STATE_ICON, SEVERITY, STATUS, STATUS_ORDER,
  TYPE_LABEL, fmtDateTime, fmtRul, h, icon, num, pct, rulTone, severityIcon, statusBadge,
} from "./format.js";

const POLL_MS = 3000;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  config: null,
  fleet: null,
  events: [],
  modelInfo: null,
  route: { name: "overview", id: null },
  filters: { line: "", type: "", status: new Set(), q: "", view: "cards" },
  sensorView: "charts",
  lastMachine: null,
  analyticsLoaded: false,
};

// ------------------------------------------------------------------- API
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail || detail;
    } catch { /* respuesta sin JSON */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function setConnection(ok, label) {
  const el = $("#conn");
  el.classList.toggle("ok", ok);
  el.classList.toggle("down", !ok);
  $("#conn-label").textContent = label;
}

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

// ---------------------------------------------------------------- routing
function parseRoute() {
  const [, name = "overview", id = null] = location.hash.replace(/^#/, "").split("/");
  const valid = ["overview", "machine", "alarms", "diagnostics", "analytics"];
  return { name: valid.includes(name) ? name : "overview", id: id ? decodeURIComponent(id) : null };
}

function onRoute() {
  state.route = parseRoute();
  if (state.route.name === "machine" && !state.route.id) {
    const pick = state.lastMachine || worstMachine()?.id;
    if (pick) { location.replace(`#/machine/${encodeURIComponent(pick)}`); return; }
  }
  for (const v of $$(".view")) v.hidden = v.id !== `view-${state.route.name}`;
  for (const a of $$(".sidenav a")) a.classList.toggle("active", a.dataset.route === state.route.name);
  if (state.route.name === "machine") state.lastMachine = state.route.id;
  window.scrollTo({ top: 0 });
  render();
  if (state.route.name === "machine") loadMachine();
  if (state.route.name === "analytics" && !state.analyticsLoaded) loadAnalytics();
}

function worstMachine() {
  const ms = state.fleet?.machines || [];
  return [...ms].sort((a, b) => a.health - b.health)[0];
}

// ---------------------------------------------------------------- polling
async function poll() {
  try {
    const [fleet, events] = await Promise.all([api("/api/fleet"), api("/api/events?limit=300")]);
    state.fleet = fleet;
    state.events = events;
    setConnection(true, "En línea");
    render();
    if (state.route.name === "machine") await loadMachine();
  } catch (err) {
    setConnection(false, err.status === 503 ? "Simulación detenida" : "Sin conexión");
    $("#content").classList.add("stale");
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

function render() {
  if (!state.fleet) return;
  $("#content").classList.remove("stale");
  renderHeader();
  if (state.route.name === "overview") renderOverview();
  if (state.route.name === "alarms") renderAlarms();
  if (state.route.name === "machine") renderMachineSelect();
}

function renderHeader() {
  const f = state.fleet;
  $("#sim-clock").textContent = fmtDateTime(f.sim_time);
  $("#sim-rate").textContent = `· 1 ciclo = ${f.minutes_per_tick} min`;
  const n = f.kpis.active_alarms;
  const badge = $("#nav-alarms");
  badge.hidden = n === 0;
  badge.textContent = n > 99 ? "99+" : n;
}

// =============================================================== OVERVIEW
function kpiTile({ label, value, unit = "", foot = "", tone = "", iconId = "", href = "" }) {
  const tag = href ? "a" : "div";
  return `<${tag} class="kpi${tone ? ` is-${tone}` : ""}"${href ? ` href="${href}"` : ""}>
    <span class="kpi-label">${iconId ? icon(iconId, `ic-${tone || "good"}`) : ""}${h(label)}</span>
    <span class="kpi-value">${value}${unit ? `<small>${unit}</small>` : ""}</span>
    ${foot ? `<span class="kpi-foot">${foot}</span>` : ""}
  </${tag}>`;
}

function renderKpis() {
  const k = state.fleet.kpis;
  const c = k.status_counts;
  const next = k.next_failure;
  const s = (n) => (n === 1 ? "" : "s");
  $("#kpis").innerHTML = [
    kpiTile({ label: "Disponibilidad", value: num(k.availability_pct, 1), unit: "%", foot: `${k.total - c.FALLA} de ${k.total} en servicio` }),
    kpiTile({ label: "Salud media de flota", value: num(k.avg_health, 0), unit: "/100", foot: "Índice por condición" }),
    kpiTile({ label: "Operativas", value: c.OPERATIVO, iconId: "i-ok", foot: "Dentro de límites" }),
    kpiTile({ label: "En alerta", value: c.ALERTA, iconId: "i-warning", tone: c.ALERTA ? "warning" : "", foot: "Inspección recomendada" }),
    kpiTile({ label: "Críticas", value: c.CRITICO, iconId: "i-serious", tone: c.CRITICO ? "serious" : "", foot: "Intervención prioritaria" }),
    kpiTile({ label: "En falla", value: c.FALLA, iconId: "i-critical", tone: c.FALLA ? "critical" : "", foot: "Paradas no planificadas" }),
    kpiTile({
      label: "Próxima falla estimada",
      value: next ? fmtRul(next.rul_hours) : "—",
      tone: next && next.rul_hours <= 24 ? "critical" : "",
      foot: next ? `${h(next.id)} · ${h(next.name)}` : "Sin fallas previstas",
      href: next ? `#/machine/${encodeURIComponent(next.id)}` : "",
    }),
    kpiTile({
      label: "Fallas previstas 24 h",
      value: k.failures_next_24h,
      tone: k.failures_next_24h ? "serious" : "",
      foot: `${k.active_alarms} alarma${s(k.active_alarms)} sin reconocer`,
      href: "#/alarms",
    }),
  ].join("");
}

function setupFilters() {
  const ms = state.fleet.machines;
  const lines = [...new Set(ms.map((m) => m.line))];
  $("#f-line").innerHTML = `<option value="">Todas</option>${lines.map((l) => `<option>${h(l)}</option>`).join("")}`;
  const types = [...new Set(ms.map((m) => m.machine_type))];
  $("#f-type").innerHTML = `<option value="">Todos</option>${types.map((t) => `<option value="${t}">${TYPE_LABEL[t]}</option>`).join("")}`;
  $("#f-line").addEventListener("change", (e) => { state.filters.line = e.target.value; renderOverview(); });
  $("#f-type").addEventListener("change", (e) => { state.filters.type = e.target.value; renderOverview(); });
  $("#f-search").addEventListener("input", (e) => { state.filters.q = e.target.value.trim().toLowerCase(); renderOverview(); });
  $("#f-status").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const st = chip.dataset.status;
    state.filters.status.has(st) ? state.filters.status.delete(st) : state.filters.status.add(st);
    renderOverview();
  });
  for (const b of $$("#view-overview .seg button")) {
    b.addEventListener("click", () => {
      state.filters.view = b.dataset.view;
      $$("#view-overview .seg button").forEach((x) => x.classList.toggle("active", x === b));
      renderOverview();
    });
  }
}

function filteredMachines() {
  const f = state.filters;
  return state.fleet.machines.filter((m) =>
    (!f.line || m.line === f.line) &&
    (!f.type || m.machine_type === f.type) &&
    (!f.status.size || f.status.has(m.status)) &&
    (!f.q || `${m.id} ${m.name}`.toLowerCase().includes(f.q)));
}

function renderStatusChips() {
  const c = state.fleet.kpis.status_counts;
  $("#f-status").innerHTML = ["OPERATIVO", "ALERTA", "CRITICO", "FALLA"].map((st) => `
    <button type="button" class="chip" data-status="${st}" aria-pressed="${state.filters.status.has(st)}">
      ${icon(STATUS[st].icon, `ic-${STATUS[st].tone}`)}${STATUS[st].label} <span class="count">${c[st]}</span>
    </button>`).join("");
}

function sensorMini(m, s) {
  const st = m.sensor_states[s];
  const unit = state.config.sensor_units[s];
  return `<div class="sensor-mini ${st !== "normal" ? st : ""}" title="${SENSOR_LABEL[s]}: ${num(m.sensors[s], 2)} ${unit}">
    <div class="k">${st !== "normal" ? icon(SENSOR_STATE_ICON[st], `ic-${st}`) : ""}${SENSOR_SHORT[s]}</div>
    <div class="v">${num(m.sensors[s], s === "Power_Usage" ? 1 : 0)}<span class="muted small"> ${unit}</span></div>
  </div>`;
}

function machineCard(m) {
  const tone = rulTone(m.rul_hours, m.running);
  return `<button type="button" class="mcard s-${m.status}" data-id="${h(m.id)}" aria-label="${h(m.id)}, ${STATUS[m.status].label}, salud ${num(m.health, 0)}">
    <div class="mcard-top">
      <div><div class="mcard-id">${h(m.id)}</div><div class="mcard-name">${h(m.name)}</div></div>
      ${statusBadge(m.status)}
    </div>
    <div class="mcard-mid">
      <div><div class="health-num">${num(m.health, 0)}<small>/100</small></div><div class="health-lbl">Índice de salud</div></div>
      <canvas class="spark" data-spark="${h(m.id)}" aria-hidden="true"></canvas>
    </div>
    <div class="hbar s-${m.status}"><span style="width:${Math.max(0, Math.min(100, m.health))}%"></span></div>
    <div class="mcard-rul">
      <span class="muted">Vida útil restante</span>
      <strong class="${tone ? `ic-${tone}` : ""}">${tone ? icon(tone === "critical" ? "i-critical" : tone === "serious" ? "i-serious" : "i-warning", `ic-${tone}`).replace("<svg", '<svg width="12" height="12" style="vertical-align:-1px;margin-right:3px"') : ""}${fmtRul(m.rul_hours, m.running)}</strong>
    </div>
    <div class="sensors-mini">${SENSORS.map((s) => sensorMini(m, s)).join("")}</div>
  </button>`;
}

function machineTable(ms) {
  const sorted = [...ms].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.health - b.health);
  const u = state.config.sensor_units;
  return `<div class="card flush"><div class="table-wrap"><table>
    <thead><tr><th>Máquina</th><th>Línea</th><th>Estado</th><th class="num">Salud</th><th class="num">Vida útil rest.</th><th>Falla estimada</th>
      ${SENSORS.map((s) => `<th class="num">${SENSOR_SHORT[s]} (${u[s]})</th>`).join("")}<th class="num" title="Probabilidad del modelo de ML">Prob. ML</th></tr></thead>
    <tbody>${sorted.map((m) => `<tr class="clickable" data-id="${h(m.id)}">
      <td><strong>${h(m.id)}</strong> <span class="muted">${h(m.name)}</span></td>
      <td>${h(m.line)}</td><td>${statusBadge(m.status)}</td>
      <td class="num">${num(m.health, 0)}</td>
      <td class="num">${fmtRul(m.rul_hours, m.running)}</td>
      <td>${m.predicted_failure_at ? fmtDateTime(m.predicted_failure_at) : "—"}</td>
      ${SENSORS.map((s) => `<td class="num">${m.sensor_states[s] !== "normal" ? icon(SENSOR_STATE_ICON[m.sensor_states[s]], `ic-${m.sensor_states[s]}`).replace("<svg", '<svg width="11" height="11" style="margin-right:3px"') : ""}${num(m.sensors[s], 1)}</td>`).join("")}
      <td class="num">${m.ml_probability == null ? "—" : pct(m.ml_probability)}</td>
    </tr>`).join("")}</tbody></table></div></div>`;
}

function renderOverview() {
  renderKpis();
  renderStatusChips();
  const ms = filteredMachines();
  const fleetEl = $("#fleet");
  if (!ms.length) {
    fleetEl.innerHTML = `<div class="card"><p class="empty">Ninguna máquina coincide con los filtros.</p></div>`;
  } else if (state.filters.view === "table") {
    fleetEl.innerHTML = machineTable(ms);
  } else {
    const byLine = new Map();
    for (const m of ms) { if (!byLine.has(m.line)) byLine.set(m.line, []); byLine.get(m.line).push(m); }
    fleetEl.innerHTML = [...byLine].map(([line, list]) => {
      const issues = list.filter((m) => m.status !== "OPERATIVO").length;
      return `<section class="line-group">
        <div class="line-head"><h2>${h(line)}</h2><span class="muted small">${list.length} máquinas${issues ? ` · ${issues} con incidencias` : ""}</span></div>
        <div class="machine-grid">${list.map(machineCard).join("")}</div>
      </section>`;
    }).join("");
    for (const c of $$("canvas[data-spark]", fleetEl)) {
      const m = ms.find((x) => x.id === c.dataset.spark);
      sparkline(c, m.health_trend, STATUS[m.status].tone);
    }
  }
  renderForecast();
  renderSideAlarms();
}

function renderForecast() {
  const rows = state.fleet.machines
    .filter((m) => m.running && m.rul_hours != null && m.rul_hours <= 72)
    .sort((a, b) => a.rul_hours - b.rul_hours);
  $("#forecast-empty").hidden = rows.length > 0;
  const box = $("#forecast-box");
  box.hidden = rows.length === 0;
  $("#forecast-legend").innerHTML = rows.length
    ? ["CRITICO", "ALERTA", "OPERATIVO"].map((st) => `<span>${icon(STATUS[st].icon, `ic-${STATUS[st].tone}`).replace("<svg", '<svg width="11" height="11" style="vertical-align:-1px;margin-right:4px"')}${STATUS[st].label}</span>`).join("")
      + `<span class="muted">· Pulse una barra para ver la máquina</span>`
    : "";
  if (rows.length) {
    box.style.height = `${48 + rows.length * 28}px`;
    forecastChart($("#forecast-chart"), rows);
  }
}

function eventItem(e, { showMachine = true, ack = false } = {}) {
  return `<li>
    ${severityIcon(e.severity)}
    <div>
      <div class="ev-title">${showMachine ? `<a class="link" href="#/machine/${encodeURIComponent(e.machine_id)}">${h(e.machine_id)}</a> · ` : ""}${EVENT_KIND[e.kind]}</div>
      <div class="ev-msg">${h(e.message)}</div>
    </div>
    <div style="text-align:right">
      <div class="ev-time">${fmtDateTime(e.timestamp)}</div>
      ${ack && !e.acknowledged && e.kind !== "maintenance" ? `<button class="btn sm" data-ack="${e.id}" style="margin-top:4px">Reconocer</button>` : ""}
    </div>
  </li>`;
}

function renderSideAlarms() {
  const active = state.events.filter((e) => !e.acknowledged && e.kind !== "maintenance").slice(0, 6);
  $("#side-alarms").innerHTML = active.length
    ? active.map((e) => eventItem(e, { ack: true })).join("")
    : `<li class="empty" style="display:block">Sin alarmas activas.</li>`;
}

// ================================================================ MACHINE
function renderMachineSelect() {
  const sel = $("#m-select");
  const ids = state.fleet.machines.map((m) => m.id).join();
  if (sel.dataset.ids !== ids) {
    sel.innerHTML = state.fleet.machines.map((m) => `<option value="${h(m.id)}">${h(m.id)} · ${h(m.name)}</option>`).join("");
    sel.dataset.ids = ids;
  }
  if (state.route.id) sel.value = state.route.id;
}

let machineReq = 0;
async function loadMachine() {
  const id = state.route.id;
  if (!id) return;
  const req = ++machineReq;
  try {
    const d = await api(`/api/fleet/${encodeURIComponent(id)}`);
    if (req !== machineReq || state.route.id !== id) return;
    renderMachine(d);
  } catch (err) {
    if (err.status === 404) {
      $("#m-title").textContent = "Máquina no encontrada";
      $("#m-sub").textContent = id;
    }
  }
}

function renderMachine(d) {
  const cfg = state.config;
  $("#m-crumb").textContent = d.id;
  $("#m-title").innerHTML = `${h(d.id)} · ${h(d.name)} ${statusBadge(d.status, true)}`;
  $("#m-sub").textContent = `${d.line} · ${d.type_label}`;
  $("#m-maint").dataset.id = d.id;

  const tone = rulTone(d.rul_hours, d.running);
  const slope = d.health_slope_per_hour;
  const mlNote = state.modelInfo && !state.modelInfo.has_predictive_signal ? "Modelo sin señal predictiva validada" : "Clasificador entrenado (ETL)";
  $("#m-kpis").innerHTML = [
    kpiTile({ label: "Índice de salud", value: num(d.health, 0), unit: "/100", tone: { ALERTA: "warning", CRITICO: "serious", FALLA: "critical" }[d.status] || "", foot: STATUS[d.status].label }),
    kpiTile({ label: "Vida útil restante", value: fmtRul(d.rul_hours, d.running), tone, foot: d.predicted_failure_at ? `Falla estimada: ${fmtDateTime(d.predicted_failure_at)}` : d.running ? "Sin tendencia de degradación" : "Máquina detenida por falla" }),
    kpiTile({ label: "Tendencia de salud", value: `${slope > 0 ? "+" : ""}${num(slope, 2)}`, unit: "pts/h", foot: slope < -0.05 ? "Degradándose" : "Estable" }),
    kpiTile({ label: "Prob. de falla (ML)", value: d.ml_probability == null ? "—" : pct(d.ml_probability), foot: mlNote }),
    kpiTile({ label: "Último mantenimiento", value: d.last_maintenance ? fmtDateTime(d.last_maintenance) : "—", foot: d.last_maintenance ? "Registrado en el sistema" : "Sin registro en esta sesión" }),
  ].join("");

  // Salud + proyección
  const t = getComputedStyle(document.documentElement);
  const v = (n) => t.getPropertyValue(n).trim();
  $("#health-legend").innerHTML = `
    <span><span class="ln" style="border-color:${v("--series-1")}"></span>Índice de salud</span>
    <span><span class="ln dash" style="border-color:${v("--projection")}"></span>Proyección</span>
    <span><span class="ln dash" style="border-color:${v("--warning")}"></span>Alerta</span>
    <span><span class="ln dash" style="border-color:${v("--serious")}"></span>Crítico</span>
    <span><span class="ln dash" style="border-color:${v("--critical")}"></span>Falla funcional</span>`;
  healthChart($("#health-chart"), d, cfg);
  $("#health-note").textContent = d.running
    ? (d.rul_hours != null
      ? `La proyección extrapola la tendencia de las últimas 4 h hasta el umbral de falla funcional (${cfg.health_thresholds.failure}/100). Se muestra un horizonte máximo de 72 h.`
      : "La salud no muestra una tendencia descendente significativa; no se proyecta falla.")
    : "Máquina detenida por falla funcional. La reparación correctiva restablece el servicio automáticamente o puede registrarse una intervención.";

  // Sensores
  const grid = $("#sensor-charts");
  if (!grid.children.length) {
    grid.innerHTML = SENSORS.map((s) => `<div class="sensor-cell">
      <div class="sensor-cell-head"><h3>${SENSOR_LABEL[s]}</h3><span class="val" data-val="${s}"></span></div>
      <div class="chart-box"><canvas data-sensor="${s}" aria-label="Evolución de ${SENSOR_LABEL[s]}"></canvas></div>
    </div>`).join("");
  }
  for (const s of SENSORS) {
    const st = d.sensor_states[s];
    $(`[data-val="${s}"]`, grid).innerHTML = `${st !== "normal" ? icon(SENSOR_STATE_ICON[st], `ic-${st}`).replace("<svg", '<svg width="14" height="14" style="margin-right:4px;vertical-align:-1px"') : ""}${num(d.sensors[s], 2)}<small> ${cfg.sensor_units[s]}</small>`;
    if (state.sensorView === "charts") sensorChart($(`canvas[data-sensor="${s}"]`, grid), d.history, s, cfg.sensor_limits[s], cfg.sensor_units[s]);
  }
  if (state.sensorView === "table") {
    const rows = d.history.slice(-36).reverse();
    $("#sensor-table").innerHTML = `<table><thead><tr><th>Hora</th>${SENSORS.map((s) => `<th class="num">${SENSOR_LABEL[s]} (${cfg.sensor_units[s]})</th>`).join("")}<th class="num">Salud</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${fmtDateTime(r.timestamp)}</td>${SENSORS.map((s) => `<td class="num">${num(r[s], 2)}</td>`).join("")}<td class="num">${num(r.health, 1)}</td></tr>`).join("")}</tbody></table>`;
  }

  $("#m-events").innerHTML = d.events.length
    ? d.events.slice(0, 15).map((e) => eventItem(e, { showMachine: false, ack: true })).join("")
    : `<li class="empty" style="display:block">Sin eventos registrados para esta máquina.</li>`;
}

function setupMachineView() {
  $("#m-select").addEventListener("change", (e) => { location.hash = `#/machine/${encodeURIComponent(e.target.value)}`; });
  for (const b of $$('[data-sview]')) {
    b.addEventListener("click", () => {
      state.sensorView = b.dataset.sview;
      $$("[data-sview]").forEach((x) => x.classList.toggle("active", x === b));
      $("#sensor-charts").hidden = state.sensorView !== "charts";
      $("#sensor-table").hidden = state.sensorView !== "table";
      loadMachine();
    });
  }
  const dialog = $("#maint-dialog");
  $("#m-maint").addEventListener("click", () => {
    const m = state.fleet?.machines.find((x) => x.id === $("#m-maint").dataset.id);
    if (!m) return;
    $("#maint-machine").textContent = `${m.id} · ${m.name} — estado actual: ${STATUS[m.status].label}, salud ${num(m.health, 0)}/100`;
    $("#maint-form").reset();
    dialog.showModal();
  });
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "confirm") return;
    const id = $("#m-maint").dataset.id;
    const fd = new FormData($("#maint-form"));
    try {
      await api(`/api/fleet/${encodeURIComponent(id)}/maintenance`, {
        method: "POST",
        body: { technician: fd.get("technician") || null, notes: fd.get("notes") || null },
      });
      toast(`Mantenimiento registrado en ${id}. Salud restablecida.`);
      await refreshNow();
    } catch (err) {
      toast(`No se pudo registrar: ${err.message}`);
    }
  });
}

async function refreshNow() {
  const [fleet, events] = await Promise.all([api("/api/fleet"), api("/api/events?limit=300")]);
  state.fleet = fleet;
  state.events = events;
  render();
  if (state.route.name === "machine") await loadMachine();
}

// ================================================================= ALARMS
function visibleEvents() {
  const sev = $("#a-sev").value;
  const kind = $("#a-kind").value;
  const active = $("#a-active").checked;
  return state.events.filter((e) =>
    (!sev || e.severity === sev) && (!kind || e.kind === kind) && (!active || (!e.acknowledged && e.kind !== "maintenance")));
}

function renderAlarms() {
  const rows = visibleEvents();
  $("#alarms-table").innerHTML = rows.length ? `<table>
    <thead><tr><th>Severidad</th><th>Hora</th><th>Máquina</th><th>Línea</th><th>Tipo</th><th>Descripción</th><th>Estado</th></tr></thead>
    <tbody>${rows.map((e) => `<tr class="${e.acknowledged ? "acked" : ""}">
      <td><span class="status">${severityIcon(e.severity)}${SEVERITY[e.severity].label}</span></td>
      <td class="num">${fmtDateTime(e.timestamp)}</td>
      <td><a class="link" href="#/machine/${encodeURIComponent(e.machine_id)}"><strong>${h(e.machine_id)}</strong></a></td>
      <td>${h(e.line)}</td>
      <td>${EVENT_KIND[e.kind]}</td>
      <td class="wrap">${h(e.message)}</td>
      <td>${e.kind === "maintenance" ? '<span class="muted">Registro</span>' : e.acknowledged ? '<span class="muted">Reconocida</span>' : `<button class="btn sm" data-ack="${e.id}">Reconocer</button>`}</td>
    </tr>`).join("")}</tbody></table>`
    : `<p class="empty" style="padding:16px">No hay eventos que coincidan con los filtros. Los eventos aparecen a medida que la flota evoluciona.</p>`;
}

function setupAlarms() {
  for (const id of ["#a-sev", "#a-kind", "#a-active"]) $(id).addEventListener("change", renderAlarms);
  $("#ack-all").addEventListener("click", async () => {
    const pending = visibleEvents().filter((e) => !e.acknowledged && e.kind !== "maintenance");
    await Promise.all(pending.map((e) => api(`/api/events/${e.id}/ack`, { method: "POST" })));
    toast(`${pending.length} alarma(s) reconocida(s).`);
    refreshNow();
  });
  // Reconocimiento individual (delegado: tabla, panel lateral y detalle)
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-ack]");
    if (!btn) return;
    e.stopPropagation();
    btn.disabled = true;
    try {
      await api(`/api/events/${btn.dataset.ack}/ack`, { method: "POST" });
      await refreshNow();
    } catch (err) {
      toast(`Error: ${err.message}`);
      btn.disabled = false;
    }
  });
}

// ============================================================ DIAGNOSTICS
function setupDiagnostics() {
  const cfg = state.config;
  const ranges = { Temperature: [30, 120, 0.5], Vibration: [30, 80, 0.1], Power_Usage: [5, 16, 0.05], Humidity: [0, 100, 0.5] };
  $("#diag-fields").innerHTML = SENSORS.map((s) => {
    const [min, max, step] = ranges[s];
    const l = cfg.sensor_limits[s];
    return `<label class="field"><span>${SENSOR_LABEL[s]} (${cfg.sensor_units[s]}) · alarma ${l.alarm}, crítico ${l.critical}</span>
      <div class="range-row">
        <input type="range" min="${min}" max="${max}" step="${step}" value="${l.nominal}" data-range="${s}" aria-label="${SENSOR_LABEL[s]}">
        <input type="number" name="${s}" min="${min}" max="${max}" step="${step}" value="${l.nominal}" required>
      </div>
    </label>`;
  }).join("");
  for (const r of $$("[data-range]")) {
    const n = $(`input[name="${r.dataset.range}"]`);
    r.addEventListener("input", () => { n.value = r.value; });
    n.addEventListener("input", () => { r.value = n.value; });
  }
  $("#diag-reset").addEventListener("click", () => {
    for (const s of SENSORS) {
      const v = cfg.sensor_limits[s].nominal;
      $(`input[name="${s}"]`).value = v;
      $(`[data-range="${s}"]`).value = v;
    }
  });
  $("#diag-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { Machine_Type: fd.get("Machine_Type") };
    for (const s of SENSORS) body[s] = Number(fd.get(s));
    $("#diag-error").hidden = true;
    try {
      renderDiagnosis(await api("/api/diagnose", { method: "POST", body }), body);
    } catch (err) {
      $("#diag-error").textContent = `Lectura no válida: ${err.message}`;
      $("#diag-error").hidden = false;
    }
  });
}

function renderDiagnosis(r, reading) {
  const cfg = state.config;
  const actions = {
    OPERATIVO: "Operación normal. Mantener el plan de mantenimiento preventivo vigente.",
    ALERTA: "Programar una inspección (análisis de vibraciones y termografía) en las próximas 48 h.",
    CRITICO: "Planificar una intervención prioritaria y reducir la carga de trabajo de la máquina.",
  };
  const ml = r.ml;
  const noSignal = state.modelInfo && !state.modelInfo.has_predictive_signal;
  $("#diag-result").innerHTML = `
    <header class="card-head"><h2>Resultado</h2>${statusBadge(r.status, true)}</header>
    <div class="diag-hero">
      <div><div class="big">${num(r.health, 0)}<span class="muted" style="font-size:18px">/100</span></div><div class="muted small">Índice de salud por condición</div></div>
      <div><div class="big">${ml ? pct(ml.failure_probability) : "—"}</div><div class="muted small">Probabilidad de falla según el modelo ML${ml ? ` · riesgo ${ml.risk_level.toLowerCase()}` : ""}</div></div>
    </div>
    <div class="diag-rows">${SENSORS.map((s) => {
      const st = r.sensor_states[s];
      return `<div class="kpi${st === "critical" ? " is-critical" : st === "warning" ? " is-warning" : ""}">
        <span class="kpi-label">${st !== "normal" ? icon(SENSOR_STATE_ICON[st], `ic-${st}`) : icon("i-ok", "ic-good")}${SENSOR_LABEL[s]}</span>
        <span class="kpi-value" style="font-size:20px">${num(reading[s], 1)}<small>${cfg.sensor_units[s]}</small></span>
        <span class="kpi-foot">${st === "critical" ? "Sobre límite crítico" : st === "warning" ? "Sobre límite de alarma" : "Dentro de límites"}</span>
      </div>`;
    }).join("")}</div>
    <div class="callout"><strong>Acción recomendada:</strong> ${actions[r.status]}</div>
    ${noSignal ? `<div class="callout warn" style="margin-top:10px"><strong>Nota sobre el modelo ML:</strong> con el dataset actual el modelo no supera al azar en validación (ver <a class="link" href="#/analytics">Modelo y datos</a>). Use el índice de salud por condición como criterio principal.</div>` : ""}`;
}

// ============================================================== ANALYTICS
async function loadAnalytics() {
  const el = $("#analytics");
  el.innerHTML = `<div class="card"><p class="empty">Cargando…</p></div>`;
  try {
    const a = await api("/api/analytics");
    state.analyticsLoaded = true;
    renderAnalytics(a);
  } catch (err) {
    el.innerHTML = `<div class="card"><p class="error">No se pudo cargar la analítica: ${h(err.message)}</p></div>`;
  }
}

const MODEL_LABEL = { logistic_regression: "Regresión logística", random_forest: "Random Forest", gradient_boosting: "Gradient Boosting" };

function renderAnalytics(a) {
  const el = $("#analytics");
  const tr = a.training;
  const ds = a.dataset;
  const q = a.quality;
  if (!tr || !ds) {
    el.innerHTML = `<div class="card"><p class="empty">No hay resultados todavía. Ejecute <code>python run_pipeline.py</code> para generar el ETL y el modelo.</p></div>`;
    return;
  }
  const tm = tr.test_metrics;
  const cm = tm.confusion_matrix;
  const cmMax = Math.max(...cm.flat());
  const cell = (v) => {
    const a2 = 0.12 + 0.6 * (v / (cmMax || 1));
    return `<td class="cell" style="background:color-mix(in srgb, var(--series-1) ${Math.round(a2 * 100)}%, var(--surface-1));color:${a2 > 0.45 ? "#fff" : "var(--text-primary)"}">${v}</td>`;
  };
  const models = Object.keys(tr.cv_results);
  el.innerHTML = `
    ${tr.has_predictive_signal ? "" : `<div class="callout warn" style="margin-bottom:16px">
      <strong>El dataset actual no contiene señal predictiva.</strong> El mejor ROC-AUC en validación cruzada
      (${num(tr.cv_results[tr.best_model].roc_auc_mean, 3)}) es equivalente al de un clasificador aleatorio
      (${num(tr.baseline_cv_roc_auc, 3)}): las distribuciones de los sensores son iguales con y sin falla (ver gráficas inferiores).
      Por ello el dashboard usa como criterio principal el <strong>índice de salud por condición</strong> y la tendencia de degradación,
      y muestra la probabilidad ML como referencia. Con datos etiquetados reales el pipeline reentrena el modelo sin cambios de código.
    </div>`}
    <div class="kpis" style="margin-bottom:16px">
      ${kpiTile({ label: "Modelo seleccionado", value: `<span style="font-size:18px">${MODEL_LABEL[tr.best_model] || tr.best_model}</span>`, foot: `Entrenado ${fmtDateTime(tr.trained_at)}` })}
      ${kpiTile({ label: "ROC-AUC (test)", value: num(tm.roc_auc, 3), foot: `Baseline aleatorio ${num(tr.baseline_cv_roc_auc, 3)}`, tone: tr.has_predictive_signal ? "" : "warning", iconId: tr.has_predictive_signal ? "" : "i-warning" })}
      ${kpiTile({ label: "Recall (test)", value: pct(tm.recall), foot: "Fallas detectadas" })}
      ${kpiTile({ label: "Precisión (test)", value: pct(tm.precision), foot: "Alertas correctas" })}
      ${kpiTile({ label: "Umbral de decisión", value: num(tr.decision_threshold, 2), foot: `${tr.n_train} train · ${tr.n_test} test` })}
    </div>
    <div class="an-grid">
      <section class="card">
        <header class="card-head"><h2>Comparación de modelos · ROC-AUC en validación cruzada</h2></header>
        <div class="chart-box short"><canvas id="an-cv"></canvas></div>
        <p class="note small muted">5 folds estratificados. La línea discontinua marca el rendimiento de un clasificador aleatorio.</p>
      </section>
      <section class="card">
        <header class="card-head"><h2>Matriz de confusión · conjunto de test</h2></header>
        <div class="table-wrap"><table class="cm">
          <tr><th></th><th>Predicho: sin falla</th><th>Predicho: falla</th></tr>
          <tr><th>Real: sin falla</th>${cell(cm[0][0])}${cell(cm[0][1])}</tr>
          <tr><th>Real: falla</th>${cell(cm[1][0])}${cell(cm[1][1])}</tr>
        </table></div>
        <dl class="dl" style="margin-top:12px">
          <dt>Exactitud</dt><dd>${pct(tm.accuracy, 1)}</dd>
          <dt>F1</dt><dd>${num(tm.f1, 3)}</dd>
          <dt>Modelos evaluados</dt><dd>${models.map((m) => MODEL_LABEL[m] || m).join(", ")}</dd>
        </dl>
      </section>
      <section class="card">
        <header class="card-head"><h2>Tasa de falla por tipo de máquina</h2><span class="muted small">${ds.rows} registros · media ${pct(ds.failure_rate, 1)}</span></header>
        <div class="chart-box short"><canvas id="an-type"></canvas></div>
      </section>
      <section class="card">
        <header class="card-head"><h2>Calidad de datos · pipeline ETL</h2><span class="muted small">${q ? fmtDateTime(q.loaded_at) : ""}</span></header>
        ${q ? `<dl class="dl">
          <dt>Filas de entrada</dt><dd>${q.rows_in}</dd>
          <dt>Filas cargadas</dt><dd>${q.rows_out}</dd>
          <dt>Duplicados eliminados</dt><dd>${q.duplicates_removed}</dd>
          <dt>Objetivo inválido eliminado</dt><dd>${q.invalid_target_removed}</dd>
          <dt>Tipo de máquina desconocido</dt><dd>${q.unknown_machine_type_removed}</dd>
          <dt>Lecturas fuera de rango</dt><dd>${Object.values(q.out_of_range_set_null).reduce((x, y) => x + y, 0)}</dd>
          <dt>Valores imputados</dt><dd>${Object.values(q.nulls_imputed).reduce((x, y) => x + y, 0)}</dd>
          <dt>Outliers recortados (IQR×3)</dt><dd>${Object.values(q.outliers_clipped).reduce((x, y) => x + y, 0)}</dd>
        </dl>` : `<p class="empty">Sin reporte de calidad.</p>`}
      </section>
      <section class="card span-2">
        <header class="card-head">
          <h2>Distribución de cada sensor por clase</h2>
          <div class="legend">
            <span><span class="ln" style="border-color:var(--series-1)"></span>Sin falla</span>
            <span><span class="ln" style="border-color:var(--series-2)"></span>Con falla</span>
          </div>
        </header>
        <p class="small muted" style="margin-bottom:10px">Porcentaje de registros de cada clase en cada intervalo. Si las curvas se superponen, el sensor no discrimina entre máquinas que fallan y que no.</p>
        <div class="sensor-grid">${SENSORS.map((s) => `<div class="sensor-cell"><div class="sensor-cell-head"><h3>${SENSOR_LABEL[s]} (${state.config.sensor_units[s]})</h3>
          <span class="muted small">media ${num(ds.class_means[0][s], 1)} vs ${num(ds.class_means[1][s], 1)}</span></div>
          <div class="chart-box"><canvas data-dist="${s}"></canvas></div></div>`).join("")}</div>
      </section>
    </div>`;

  barChart($("#an-cv"), {
    labels: models.map((m) => MODEL_LABEL[m] || m),
    values: models.map((m) => tr.cv_results[m].roc_auc_mean),
    max: 1,
    format: (v) => num(v, 2),
    reference: { value: tr.baseline_cv_roc_auc, label: `Aleatorio ${num(tr.baseline_cv_roc_auc, 2)}` },
  });
  const types = ds.by_machine_type;
  barChart($("#an-type"), {
    labels: types.map((r) => `${TYPE_LABEL[r.machine_type] || r.machine_type} (n=${r.count})`),
    values: types.map((r) => r.failure_rate * 100),
    max: Math.max(50, Math.ceil(Math.max(...types.map((r) => r.failure_rate * 100)) / 10) * 10),
    format: (v) => `${num(v, 0)} %`,
  });
  for (const s of SENSORS) distributionChart($(`canvas[data-dist="${s}"]`), ds.distributions[s], state.config.sensor_units[s]);
}

// ================================================================== THEME
function setupTheme() {
  const btn = $("#theme-toggle");
  const current = () => document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const paint = () => { btn.querySelector("use").setAttribute("href", current() === "dark" ? "#i-sun" : "#i-moon"); };
  btn.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("pm-theme", next); } catch { /* almacenamiento no disponible */ }
    paint();
    refreshTheme();
    render();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { paint(); refreshTheme(); render(); });
  paint();
}

// =================================================================== INIT
async function init() {
  setupTheme();
  try {
    state.config = await api("/api/config");
    state.modelInfo = await api("/model/info").catch(() => null);
    const [fleet, events] = await Promise.all([api("/api/fleet"), api("/api/events?limit=300")]);
    state.fleet = fleet;
    state.events = events;
    setConnection(true, "En línea");
  } catch (err) {
    setConnection(false, "Sin conexión");
    $("#content").innerHTML = `<div class="card" style="max-width:640px"><h2>No se puede conectar con la API</h2>
      <p class="muted" style="margin-top:6px">${h(err.message)}. Inicie el servidor con <code>uvicorn src.api.main:app</code> y
      asegúrese de que la simulación de flota esté habilitada (<code>SIMULATION_ENABLED=true</code>).</p></div>`;
    return;
  }
  setupFilters();
  setupMachineView();
  setupAlarms();
  setupDiagnostics();
  $("#fleet").addEventListener("click", (e) => {
    const target = e.target.closest("[data-id]");
    if (target) location.hash = `#/machine/${encodeURIComponent(target.dataset.id)}`;
  });
  window.addEventListener("hashchange", onRoute);
  onRoute();
  setTimeout(poll, POLL_MS);
}

init();
