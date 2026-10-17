// Centro de Mantenimiento Predictivo: enrutado, sondeo de la API y vistas.
import { barChart, refreshTheme, riskChart, sensorChart, sparkline } from "./charts.js";
import {
  COMPONENTS, EVENT_KIND, MODEL_LABEL, RESOLUTION, SENSORS, SENSOR_LABEL, SENSOR_SHORT, SENSOR_STATE_ICON,
  SEVERITY, STATUS, STATUS_ORDER, STATUS_TONE, fmtDateTime, fmtDays, h, icon, num, pct, riskPct, severityIcon,
  statusBadge,
} from "./format.js";

const POLL_MS = 3000;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const fullFmt = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const dateFmt = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric" });
const fmtDate = (iso) => (iso ? dateFmt.format(new Date(iso)) : "—");

const state = {
  config: null,
  fleet: null,
  events: [],
  modelInfo: null,
  route: { name: "overview", id: null },
  filters: { model: "", status: new Set(), q: "", view: "map" },
  sensorView: "charts",
  lastMachine: null,
  analyticsLoaded: false,
  whatIf: { id: null, inputs: null, baseline: null },
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

const smallIcon = (id, tone, size = 11) =>
  icon(id, `ic-${tone}`).replace("<svg", `<svg width="${size}" height="${size}" style="vertical-align:-1px;margin-right:3px"`);

// ---------------------------------------------------------------- routing
function parseRoute() {
  const [, name = "overview", id = null] = location.hash.replace(/^#/, "").split("/");
  const valid = ["overview", "machine", "alarms", "diagnostics", "analytics"];
  return { name: valid.includes(name) ? name : "overview", id: id ? decodeURIComponent(id) : null };
}

function riskiest() {
  return [...(state.fleet?.machines || [])].sort((a, b) => (b.failure_probability || 0) - (a.failure_probability || 0))[0];
}

function onRoute() {
  state.route = parseRoute();
  if (state.route.name === "machine" && !state.route.id) {
    const pick = state.lastMachine || riskiest()?.id;
    if (pick) { location.replace(`#/machine/${encodeURIComponent(pick)}`); return; }
  }
  for (const v of $$(".view")) v.hidden = v.id !== `view-${state.route.name}`;
  for (const a of $$(".sidenav a")) a.classList.toggle("active", a.dataset.route === state.route.name);
  if (state.route.name === "machine") state.lastMachine = state.route.id;
  window.scrollTo({ top: 0 });
  render();
  if (state.route.name === "machine") loadMachine();
  if (state.route.name === "analytics" && !state.analyticsLoaded) loadAnalytics();
  if (state.route.name === "diagnostics" && !state.whatIf.id) loadWhatIf(state.lastMachine || riskiest()?.id);
}

// ---------------------------------------------------------------- polling
async function refresh() {
  const [fleet, events] = await Promise.all([api("/api/fleet"), api("/api/events?limit=600")]);
  state.fleet = fleet;
  state.events = events;
}

async function poll() {
  try {
    await refresh();
    setConnection(true, "En línea");
    render();
    if (state.route.name === "machine") await loadMachine();
  } catch (err) {
    setConnection(false, err.status === 503 ? "Flota no disponible" : "Sin conexión");
    $("#content").classList.add("stale");
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

async function refreshNow() {
  await refresh();
  render();
  if (state.route.name === "machine") await loadMachine();
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
  $("#sim-clock").textContent = fullFmt.format(new Date(f.sim_time));
  $("#replay-progress").style.width = `${Math.max(0, Math.min(100, f.replay.progress_pct))}%`;
  $("#sim-rate").textContent = `Reproducción ${num(f.replay.progress_pct, 0)} % · 1 ciclo = ${f.hours_per_tick} h`;
  $("#replay").title = `Reproducción de la telemetría real del periodo de test (${fmtDateTime(f.replay.start)} – ${fmtDateTime(f.replay.end)}), no visto por el modelo al entrenar.`;
  for (const el of $$("[data-horizon]")) el.textContent = f.horizon_hours;
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
  const hz = state.fleet.horizon_hours;
  $("#kpis").innerHTML = [
    kpiTile({ label: "Disponibilidad", value: num(k.availability_pct, 1), unit: "%", foot: `${k.total - c.FALLA} de ${k.total} en servicio` }),
    kpiTile({ label: "Operativas", value: c.OPERATIVO, iconId: "i-ok", foot: "Riesgo bajo" }),
    kpiTile({ label: "En vigilancia", value: c.ALERTA, iconId: "i-warning", tone: c.ALERTA ? "warning" : "", foot: "Riesgo elevado" }),
    kpiTile({ label: `Falla probable ${hz} h`, value: c.CRITICO, iconId: "i-serious", tone: c.CRITICO ? "serious" : "", foot: "Intervención recomendada" }),
    kpiTile({ label: "En falla", value: c.FALLA, iconId: "i-critical", tone: c.FALLA ? "critical" : "", foot: "Reparación correctiva" }),
    kpiTile({
      label: "Fallas anticipadas",
      value: `${k.replay_anticipated}<small>/${k.replay_failures}</small>`,
      foot: k.replay_failures ? `${pct(k.replay_anticipated_rate)} · antelación mediana ${num(k.replay_median_lead_hours, 0)} h` : "Aún sin fallas en la reproducción",
    }),
    kpiTile({
      label: "Falsas alarmas",
      value: k.replay_false_alarms,
      foot: k.replay_correct_component_rate != null ? `Componente acertado ${pct(k.replay_correct_component_rate)}` : "—",
    }),
    kpiTile({ label: "Alarmas sin reconocer", value: k.active_alarms, tone: k.active_alarms ? "serious" : "", href: "#/alarms", foot: "Ver registro" }),
  ].join("");
}

function setupFilters() {
  const models = [...new Set(state.fleet.machines.map((m) => m.model))].sort();
  $("#f-model").innerHTML = `<option value="">Todos</option>${models.map((m) => `<option value="${m}">${MODEL_LABEL(m)}</option>`).join("")}`;
  $("#f-model").addEventListener("change", (e) => { state.filters.model = e.target.value; renderOverview(); });
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
    (!f.model || m.model === f.model) &&
    (!f.status.size || f.status.has(m.status)) &&
    (!f.q || m.id.toLowerCase().includes(f.q)));
}

const byRisk = (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)
  || (b.failure_probability || 0) - (a.failure_probability || 0);

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
  return `<div class="sensor-mini ${st !== "normal" ? st : ""}" title="${SENSOR_LABEL[s]}: ${num(m.sensors[s], 1)} ${unit}">
    <div class="k">${st !== "normal" ? icon(SENSOR_STATE_ICON[st], `ic-${st}`) : ""}${SENSOR_SHORT[s]}</div>
    <div class="v">${num(m.sensors[s], 0)}${unit ? `<span class="muted small"> ${unit}</span>` : ""}</div>
  </div>`;
}

function mapTile(m) {
  const s = STATUS[m.status];
  return `<button type="button" class="tile s-${m.status}" data-id="${h(m.id)}"
      title="${h(m.id)} · ${MODEL_LABEL(m.model)} · ${s.label} · riesgo ${riskPct(m.failure_probability)}${m.predicted_component ? ` (${m.predicted_component})` : ""}"
      aria-label="${h(m.id)}, ${s.label}, riesgo ${riskPct(m.failure_probability)}">
    <span class="t-id">${m.status !== "OPERATIVO" ? icon(s.icon, `ic-${s.tone}`) : ""}${h(m.id)}</span>
    <span class="t-risk">${m.status === "FALLA" ? "En falla" : riskPct(m.failure_probability)}</span>
  </button>`;
}

function machineCard(m) {
  const tone = STATUS_TONE[m.status];
  const p = m.failure_probability || 0;
  return `<button type="button" class="mcard s-${m.status}" data-id="${h(m.id)}" aria-label="${h(m.id)}, ${STATUS[m.status].label}, riesgo ${riskPct(p)}">
    <div class="mcard-top">
      <div><div class="mcard-id">${h(m.id)}</div><div class="mcard-name">${MODEL_LABEL(m.model)} · ${num(m.age, 0)} años</div></div>
      ${statusBadge(m.status)}
    </div>
    <div class="mcard-mid">
      <div><div class="health-num">${riskPct(p).replace(" %", "")}<small>%</small></div><div class="health-lbl">Riesgo ${state.fleet.horizon_hours} h</div></div>
      <canvas class="spark" data-spark="${h(m.id)}" aria-hidden="true"></canvas>
    </div>
    <div class="hbar s-${m.status}"><span style="width:${Math.max(2, p * 100)}%"></span></div>
    <div class="mcard-rul">
      <span class="muted">${m.status === "FALLA" ? "Última falla" : "Componente probable"}</span>
      <strong class="${tone ? `ic-${tone}` : ""}">${m.status === "FALLA" ? h(m.last_failure?.components.join(", ")) : m.predicted_component || "Ninguno"}</strong>
    </div>
    <div class="sensors-mini">${SENSORS.map((s) => sensorMini(m, s)).join("")}</div>
  </button>`;
}

function machineTable(ms) {
  const u = state.config.sensor_units;
  return `<div class="card flush"><div class="table-wrap"><table>
    <thead><tr><th>Máquina</th><th>Modelo</th><th class="num">Edad</th><th>Estado</th><th class="num">Riesgo ${state.fleet.horizon_hours} h</th><th>Comp. probable</th><th class="num">Errores 24 h</th>
      ${SENSORS.map((s) => `<th class="num">${SENSOR_SHORT[s]}${u[s] ? ` (${u[s]})` : ""}</th>`).join("")}</tr></thead>
    <tbody>${[...ms].sort(byRisk).map((m) => `<tr class="clickable" data-id="${h(m.id)}">
      <td><strong>${h(m.id)}</strong></td><td>${MODEL_LABEL(m.model)}</td><td class="num">${num(m.age, 0)}</td>
      <td>${statusBadge(m.status)}</td>
      <td class="num">${riskPct(m.failure_probability)}</td>
      <td>${m.predicted_component || "—"}</td>
      <td class="num">${m.errors_24h}</td>
      ${SENSORS.map((s) => `<td class="num">${m.sensor_states[s] !== "normal" ? smallIcon(SENSOR_STATE_ICON[m.sensor_states[s]], m.sensor_states[s]) : ""}${num(m.sensors[s], 1)}</td>`).join("")}
    </tr>`).join("")}</tbody></table></div></div>`;
}

function renderOverview() {
  renderKpis();
  renderStatusChips();
  const ms = filteredMachines();
  const el = $("#fleet");
  const threshold = state.fleet.thresholds.decision;
  if (!ms.length) {
    el.innerHTML = `<div class="card"><p class="empty">Ninguna máquina coincide con los filtros.</p></div>`;
  } else if (state.filters.view === "table") {
    el.innerHTML = machineTable(ms);
  } else if (state.filters.view === "cards") {
    const sorted = [...ms].sort(byRisk);
    el.innerHTML = `<div class="machine-grid">${sorted.map(machineCard).join("")}</div>`;
    for (const c of $$("canvas[data-spark]", el)) {
      const m = sorted.find((x) => x.id === c.dataset.spark);
      sparkline(c, m.risk_trend, STATUS[m.status].tone, threshold);
    }
  } else {
    // Mapa: posiciones fijas por ID para que el operador memorice la planta
    el.innerHTML = `<section class="card">
      <header class="card-head"><h2>Mapa de flota</h2><span class="muted small">${ms.length} máquinas · pulse una para ver su detalle</span></header>
      <div class="map-grid">${ms.map(mapTile).join("")}</div>
    </section>`;
  }
  renderRiskList();
  renderSideAlarms();
}

function renderRiskList() {
  const th = state.fleet.thresholds;
  const rows = state.fleet.machines.filter((m) => m.status !== "FALLA" && (m.failure_probability || 0) >= th.alert)
    .sort((a, b) => b.failure_probability - a.failure_probability);
  $("#risk-list").innerHTML = rows.length
    ? rows.slice(0, 8).map((m) => `<li><a href="#/machine/${encodeURIComponent(m.id)}">
        <span class="r-id">${h(m.id)} ${statusBadge(m.status)}</span>
        <span class="r-p">${riskPct(m.failure_probability)}</span>
        <span class="r-sub">${MODEL_LABEL(m.model)} · componente probable <strong>${m.predicted_component || "—"}</strong>${m.alarm_since ? ` · alarma desde ${fmtDateTime(m.alarm_since)}` : ""}</span>
      </a></li>`).join("")
      + (rows.length > 8 ? `<li class="small muted" style="padding:8px 2px">y ${rows.length - 8} más (filtre por estado)</li>` : "")
    : `<li class="empty">Ninguna máquina supera el umbral de vigilancia (${pct(th.alert)}).</li>`;
}

function eventItem(e, { showMachine = true, ack = false } = {}) {
  const res = e.resolution ? RESOLUTION[e.resolution] : null;
  return `<li>
    ${severityIcon(e.severity)}
    <div>
      <div class="ev-title">${showMachine && e.machine_id ? `<a class="link" href="#/machine/${encodeURIComponent(e.machine_id)}">${h(e.machine_id)}</a> · ` : ""}${EVENT_KIND[e.kind] || e.kind}${res ? ` <span class="muted small">· ${res.label}</span>` : ""}</div>
      <div class="ev-msg">${h(e.message)}</div>
    </div>
    <div style="text-align:right">
      <div class="ev-time">${fmtDateTime(e.timestamp)}</div>
      ${ack && !e.acknowledged ? `<button class="btn sm" data-ack="${e.id}" style="margin-top:4px">Reconocer</button>` : ""}
    </div>
  </li>`;
}

function renderSideAlarms() {
  const active = state.events.filter((e) => !e.acknowledged).slice(0, 6);
  $("#side-alarms").innerHTML = active.length
    ? active.map((e) => eventItem(e, { ack: true })).join("")
    : `<li class="empty" style="display:block">Sin alarmas activas.</li>`;
}

// ================================================================ MACHINE
function renderMachineSelect() {
  const sel = $("#m-select");
  const ids = state.fleet.machines.map((m) => m.id).join();
  if (sel.dataset.ids !== ids) {
    sel.innerHTML = state.fleet.machines.map((m) => `<option value="${h(m.id)}">${h(m.id)} · ${MODEL_LABEL(m.model)}</option>`).join("");
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

function legendLine(color, label, dash = false) {
  return `<span><span class="ln${dash ? " dash" : ""}" style="border-color:${color}"></span>${label}</span>`;
}

function renderMachine(d) {
  const cfg = state.config;
  const th = state.fleet.thresholds;
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  $("#m-crumb").textContent = d.id;
  $("#m-title").innerHTML = `${h(d.id)} · ${MODEL_LABEL(d.model)} ${statusBadge(d.status, true)}`;
  $("#m-sub").textContent = `${num(d.age, 0)} años de antigüedad · ${d.last_failure
    ? `última falla: ${d.last_failure.components.join(", ")} el ${fmtDateTime(d.last_failure.timestamp)}`
    : "sin fallas en el periodo reproducido"}`;
  $("#m-maint").dataset.id = d.id;

  const p = d.failure_probability || 0;
  const comps = d.component_probabilities || {};
  const top = COMPONENTS.reduce((a, b) => ((comps[b] || 0) > (comps[a] || 0) ? b : a), COMPONENTS[0]);
  $("#m-kpis").innerHTML = [
    kpiTile({ label: `Riesgo de falla ${state.fleet.horizon_hours} h`, value: riskPct(p), tone: STATUS_TONE[d.status], foot: `Umbral de alarma ${pct(th.decision)}` }),
    kpiTile({ label: "Componente probable", value: d.predicted_component || "—", foot: d.predicted_component ? `Probabilidad ${riskPct(comps[top])}` : "Ningún componente en riesgo" }),
    kpiTile({ label: "Alarma activa", value: d.alarm_since ? fmtDateTime(d.alarm_since) : "—", tone: d.alarm_since ? "serious" : "", foot: d.alarm_since ? "Desde la primera alarma del modelo" : "Sin alarma abierta" }),
    kpiTile({ label: "Errores del controlador", value: d.errors_24h, foot: "Últimas 24 h" }),
    kpiTile({ label: "Estado de sensores", value: SENSORS.filter((s) => d.sensor_states[s] !== "normal").length, unit: "/4", foot: "Fuera de límites" }),
  ].join("");

  $("#sensor-legend").innerHTML = legendLine(v("--baseline"), "Lectura horaria") + legendLine(v("--series-1"), "Media 24 h")
    + legendLine(v("--warning"), "Alarma", true) + legendLine(v("--critical"), "Crítico", true);
  $("#risk-legend").innerHTML = legendLine(v("--series-1"), "Riesgo")
    + legendLine(v("--critical"), "Umbral de alarma", true) + legendLine(v("--warning"), "Vigilancia", true)
    + legendLine(v("--critical"), "Falla real") + legendLine(v("--axis-muted"), "Mantenimiento");
  riskChart($("#risk-chart"), d, th);

  const days = d.days_since_replacement || {};
  $("#m-components").innerHTML = COMPONENTS.map((c) => `
    <div class="comp-row${c === d.predicted_component ? " top" : ""}">
      <div><div class="comp-name">${c}</div><div class="comp-days">${fmtDays(days[c])}</div></div>
      <div class="comp-bar" title="Probabilidad de falla de ${c}: ${riskPct(comps[c])}"><span style="width:${Math.max(1, (comps[c] || 0) * 100)}%"></span></div>
      <div class="comp-val">${riskPct(comps[c])}</div>
    </div>`).join("")
    + `<p class="small muted" style="margin-top:8px">Barra: probabilidad de falla de cada componente en ${state.fleet.horizon_hours} h. Debajo del nombre: tiempo desde su último reemplazo.</p>`;

  const grid = $("#sensor-charts");
  if (!grid.children.length) {
    grid.innerHTML = SENSORS.map((s) => `<div class="sensor-cell">
      <div class="sensor-cell-head"><h3>${SENSOR_LABEL[s]}</h3><span class="val" data-val="${s}"></span></div>
      <div class="chart-box"><canvas data-sensor="${s}" aria-label="Evolución de ${SENSOR_LABEL[s]}"></canvas></div>
    </div>`).join("");
  }
  for (const s of SENSORS) {
    const st = d.sensor_states[s];
    const unit = cfg.sensor_units[s];
    $(`[data-val="${s}"]`, grid).innerHTML = `${st !== "normal" ? smallIcon(SENSOR_STATE_ICON[st], st, 14) : ""}${num(d.sensors[s], 1)}${unit ? `<small> ${unit}</small>` : ""}`;
    if (state.sensorView === "charts" && d.history.length > 1) {
      sensorChart($(`canvas[data-sensor="${s}"]`, grid), d.history, s, cfg.sensor_limits[s], unit, d.failures);
    }
  }
  if (state.sensorView === "table") {
    const rows = d.history.slice(-48).reverse();
    $("#sensor-table").innerHTML = `<table><thead><tr><th>Hora</th>${SENSORS.map((s) => `<th class="num">${SENSOR_LABEL[s]}${cfg.sensor_units[s] ? ` (${cfg.sensor_units[s]})` : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${fmtDateTime(r.timestamp)}</td>${SENSORS.map((s) => `<td class="num">${num(r[s], 2)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  const relevant = d.events.filter((e) => e.kind !== "error").slice(0, 15);
  $("#m-events").innerHTML = relevant.length
    ? relevant.map((e) => eventItem(e, { showMachine: false, ack: true })).join("")
    : `<li class="empty" style="display:block">Sin eventos relevantes para esta máquina en el periodo reproducido.</li>`;
}

function setupMachineView() {
  $("#m-select").addEventListener("change", (e) => { location.hash = `#/machine/${encodeURIComponent(e.target.value)}`; });
  for (const b of $$("[data-sview]")) {
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
    $("#maint-machine").textContent = `${m.id} · ${MODEL_LABEL(m.model)} — ${STATUS[m.status].label}, riesgo ${riskPct(m.failure_probability)}`;
    $("#maint-form").reset();
    if (m.predicted_component) $("#maint-form").component.value = m.predicted_component;
    dialog.showModal();
  });
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "confirm") return;
    const id = $("#m-maint").dataset.id;
    const fd = new FormData($("#maint-form"));
    try {
      await api(`/api/fleet/${encodeURIComponent(id)}/work-orders`, {
        method: "POST",
        body: { technician: fd.get("technician") || null, component: fd.get("component") || null, notes: fd.get("notes") || null },
      });
      toast(`Orden de trabajo registrada en ${id}.`);
      await refreshNow();
    } catch (err) {
      toast(`No se pudo registrar: ${err.message}`);
    }
  });
}

// ================================================================= ALARMS
function visibleEvents() {
  const sev = $("#a-sev").value;
  const kind = $("#a-kind").value;
  const active = $("#a-active").checked;
  return state.events.filter((e) =>
    (!sev || e.severity === sev) && (!kind || e.kind === kind) && (!active || !e.acknowledged));
}

function renderAlarms() {
  const rows = visibleEvents().slice(0, 300);
  $("#alarms-table").innerHTML = rows.length ? `<table>
    <thead><tr><th>Severidad</th><th>Hora</th><th>Máquina</th><th>Tipo</th><th>Descripción</th><th>Resultado</th><th>Estado</th></tr></thead>
    <tbody>${rows.map((e) => {
      const res = e.resolution ? RESOLUTION[e.resolution] : null;
      return `<tr class="${e.acknowledged ? "acked" : ""}">
      <td><span class="status">${severityIcon(e.severity)}${SEVERITY[e.severity].label}</span></td>
      <td class="num">${fmtDateTime(e.timestamp)}</td>
      <td>${e.machine_id ? `<a class="link" href="#/machine/${encodeURIComponent(e.machine_id)}"><strong>${h(e.machine_id)}</strong></a>` : "—"}</td>
      <td>${EVENT_KIND[e.kind] || e.kind}</td>
      <td class="wrap">${h(e.message)}</td>
      <td>${res ? `<span class="status">${smallIcon({ good: "i-ok", warning: "i-warning", serious: "i-serious", critical: "i-critical" }[res.tone], res.tone, 12)}${res.label}</span>` : '<span class="muted">—</span>'}</td>
      <td>${e.acknowledged ? '<span class="muted">Reconocida</span>' : `<button class="btn sm" data-ack="${e.id}">Reconocer</button>`}</td>
    </tr>`;
    }).join("")}</tbody></table>`
    : `<p class="empty" style="padding:16px">No hay eventos que coincidan con los filtros.</p>`;
}

function setupAlarms() {
  for (const id of ["#a-sev", "#a-kind", "#a-active"]) $(id).addEventListener("change", renderAlarms);
  $("#ack-all").addEventListener("click", async () => {
    const pending = visibleEvents().filter((e) => !e.acknowledged);
    await Promise.all(pending.map((e) => api(`/api/events/${e.id}/ack`, { method: "POST" })));
    toast(`${pending.length} alarma(s) reconocida(s).`);
    refreshNow();
  });
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

// ================================================================ WHAT-IF
function sensorRange(l) {
  const span = l.critical_high - l.critical_low;
  return [Math.max(0, l.critical_low - 0.3 * span), l.critical_high + 0.3 * span];
}

function setupWhatIf() {
  const cfg = state.config;
  $("#w-machine").innerHTML = state.fleet.machines.map((m) => `<option value="${h(m.id)}">${h(m.id)} · ${MODEL_LABEL(m.model)}</option>`).join("");
  $("#w-machine").addEventListener("change", (e) => loadWhatIf(e.target.value));
  $("#diag-fields").innerHTML = SENSORS.map((s) => {
    const l = cfg.sensor_limits[s];
    const [min, max] = sensorRange(l);
    const unit = cfg.sensor_units[s];
    return `<label class="field"><span>${SENSOR_LABEL[s]}${unit ? ` (${unit})` : ""} · normal ${num(l.alarm_low, 0)}–${num(l.alarm_high, 0)}</span>
      <div class="range-row">
        <input type="range" min="${min.toFixed(1)}" max="${max.toFixed(1)}" step="0.1" data-range="${s}" aria-label="${SENSOR_LABEL[s]}">
        <input type="number" name="${s}" min="0" step="0.1" required>
      </div>
    </label>`;
  }).join("");
  for (const r of $$("[data-range]")) {
    const n = $(`input[name="${r.dataset.range}"]`);
    r.addEventListener("input", () => { n.value = r.value; });
    n.addEventListener("input", () => { r.value = n.value; });
  }
  $("#diag-errors").innerHTML = [1, 2, 3, 4, 5].map((i) => `<label class="field"><span>error${i}</span><input type="number" name="error${i}" min="0" max="50" step="1"></label>`).join("");
  $("#diag-days").innerHTML = COMPONENTS.map((c) => `<label class="field"><span>${c}</span><input type="number" name="days_${c}" min="0" max="1000" step="0.5" placeholder="—"></label>`).join("");
  $("#diag-reset").addEventListener("click", () => fillWhatIf(state.whatIf.inputs));
  $("#diag-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#diag-error").hidden = true;
    try {
      const body = readWhatIf();
      renderWhatIf(await api("/api/diagnose", { method: "POST", body }), body);
    } catch (err) {
      $("#diag-error").textContent = `Entrada no válida: ${err.message}`;
      $("#diag-error").hidden = false;
    }
  });
}

async function loadWhatIf(id) {
  if (!id) return;
  state.whatIf.id = id;
  $("#w-machine").value = id;
  const inputs = await api(`/api/fleet/${encodeURIComponent(id)}/inputs`);
  state.whatIf.inputs = inputs;
  state.whatIf.baseline = await api("/api/diagnose", { method: "POST", body: inputs });
  fillWhatIf(inputs);
  renderWhatIf(state.whatIf.baseline, inputs);
}

function fillWhatIf(inp) {
  if (!inp) return;
  const f = $("#diag-form");
  f.model.value = inp.model;
  f.age.value = inp.age;
  for (const s of SENSORS) { f[s].value = inp.sensors[s]; $(`[data-range="${s}"]`).value = inp.sensors[s]; }
  for (const [e, n] of Object.entries(inp.errors_24h)) f[e].value = n;
  for (const c of COMPONENTS) f[`days_${c}`].value = inp.days_since[c] ?? "";
}

function readWhatIf() {
  const f = $("#diag-form");
  const numOrNull = (v) => (v === "" ? null : Number(v));
  return {
    model: f.model.value,
    age: Number(f.age.value),
    sensors: Object.fromEntries(SENSORS.map((s) => [s, Number(f[s].value)])),
    errors_24h: Object.fromEntries([1, 2, 3, 4, 5].map((i) => [`error${i}`, Number(f[`error${i}`].value || 0)])),
    days_since: Object.fromEntries(COMPONENTS.map((c) => [c, numOrNull(f[`days_${c}`].value)])),
  };
}

function renderWhatIf(r, inputs) {
  const base = state.whatIf.baseline;
  const level = { ALTO: "CRITICO", MEDIO: "ALERTA", BAJO: "OPERATIVO" }[r.risk_level];
  const delta = base ? r.failure_probability - base.failure_probability : 0;
  const comps = r.component_probabilities;
  $("#diag-result").innerHTML = `
    <header class="card-head"><h2>Resultado</h2>${statusBadge(level, true)}</header>
    <div class="diag-hero">
      <div><div class="big">${riskPct(r.failure_probability)}</div><div class="muted small">Probabilidad de falla en ${r.horizon_hours} h</div></div>
      <div><div class="big" style="font-size:28px">${r.predicted_component || "—"}</div><div class="muted small">Componente más probable</div></div>
      ${base ? `<div><div class="big" style="font-size:28px">${delta >= 0 ? "+" : "−"}${num(Math.abs(delta) * 100, 0)} pp</div><div class="muted small">frente al estado actual de ${h(state.whatIf.id)} (${riskPct(base.failure_probability)})</div></div>` : ""}
    </div>
    <h3 class="form-section">Probabilidad por componente</h3>
    ${COMPONENTS.map((c) => `<div class="comp-row${c === r.predicted_component ? " top" : ""}"><div class="comp-name">${c}</div>
      <div class="comp-bar"><span style="width:${Math.max(1, comps[c] * 100)}%"></span></div><div class="comp-val">${riskPct(comps[c])}</div></div>`).join("")}
    <h3 class="form-section" style="margin-top:12px">Sensores (media 24 h)</h3>
    <div class="diag-rows">${SENSORS.map((s) => {
      const st = r.sensor_states[s] || "normal";
      return `<div class="kpi${st === "critical" ? " is-critical" : st === "warning" ? " is-warning" : ""}">
        <span class="kpi-label">${st !== "normal" ? icon(SENSOR_STATE_ICON[st], `ic-${st}`) : icon("i-ok", "ic-good")}${SENSOR_LABEL[s]}</span>
        <span class="kpi-value" style="font-size:20px">${num(inputs.sensors[s], 1)}</span>
        <span class="kpi-foot">${st === "critical" ? "Fuera del límite crítico" : st === "warning" ? "Fuera del rango normal" : "Dentro de límites"}</span>
      </div>`;
    }).join("")}</div>
    <div class="callout"><strong>Recomendación:</strong> ${h(r.recommendation)}</div>
    <p class="small muted" style="margin-top:10px">La variabilidad de los sensores y sus medias de 3 h se toman de la media de 24 h o de valores típicos de entrenamiento.</p>`;
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

const MODEL_NAMES = { logistic_regression: "Regresión logística", random_forest: "Random Forest", hist_gradient_boosting: "Gradient Boosting (hist.)" };

function featureLabel(f) {
  let m = f.match(/^(volt|rotate|pressure|vibration)_(mean|std)_(3h|24h)$/);
  if (m) return `${SENSOR_LABEL[m[1]]} · ${m[2] === "mean" ? "media" : "desv."} ${m[3]}`;
  m = f.match(/^(error\d)_count_24h$/);
  if (m) return `${m[1]} · nº en 24 h`;
  m = f.match(/^(comp\d)_days_since$/);
  if (m) return `Días desde reemplazo ${m[1]}`;
  return { age: "Antigüedad", model: "Modelo" }[f] || f;
}

function seqCell(v, max) {
  const a = 0.08 + 0.72 * (max ? Math.min(1, v / max) : 0);
  return `<td class="cell" style="background:color-mix(in srgb, var(--series-1) ${Math.round(a * 100)}%, var(--surface-1));color:${a > 0.45 ? "#fff" : "var(--text-primary)"}">${v}</td>`;
}

function divCell(z) {
  const k = Math.min(1, Math.abs(z) / 5);
  const pole = z >= 0 ? "var(--div-pos)" : "var(--div-neg)";
  return `<td class="cell" style="background:color-mix(in srgb, ${pole} ${Math.round(k * 85)}%, var(--div-mid));color:${k > 0.55 ? "#fff" : "var(--text-primary)"}">${z > 0 ? "+" : ""}${num(z, 1)}σ</td>`;
}

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
  const ev = tm.events;
  const models = Object.keys(tr.validation_results);
  const classes = ["none", ...COMPONENTS];
  const cm = tm.multiclass_confusion_matrix;
  const cmMax = Math.max(...cm.flat().filter((_, i) => i !== 0));
  const sig = ds.failure_signature;
  const imp = tr.feature_importance.slice(0, 12);

  el.innerHTML = `
    ${tr.has_predictive_signal ? "" : `<div class="callout warn" style="margin-bottom:16px"><strong>El modelo no muestra señal predictiva</strong> (ROC-AUC en validación inferior a 0,6). Revise los datos antes de confiar en sus alarmas.</div>`}
    <div class="callout" style="margin-bottom:16px">
      <strong>Sobre estos resultados.</strong> El dataset Azure Predictive Maintenance es sintético: Microsoft lo generó para un tutorial,
      con precursores de falla muy limpios (errores del controlador y desviaciones de un sensor por componente). Por eso las métricas son casi perfectas;
      con telemetría real de planta espere valores más modestos. La evaluación es honesta: división temporal, sin fuga de información
      y medida en un periodo (${fmtDate(tr.splits.test.start)} – ${fmtDate(tr.splits.test.end)}) que el modelo no vio.
    </div>
    <div class="kpis" style="margin-bottom:16px">
      ${kpiTile({ label: "Modelo seleccionado", value: `<span style="font-size:17px">${MODEL_NAMES[tr.best_model] || tr.best_model}</span>`, foot: `Calibrado (isotónico) · entrenado ${fmtDate(tr.trained_at)}` })}
      ${kpiTile({ label: "PR-AUC (test)", value: num(tm.pr_auc, 3), foot: `Azar: ${num(tm.prevalence, 3)}` })}
      ${kpiTile({ label: "ROC-AUC (test)", value: num(tm.roc_auc, 3), foot: "Azar: 0,500" })}
      ${kpiTile({ label: "Fallas anticipadas", value: `${ev.anticipated}<small>/${ev.failure_events}</small>`, foot: `${pct(ev.anticipated_rate, 1)} de los eventos de test` })}
      ${kpiTile({ label: "Antelación mediana", value: num(ev.median_lead_hours, 0), unit: "h", foot: `Componente acertado ${pct(ev.correct_component_rate)}` })}
      ${kpiTile({ label: "Precisión / Recall", value: `${pct(tm.precision)}`, foot: `Recall ${pct(tm.recall, 1)} (por filas)` })}
      ${kpiTile({ label: "Umbral de alarma", value: pct(tr.decision_threshold, 1), foot: `Coste falla:falsa alarma = ${tr.costs.missed_failure}:${tr.costs.false_alarm}` })}
    </div>
    <div class="an-grid">
      <section class="card">
        <header class="card-head"><h2>Comparación de modelos · PR-AUC en validación</h2></header>
        <div class="chart-box short"><canvas id="an-cv"></canvas></div>
        <p class="note small muted">Validación temporal (${fmtDate(tr.splits.valid.start)} – ${fmtDate(tr.splits.valid.end)}). La línea discontinua es el PR-AUC de un clasificador aleatorio (la prevalencia de fallas).</p>
      </section>
      <section class="card">
        <header class="card-head"><h2>Variables más influyentes</h2><span class="muted small">Caída de PR-AUC al permutarlas</span></header>
        <div class="chart-box" style="height:${60 + imp.length * 22}px"><canvas id="an-imp"></canvas></div>
      </section>
      <section class="card">
        <header class="card-head"><h2>Matriz de confusión · test</h2><span class="muted small">Filas: real · columnas: predicho</span></header>
        <div class="table-wrap"><table class="cm">
          <tr><th></th>${classes.map((c) => `<th>${c === "none" ? "Sin falla" : c}</th>`).join("")}</tr>
          ${cm.map((row, i) => `<tr><th>${classes[i] === "none" ? "Sin falla" : classes[i]}</th>${row.map((v, j) => (i === 0 && j === 0 ? `<td class="cell excluded">${num(v, 0)}</td>` : seqCell(v, cmMax))).join("")}</tr>`).join("")}
        </table></div>
        <p class="note small muted">Una fila cada 3 h por máquina. La celda gris (sin falla correctamente) queda fuera de la escala de color para que se distingan los errores.</p>
      </section>
      <section class="card">
        <header class="card-head"><h2>Rendimiento por componente · test</h2></header>
        <div class="table-wrap"><table>
          <thead><tr><th>Clase</th><th class="num">Precisión</th><th class="num">Recall</th><th class="num">F1</th><th class="num">Filas</th></tr></thead>
          <tbody>${classes.map((c) => { const r = tm.per_class[c]; return `<tr><td><strong>${c === "none" ? "Sin falla" : c}</strong></td><td class="num">${pct(r.precision, 1)}</td><td class="num">${pct(r.recall, 1)}</td><td class="num">${num(r["f1-score"], 3)}</td><td class="num">${num(r.support, 0)}</td></tr>`; }).join("")}</tbody>
        </table></div>
      </section>
      <section class="card">
        <header class="card-head"><h2>Firma de cada falla</h2><span class="muted small">Media 24 h antes de fallar vs. operación normal</span></header>
        <div class="table-wrap"><table class="heat">
          <tr><th></th>${SENSORS.map((s) => `<th>${SENSOR_LABEL[s]}</th>`).join("")}</tr>
          ${COMPONENTS.map((c) => `<tr><th>${c}</th>${SENSORS.map((s) => divCell(sig[c][s])).join("")}</tr>`).join("")}
        </table></div>
        <div class="legend" style="margin-top:8px">
          <span><span class="sw" style="background:var(--div-neg)"></span>Por debajo de lo normal</span>
          <span><span class="sw" style="background:var(--div-mid);border:1px solid var(--border)"></span>Sin cambio</span>
          <span><span class="sw" style="background:var(--div-pos)"></span>Por encima de lo normal</span>
        </div>
        <p class="note small muted">En desviaciones estándar. Cada componente tiene un sensor delator: por eso el modelo puede decir <em>qué</em> va a fallar.</p>
      </section>
      <section class="card">
        <header class="card-head"><h2>Fallas por componente</h2><span class="muted small">${Object.values(ds.failures_by_component).reduce((x, y) => x + y, 0)} en 2015</span></header>
        <div class="chart-box short"><canvas id="an-fail"></canvas></div>
      </section>
      <section class="card">
        <header class="card-head"><h2>Datos de origen</h2><span class="muted small">${fmtDate(ds.start)} – ${fmtDate(ds.end)}</span></header>
        <dl class="dl">
          <dt>Máquinas</dt><dd>${ds.machines} (${Object.entries(ds.machines_by_model).map(([m, n]) => `${MODEL_LABEL(m)}: ${n}`).join(", ")})</dd>
          <dt>Lecturas de telemetría</dt><dd>${num(ds.telemetry_rows, 0)} (horarias)</dd>
          <dt>Fallas registradas</dt><dd>${Object.values(ds.failures_by_component).reduce((x, y) => x + y, 0)}</dd>
          <dt>Mantenimientos</dt><dd>${num(Object.values(ds.maintenance_by_component).reduce((x, y) => x + y, 0), 0)}</dd>
          <dt>Errores del controlador</dt><dd>${num(Object.values(ds.errors_by_type).reduce((x, y) => x + y, 0), 0)}</dd>
          <dt>Filas de entrenamiento</dt><dd>${num(ds.feature_rows, 0)} (${pct(ds.positive_rate, 1)} con falla en ${tr.horizon_hours} h)</dd>
          <dt>Train / validación / test</dt><dd>${num(tr.splits.train.rows, 0)} / ${num(tr.splits.valid.rows, 0)} / ${num(tr.splits.test.rows, 0)}</dd>
        </dl>
      </section>
      <section class="card">
        <header class="card-head"><h2>Calidad de datos · pipeline ETL</h2><span class="muted small">${q ? `Cargado ${fmtDate(q.loaded_at)}` : ""}</span></header>
        ${q ? `<dl class="dl">
          <dt>Telemetría: duplicados</dt><dd>${q.telemetry.duplicates_removed}</dd>
          <dt>Telemetría: fuera de rango</dt><dd>${Object.values(q.telemetry.out_of_range_set_null).reduce((x, y) => x + y, 0)}</dd>
          <dt>Telemetría: valores interpolados</dt><dd>${Object.values(q.telemetry.nulls_interpolated).reduce((x, y) => x + y, 0)}</dd>
          <dt>Errores descartados</dt><dd>${q.errors.invalid_removed + q.errors.duplicates_removed}</dd>
          <dt>Mantenimientos descartados</dt><dd>${q.maint.invalid_removed + q.maint.duplicates_removed}</dd>
          <dt>Fallas descartadas</dt><dd>${q.failures.invalid_removed + q.failures.duplicates_removed}</dd>
        </dl>` : `<p class="empty">Sin reporte de calidad.</p>`}
      </section>
    </div>`;

  barChart($("#an-cv"), {
    labels: models.map((m) => MODEL_NAMES[m] || m),
    values: models.map((m) => tr.validation_results[m].pr_auc),
    max: 1,
    format: (v) => num(v, 2),
    reference: { value: tr.validation_prevalence, label: `Azar ${num(tr.validation_prevalence, 3)}` },
  });
  barChart($("#an-imp"), {
    labels: imp.map((r) => featureLabel(r.feature)),
    values: imp.map((r) => r.importance),
    format: (v) => num(v, 3),
    horizontal: true,
  });
  barChart($("#an-fail"), {
    labels: COMPONENTS,
    values: COMPONENTS.map((c) => ds.failures_by_component[c]),
    format: (v) => num(v, 0),
  });
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
    await refresh();
    setConnection(true, "En línea");
  } catch (err) {
    setConnection(false, "Sin conexión");
    $("#content").innerHTML = `<div class="card" style="max-width:640px"><h2>No se puede cargar la flota</h2>
      <p class="muted" style="margin-top:6px">${h(err.message)}</p>
      <p class="muted" style="margin-top:6px">Ejecute <code>python run_pipeline.py</code> (descarga los datos, ejecuta el ETL y entrena el modelo) y reinicie <code>uvicorn src.api.main:app</code>.</p></div>`;
    return;
  }
  setupFilters();
  setupMachineView();
  setupAlarms();
  setupWhatIf();
  $("#fleet").addEventListener("click", (e) => {
    const target = e.target.closest("[data-id]");
    if (target) location.hash = `#/machine/${encodeURIComponent(target.dataset.id)}`;
  });
  window.addEventListener("hashchange", onRoute);
  onRoute();
  setTimeout(poll, POLL_MS);
}

init();
