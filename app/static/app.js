"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt = (x, d = 1) => (x == null ? "–" : Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dateFr = iso => new Date(iso + "T00:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });

let CFG = {}, STATUS = {}, RESULTS = null, charts = {}, pollTimer = null, selectedFile = null, wasTraining = false;

async function api(url, opts) {
  const r = await fetch(url, opts);
  let body = null; try { body = await r.json(); } catch { /* non JSON */ }
  if (!r.ok) throw new Error((body && body.detail) || `Erreur ${r.status}`);
  return body;
}
function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms);
}
function alertBox(el, msg, kind = "") { el.hidden = !msg; el.className = "alert " + kind; el.textContent = msg || ""; }
function form(obj) { const f = new FormData(); Object.entries(obj).forEach(([k, v]) => f.append(k, v)); return f; }

/* ---------- Onglets ---------- */
function showTab(n) {
  $$(".step").forEach(b => b.classList.toggle("active", b.dataset.tab == n));
  $$(".panel").forEach(p => p.classList.toggle("active", p.id === "tab" + n));
  window.scrollTo({ top: $("#steps").offsetTop - 10, behavior: "smooth" });
}
$$(".step").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

/* ---------- Compte à rebours ---------- */
function countdown() {
  if (!CFG.event) return;
  const start = new Date(CFG.event.start + "T00:00:00"), end = new Date(CFG.event.end + "T23:59:59"), now = new Date();
  const days = Math.ceil((start - now) / 864e5);
  if (now < start) {
    $("#cdLabel").textContent = "Ouverture dans"; $("#cdNum").textContent = days + " j";
    $("#cdSub").textContent = "du " + start.toLocaleDateString("fr-FR", { day: "numeric", month: "long" }) + " au " + end.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  } else if (now <= end) {
    const d = Math.floor((now - start) / 864e5) + 1;
    $("#cdLabel").textContent = "Jeux en cours"; $("#cdNum").textContent = "Jour " + d; $("#cdSub").textContent = "Que la fête commence !";
  } else { $("#cdLabel").textContent = "Jeux terminés"; $("#cdNum").textContent = "Merci"; $("#cdSub").textContent = CFG.event.name; }
}

/* ---------- Graphiques ---------- */
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function makeChart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($("#" + id), cfg);
}
const baseOpts = () => ({
  responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
  plugins: { legend: { labels: { color: css("--muted"), usePointStyle: true } } },
  scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 10 }, grid: { display: false } },
            y: { ticks: { color: css("--muted") }, grid: { color: css("--line") } } },
});

async function drawHistory() {
  const { history } = await api("/api/history?last_n=120");
  if (!history.length) return;
  makeChart("chartHistory", { type: "line", data: {
    labels: history.map(h => h.Date),
    datasets: [{ label: "PM2,5 observé (µg/m³)", data: history.map(h => h.PM25), borderColor: "#0B3D91",
      backgroundColor: "rgba(11,61,145,.12)", fill: true, pointRadius: 0, tension: .25, borderWidth: 2 }] },
    options: baseOpts() });
}
function drawLoss(meta) {
  const h = (meta && meta.loss_history) || [];
  if (!h.length) return;
  const o = baseOpts(); o.scales.x.ticks.maxTicksLimit = 8;
  makeChart("chartLoss", { type: "line", data: { labels: h.map(l => l.epoch), datasets: [
    { label: "Perte entraînement", data: h.map(l => l.loss), borderColor: "#00A651", pointRadius: 0, borderWidth: 2 },
    { label: "Perte validation", data: h.map(l => l.val_loss), borderColor: "#E31B23", pointRadius: 0, borderWidth: 2 }] }, options: o });
}
async function drawForecast(res) {
  const { history } = await api("/api/history?last_n=45");
  const fc = res.forecast, lastObs = history[history.length - 1];
  const labels = [...history.map(h => h.Date), ...fc.map(f => f.Date)];
  const nH = history.length, pad = n => Array(n).fill(null);
  const obs = [...history.map(h => h.PM25), ...pad(fc.length)];
  const mean = [...pad(nH - 1), lastObs.PM25, ...fc.map(f => f.Forecast)];
  const lo = [...pad(nH - 1), lastObs.PM25, ...fc.map(f => f.Lower_95)];
  const up = [...pad(nH - 1), lastObs.PM25, ...fc.map(f => f.Upper_95)];
  const ref = labels.map(() => res.sn_reference);
  makeChart("chartForecast", { type: "line", data: { labels, datasets: [
    { label: "Observé", data: obs, borderColor: "#0B3D91", pointRadius: 0, borderWidth: 2.5, tension: .2 },
    { label: "Prévision", data: mean, borderColor: "#E31B23", borderWidth: 3, pointRadius: 5, pointBackgroundColor: "#E31B23", borderDash: [6, 4] },
    { label: "IC 95 % (bas)", data: lo, borderColor: "transparent", pointRadius: 0, backgroundColor: "transparent" },
    { label: "IC 95 %", data: up, borderColor: "transparent", pointRadius: 0, fill: "-1", backgroundColor: "rgba(227,27,35,.22)" },
    { label: `Repère SN (${res.sn_reference})`, data: ref, borderColor: "#F77F00", borderDash: [2, 4], pointRadius: 0, borderWidth: 1.5 }] },
    options: { ...baseOpts(), plugins: { legend: { labels: { color: css("--muted"), usePointStyle: true,
      filter: i => i.text !== "IC 95 % (bas)" } } } } });
}

/* ---------- Statut ---------- */
async function refreshStatus() {
  STATUS = await api("/api/status");
  const { data: d, model: m, training: t } = STATUS;
  setChip("#chipData", d.available ? "ok" : "warn",
    d.available ? `<b>Données :</b> ${d.rows} jours (${d.start} → ${d.end})` : "<b>Données :</b> aucune");
  const mTxt = !m.trained ? "non entraîné" : m.outdated ? "à réentraîner (nouvelles données)" : "à jour ✓";
  setChip("#chipModel", !m.trained ? "warn" : m.outdated ? "warn" : "ok", `<b>Modèle :</b> ${mTxt}`);
  setChip("#chipFc", STATUS.has_results ? "ok" : "warn", `<b>Prévision :</b> ${STATUS.has_results ? "disponible" : "aucune"}`);
  renderDataKpis(d); renderModel(m, t);
  $("#btnTrain").disabled = t.status === "running" || !d.available || !d.enough_to_train;
  $("#btnPredict").disabled = !m.trained || t.status === "running";
  $("#steps .step[data-tab='1']").classList.toggle("done", d.available);
  $("#steps .step[data-tab='2']").classList.toggle("done", m.trained && !m.outdated);
  $("#steps .step[data-tab='3']").classList.toggle("done", STATUS.has_results);
  $("#steps .step[data-tab='4']").classList.toggle("done", STATUS.has_results);
  $("#steps .step[data-tab='5']").classList.toggle("done", STATUS.has_results);
  return t;
}
function setChip(sel, kind, html) { const c = $(sel); c.className = "chip " + kind; c.innerHTML = html; }
function kpi(v, l) { return `<div class="kpi"><b>${v}</b><span>${l}</span></div>`; }
function renderDataKpis(d) {
  if (!d.available) { $("#dataKpis").innerHTML = '<p class="muted">Aucune donnée chargée.</p>'; return; }
  let h = kpi(d.rows, "jours") + kpi(fmt(d.mean), "moyenne µg/m³") + kpi(fmt(d.max), "max µg/m³") + kpi(fmt(d.min), "min µg/m³") + kpi(d.missing_days, "jours manquants");
  if (!d.enough_to_train) h += `<p class="muted">⚠ Minimum ${d.min_rows} observations requises pour entraîner.</p>`;
  $("#dataKpis").innerHTML = h;
}
function renderModel(m, t) {
  if (!m.trained) { $("#modelKpis").innerHTML = '<p class="muted">Modèle non entraîné.</p>'; }
  else {
    const mt = m.metrics || {};
    $("#modelKpis").innerHTML = kpi(fmt(mt.rmse, 2), "RMSE test µg/m³") + kpi(fmt(mt.mae, 2), "MAE test µg/m³") +
      kpi(m.epochs_run, "époques") + kpi(m.n_params.toLocaleString("fr-FR"), "paramètres") +
      `<p class="muted" style="grid-column:1/-1">Entraîné le ${new Date(m.trained_at).toLocaleString("fr-FR")} sur ${m.n_rows} jours (jusqu'au ${m.data_end}).` +
      (m.outdated ? " <b>De nouvelles données sont disponibles : réentraînez le modèle.</b>" : "") + "</p>";
    drawLoss(m);
  }
  const run = t.status === "running";
  $("#progress").hidden = !run;
  if (run) {
    const pct = Math.min(100, (t.epoch / Math.max(t.epochs, 1)) * 100);
    $("#barFill").style.width = pct + "%";
    const last = t.logs[t.logs.length - 1];
    $("#progText").textContent = `Époque ${t.epoch}/${t.epochs} (arrêt anticipé possible)` + (last ? ` · perte val = ${last.val_loss.toFixed(5)}` : "");
  }
  if (t.status === "error") alertBox($("#trainMsg"), "Échec de l'entraînement : " + t.message, "err");
}

/* ---------- Suivi de l'entraînement ---------- */
function startPolling() { if (!pollTimer) pollTimer = setInterval(tick, 1500); }
async function tick() {
  const t = await refreshStatus().catch(() => null);
  if (!t) return;
  if (t.status === "running") { wasTraining = true; return; }
  clearInterval(pollTimer); pollTimer = null;
  if (wasTraining) {
    wasTraining = false;
    if (t.status === "done") {
      alertBox($("#trainMsg"), "✔ Modèle entraîné. Prévisions mises à jour automatiquement.", "ok");
      toast("Modèle entraîné ✔"); await loadResults(); drawHistory();
    }
  }
}

/* ---------- Résultats ---------- */
async function loadResults() {
  if (!STATUS.has_results) { RESULTS = null; return; }
  try {
    const f = await api("/api/forecast"), c = await api("/api/classification"), r = await api("/api/risks");
    RESULTS = { ...f, ...c, ...r }; renderResults();
  } catch (e) { /* aucune prévision */ }
}
function renderResults() {
  const R = RESULTS; if (!R) return;
  $("#chipFc").innerHTML = `<b>Prévision :</b> ${R.n_days} j · ${new Date(R.generated_at).toLocaleString("fr-FR")}`;
  // Prévisions
  $("#fcCards").innerHTML = R.forecast.map(f => {
    const c = f.forecast_class;
    return `<div class="fc l${c.level || 0}" style="background:${c.color}">
      <span class="tag">${esc(c.label)}</span><div class="day">${f.Day}</div><div class="date">${dateFr(f.Date)}</div>
      <div class="val">${fmt(f.Forecast)} <small>µg/m³</small></div>
      <div class="ci">IC 95 % : ${fmt(f.Lower_95)} – ${fmt(f.Upper_95)} · σ = ${fmt(f.SD)}</div></div>`;
  }).join("");
  drawForecast({ forecast: R.forecast, sn_reference: R.sn_reference });
  // Classification
  $("#legend").innerHTML = R.scale.map(s => `<div><i style="background:${R.levels[s.level].color}"></i><b>${R.levels[s.level].label}</b> ${s.range}</div>`).join("");
  $("#classCards").innerHTML = R.forecast.map(f => {
    const c = f.forecast_class, mini = (lbl, b) => `<div><span>${lbl}</span><b>${esc(b.label)}</b></div>`;
    return `<div class="fc l${c.level || 0}" style="background:${c.color}">
      <span class="tag">${esc(c.label)}</span><div class="day">${f.Day} · ${dateFr(f.Date)}</div>
      <div class="val">${fmt(f.Forecast)} <small>µg/m³</small></div>
      <div class="cls">${esc(c.text || "Valeur ≤ 0 : non classée")}</div>
      <div class="trio">${mini("Borne basse", f.lower_class)}${mini("Prévision", c)}${mini("Borne haute", f.upper_class)}</div></div>`;
  }).join("");
  // Risques
  $("#riskNote").textContent = `RR par 10 µg/m³ · contrefactuel = ${R.counterfactual} µg/m³ · repère réglementaire sénégalais = ${R.sn_reference} µg/m³. Un message est émis si PM2,5 prévu > ${R.counterfactual} µg/m³ (valeur guide OMS).`;
  const rows = R.health.map(h => `<tr><td>${h.Day}</td><td>${dateFr(h.Date)}</td><td>${fmt(h.Forecast)}</td><td>${esc(h.Outcome)} (${h.ICD10})</td>
    <td>${fmt(h.RR_obs, 4)} <span class="muted">[${fmt(h.RR_obs_low, 4)} – ${fmt(h.RR_obs_high, 4)}]</span></td>
    <td>${fmt(h.FA_pct, 2)} % <span class="muted">[${fmt(h.FA_pct_low, 2)} – ${fmt(h.FA_pct_high, 2)}]</span></td></tr>`).join("");
  $("#riskTable").innerHTML = `<thead><tr><th>Jour</th><th>Date</th><th>PM2,5</th><th>Motif</th><th>RR observé [IC]</th><th>FA [IC]</th></tr></thead><tbody>${rows}</tbody>`;
  const withMsg = R.messages.filter(m => m.Message);
  $("#messages").innerHTML = withMsg.length
    ? withMsg.map(m => `<div class="msg"><h3>${m.Day} · ${dateFr(m.Date)}</h3><p>${esc(m.Message)}</p></div>`).join("")
    : `<div class="msg none"><h3>Aucun message sanitaire</h3><p>Le PM2,5 prévu reste ≤ ${R.counterfactual} µg/m³ (valeur guide OMS) sur tout l'horizon : pas de message à diffuser.</p></div>`;
}

/* ---------- Actions ---------- */
const drop = $("#drop"), fileInput = $("#file");
function pick(f) { selectedFile = f; $("#fname").textContent = f ? "📎 " + f.name : ""; $("#btnUpload").disabled = !f; }
fileInput.addEventListener("change", () => pick(fileInput.files[0]));
["dragover", "dragenter"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", ev => pick(ev.dataTransfer.files[0]));

$("#btnUpload").addEventListener("click", async () => {
  const btn = $("#btnUpload"); btn.disabled = true; btn.textContent = "Chargement…";
  try {
    const f = form({ file: selectedFile, mode: $("input[name=mode]:checked").value, retrain: $("#retrain").checked });
    const r = await api("/api/upload", { method: "POST", body: f });
    let msg = `✔ ${r.filename} chargé : ${r.rows_added} nouveau(x) jour(s), total ${r.rows_after}.`;
    if (r.dropped_rows) msg += ` ${r.dropped_rows} ligne(s) invalide(s) ignorée(s).`;
    if (r.training_started) { msg += " Réentraînement lancé…"; wasTraining = true; startPolling(); setTimeout(() => showTab(2), 700); }
    else if (r.note) msg += " " + r.note;
    alertBox($("#uploadMsg"), msg, "ok"); await refreshStatus(); drawHistory();
  } catch (e) { alertBox($("#uploadMsg"), e.message, "err"); }
  btn.textContent = "Charger les données"; btn.disabled = !selectedFile;
});

$("#btnDemo").addEventListener("click", async ev => {
  ev.preventDefault();
  if (!confirm("Charger une série SYNTHÉTIQUE de démonstration (remplace les données actuelles) ?")) return;
  try {
    await api("/api/demo-data", { method: "POST", body: form({ retrain: false }) });
    alertBox($("#uploadMsg"), "✔ Données de démonstration chargées (fictives). Passez à l'étape 2 pour entraîner.", "ok");
    await refreshStatus(); drawHistory();
  } catch (e) { alertBox($("#uploadMsg"), e.message, "err"); }
});

$("#btnTrain").addEventListener("click", async () => {
  try {
    alertBox($("#trainMsg"), "");
    await api("/api/train", { method: "POST", body: form({ epochs: $("#epochs").value }) });
    wasTraining = true; startPolling(); await refreshStatus();
  } catch (e) { alertBox($("#trainMsg"), e.message, "err"); }
});

$("#btnPredict").addEventListener("click", async () => {
  const btn = $("#btnPredict"); btn.disabled = true; btn.textContent = "Simulation en cours…";
  try {
    await api("/api/predict", { method: "POST", body: form({ n_days: $("#nDays").value }) });
    await refreshStatus(); await loadResults(); toast("Prévision mise à jour ✔");
  } catch (e) { toast("⚠ " + e.message, 5000); }
  btn.textContent = "Lancer la prévision"; btn.disabled = !(STATUS.model && STATUS.model.trained);
});

$$("[data-dl]").forEach(b => b.addEventListener("click", () => {
  if (!STATUS.has_results) return toast("Aucune prévision à télécharger : lancez d'abord l'étape 3.");
  window.location.href = "/api/download/" + b.dataset.dl;
}));

/* ---------- Init ---------- */
(async function init() {
  CFG = await api("/api/config");
  $("#nDays").innerHTML = Array.from({ length: CFG.max_days }, (_, i) => `<option value="${i + 1}" ${i + 1 === CFG.default_days ? "selected" : ""}>${i + 1} jour${i ? "s" : ""}</option>`).join("");
  $("#epochs").value = CFG.epochs;
  countdown(); setInterval(countdown, 3600e3);
  const t = await refreshStatus();
  await drawHistory(); await loadResults();
  if (t.status === "running") { wasTraining = true; startPolling(); }
})();
