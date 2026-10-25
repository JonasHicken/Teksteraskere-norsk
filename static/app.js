"use strict";
/* Teksting - front end. Plain JS, no external libraries (works offline). */

// ---------------------------------------------------------------- utils ---
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const ICON = {
  ear: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  wrap: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 6h16M4 12h12.5a3 3 0 0 1 0 6H12m2-2.5L11.5 18l2.5 2.5M4 18h4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  split: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 4v16M4 8v8M20 8v8M7 12H4m13 0h3" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  merge: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 7v10M20 7v10M7 12h10m-3-3 3 3-3 3m-4-6-3 3 3 3" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12M10.5 11v5M13.5 11v5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  keys: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="3" y="6.5" width="18" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M7 10h.01M10.5 10h.01M14 10h.01M17 10h.01M8 14h8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
  play: '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor"/></svg>',
  back: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M11 6 5 12l6 6M5.5 12H19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  rew: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M11 7 5 12l6 5zM19 7l-6 5 6 5z" fill="currentColor"/></svg>',
  fwd: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="m13 7 6 5-6 5zM5 7l6 5-6 5z" fill="currentColor"/></svg>',
  undo: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M9 7 4 12l5 5M4.5 12H14a5 5 0 0 1 0 10h-2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  redo: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="m15 7 5 5-5 5M19.5 12H10a5 5 0 0 0 0 10h2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

let LANG = "nb";
function t(key, vars) {
  let s = (STR[LANG] && STR[LANG][key]) ?? STR.en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split("{" + k + "}").join(v);
  return s;
}
const locale = () => (LANG === "nb" ? "nb-NO" : "en-GB");
const num = (x, d = 1) => new Intl.NumberFormat(locale(), { maximumFractionDigits: d, minimumFractionDigits: 0 }).format(x);
function fmtDur(s) {
  if (s == null || !isFinite(s)) return "";
  s = Math.max(0, Math.round(s));
  if (s < 60) return t("dur_s", { s });
  if (s < 3600) return t("dur_m", { m: Math.max(1, Math.round(s / 60)) });
  const hh = Math.floor(s / 3600), mm = Math.round((s % 3600) / 60);
  return mm ? t("dur_hm", { h: hh, m: mm }) : t("dur_h", { h: hh });
}
const fmtGB = (b) => (b >= 1e9 ? num(b / 1e9) + " GB" : num(b / 1e6, 0) + " MB");
function fmtTC(sec, digits = 1) {
  sec = Math.max(0, sec || 0);
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60);
  const ss = (sec % 60).toFixed(digits).padStart(digits ? 3 + digits : 2, "0");
  return `${hh}:${String(mm).padStart(2, "0")}:${ss}`;
}
function parseTC(str) {
  const parts = String(str).trim().replace(",", ".").split(":").map(Number);
  if (!parts.length || parts.some((p) => !isFinite(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}
const dirname = (p) => p.replace(/[\\/][^\\/]*$/, "");

async function api(method, url, body, opts = {}) {
  const r = await fetch(url, {
    method,
    headers: body !== undefined ? { "content-type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    ...opts,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r.text();
}

function toast(msg, action, ms) {
  const actions = action ? (Array.isArray(action) ? action : [action]) : [];
  const el = h("div", { class: "toast" }, h("span", null, msg));
  for (const a of actions) el.append(h("button", { class: "link", type: "button", onclick: () => { a.run(); el.remove(); } }, a.label));
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms || (actions.length ? 9000 : 4500));
  return el;
}

// ---- hover explanations: any element with data-tip gets a small tooltip
const TIP = h("div", { class: "tip", role: "tooltip", hidden: true });
document.body.append(TIP);
let tipTimer = null, tipEl = null;
function showTip(el) {
  if (!el.isConnected || !el.dataset.tip) return;
  TIP.textContent = el.dataset.tip;
  TIP.hidden = false;
  const r = el.getBoundingClientRect();
  const tw = TIP.offsetWidth, th = TIP.offsetHeight;
  const x = Math.max(8, Math.min(r.left + r.width / 2 - tw / 2, innerWidth - tw - 8));
  let y = r.bottom + 8;
  if (y + th > innerHeight - 8) y = r.top - th - 8;
  TIP.style.left = x + "px";
  TIP.style.top = y + "px";
}
function hideTip() { clearTimeout(tipTimer); tipEl = null; TIP.hidden = true; }
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest && e.target.closest("[data-tip]");
  if (el === tipEl) return;
  hideTip();
  if (!el) return;
  tipEl = el;
  tipTimer = setTimeout(() => showTip(el), 400);
});
document.addEventListener("focusin", (e) => {
  const el = e.target.closest && e.target.closest("[data-tip]");
  if (el && el.matches(":focus-visible")) { tipEl = el; showTip(el); }
});
document.addEventListener("focusout", hideTip);
document.addEventListener("pointerdown", hideTip, true);
document.addEventListener("mouseleave", hideTip);
window.addEventListener("scroll", hideTip, true);

function ask(title, body, okLabel, { danger = false } = {}) {
  const d = $("#dialog");
  $("#dlg-title").textContent = title;
  $("#dlg-body").textContent = body;
  $("#dlg-ok").textContent = okLabel;
  $("#dlg-ok").className = "btn " + (danger ? "danger" : "primary");
  $("#dlg-cancel").textContent = t("cancel");
  return new Promise((res) => {
    d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true });
    d.returnValue = "";  // a dialog closed without a button must never count as the previous dialog's "ok"
    d.showModal();
    $("#dlg-cancel").focus();
  });
}

// ---------------------------------------------------------------- state ---
const S = { state: null, armed: null, editor: null, dl: {} };
const RUNNING = ["downloading", "loading", "transcribing", "checking", "finishing"];
const SHOWN = {}; // job id -> last progress shown (the bar never moves backwards)

// Progress between server reports: the server says how fast it is going (rate) and how far it can
// get before the next report (cap); we move the bar along that line every 250 ms.
function live(j) {
  let p = j.progress || 0, eta = j.eta;
  if (j.pt && j.rate && j.status !== "downloading") {
    const age = Math.max(0, Date.now() / 1000 + (S.skew || 0) - j.pt);
    p = Math.max(p, Math.min(j.cap ?? p, p + j.rate * age));
    if (eta != null) eta = Math.max(0, eta - age);
  }
  const key = j.id + (j.status === "downloading" ? ":dl" : "");
  const prev = SHOWN[key];
  if (prev != null && prev > p) {
    if (eta != null && j.rate) eta = Math.max(0, eta - (prev - p) / j.rate);
    p = prev;
  }
  SHOWN[key] = p;
  return { p: Math.min(1, p), eta };
}

function tickJobs() {
  if (!S.state) return;
  if (busyNow() && S.pollAt - Date.now() > 1000) schedulePoll(250);  // a job was just added or started: follow it closely
  for (const j of S.state.jobs) {
    if (!RUNNING.includes(j.status)) { delete SHOWN[j.id]; delete SHOWN[j.id + ":dl"]; continue; }
    if (j.status !== "downloading") delete SHOWN[j.id + ":dl"];
    const row = document.querySelector(`.job[data-id="${j.id}"]`);
    if (!row) continue;
    const bar = row.querySelector(".bar span"), st = row.querySelector(".job-st");
    const txt = statusText(j);
    if (bar) bar.style.width = (live(j).p * 100).toFixed(2) + "%";
    if (st && st.textContent !== txt) st.textContent = txt;
  }
}
setInterval(tickJobs, 250);

// Poll every second while something runs, every 3 s when idle, every 10 s while the window is minimised
// (the server quits a browser-mode session after 90 s without a poll).
function busyNow() {
  const st = S.state;
  if (!st) return true;
  return st.jobs.some((j) => RUNNING.includes(j.status) || j.checking || (j.status === "queued" && !st.paused) || ["queued", "running"].includes(j.export?.status))
    || Object.keys(S.dl || {}).length > 0;
}
function schedulePoll(ms) {
  if (S.stopped) return;
  clearTimeout(S.pollT);
  S.pollAt = Date.now() + ms;
  S.pollT = setTimeout(poll, ms);
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") schedulePoll(0); });

// Updates (tekst/update.py): one notice per session when a new version has been downloaded
function updateLine() {
  const u = (S.state && S.state.update) || {};
  return [u.version ? t("version", { v: u.version }) : t("version_dev"),
    u.ready ? t("update_ready") : "", u.error ? t("update_failed") : ""].filter(Boolean).join(" · ");
}
function noticeUpdate() {
  const u = S.state.update || {};
  if (u.ready && S.updateShown !== u.ready) { S.updateShown = u.ready; toast(t("update_ready"), null, 12000); }
}

async function poll() {
  clearTimeout(S.pollT);
  try {
    S.state = await api("GET", "/api/state");
    if (S.state.now) S.skew = S.state.now - Date.now() / 1000;
    if (route().name === "settings" || Object.keys(S.dl || {}).length) S.dl = await api("GET", "/api/downloads");
    $("#offline").hidden = true;
    applyLang();
    noticeUpdate();
    if (route().name === "jobs") updateJobs();
    if (S.editor) S.editor.sync(S.state);
    if (route().name === "settings") updateModels();
    schedulePoll(document.visibilityState !== "visible" ? 10000 : busyNow() ? 1000 : 3000);
  } catch (e) {
    $("#offline").hidden = false;
    schedulePoll(1000);
  }
}

function applyLang() {
  const want = S.state?.settings?.ui_lang || (/^(nb|no|nn)\b/i.test(navigator.language) ? "nb" : "en");
  if (want !== LANG) {
    LANG = want;
    document.documentElement.lang = LANG === "nb" ? "nb" : "en";
    (async () => { if (S.editor) { await S.editor.destroy(); S.editor = null; } render(); })();
  }
  $$("[data-t]").forEach((el) => { const s = t(el.dataset.t); if (el.textContent !== s) el.textContent = s; });
  const lt = $("#lang-toggle"), ls = LANG === "nb" ? "English" : "Norsk";
  if (lt.textContent !== ls) lt.textContent = ls;
}

async function saveSettings(patch) {
  S.state = await api("PUT", "/api/settings", patch);
  return S.state;
}

// --------------------------------------------------------------- router ---
function route() {
  const m = location.hash.match(/^#\/(settings|edit)?\/?([\w-]*)/);
  if (!m || !m[1]) return { name: "jobs" };
  return { name: m[1], id: m[2] };
}
async function render() {
  const r = route();
  if (S.editor && (r.name !== "edit" || r.id !== S.editor.id)) { await S.editor.destroy(); S.editor = null; }
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === (r.name === "edit" ? "jobs" : r.name)));
  document.body.classList.toggle("editing", r.name === "edit");
  if (!S.state) return;
  if (r.name === "settings") viewSettings();
  else if (r.name === "edit") { if (!S.editor) { S.editor = new Editor(r.id); } }
  else viewJobs();
}
window.addEventListener("hashchange", render);

// ----------------------------------------------------------------- jobs ---
function viewJobs() {
  const v = $("#view");
  v.className = "page jobs";
  const st = S.state.settings;
  const models = S.state.models;
  const modelSel = h("select", { id: "model", onchange: (e) => saveSettings({ model: e.target.value }).then(updateJobs) },
    ["large", "medium", "small"].map((n) =>
      h("option", { value: n, selected: st.model === n },
        t("model_" + n) + " (" + fmtGB(models[n].size) + (models[n].ready ? ", " + t("downloaded") : "") + ")")));
  const langSel = h("select", { id: "lang", onchange: (e) => saveSettings({ language: e.target.value }) },
    h("option", { value: "no", selected: st.language === "no" }, "Bokmål"),
    h("option", { value: "nn", selected: st.language === "nn" }, "Nynorsk"));
  v.replaceChildren(
    h("section", { class: "intro" },
      h("h1", null, t("jobs_title")),
      h("p", { class: "lead" }, t("jobs_lead"))),
    h("div", { class: "addbar" },
      h("button", { class: "btn primary big", type: "button", id: "add", onclick: pickFiles }, t("add_videos")),
      h("label", { class: "field", "data-tip": t("tip_quality") }, h("span", null, t("quality")), modelSel),
      h("label", { class: "field" }, h("span", null, t("language")), langSel)),
    h("div", { id: "queueline", class: "queueline", "aria-live": "polite" }),
    h("div", { id: "statsline", class: "statsline" }),
    h("div", { id: "batchbar", class: "batchbar" }),
    h("ol", { id: "joblist", class: "joblist" }),
    h("p", { class: "fineprint" }, t("privacy")));
  updateJobs();
}

async function pickFiles() {
  const b = $("#add");
  b.disabled = true;
  b.textContent = t("picker_open");
  try {
    const r = await api("POST", "/api/pick", { title: t("picker_title") });
    S.state = r;
    if (r.added.length) toast(t("added_n", { n: r.added.length }));
  } catch (e) {
    toast(t("picker_failed") + " " + e.message);
  } finally {
    b.disabled = false;
    b.textContent = t("add_videos");
    updateJobs();
  }
}

function jobEstimate(j) {
  const m = S.state.models[j.model], sm = S.state.models.small;
  if (!j.duration || !m) return null;
  const check = S.state.settings.double_check && j.model !== "small" ? sm.speed : 0;
  return j.duration * (m.speed + check) * (S.state.time_scale || 1);
}
// Seconds of double-check still ahead for a job (it runs after the video is ready to proofread).
function checkLeft(j) {
  const sm = S.state.models.small;
  if (!j.duration || !sm) return 0;
  if (j.checking) return (1 - (j.check || 0)) * j.duration * sm.speed * (S.state.time_scale || 1);
  return RUNNING.includes(j.status) && j.double ? j.duration * sm.speed * (S.state.time_scale || 1) : 0;
}

function statusText(j) {
  const m = S.state.models[j.model];
  switch (j.status) {
    case "queued": {
      const e = jobEstimate(j);
      return t("st_queued") + (e ? " " + t("st_takes", { d: fmtDur(e) }) : "");
    }
    case "downloading":
    {
      const dm = S.state.models[j.dl_model || j.model] || m;
      return t("st_downloading", { model: t("model_short_" + (j.dl_model || j.model)), done: fmtGB((j.progress || 0) * dm.size), total: fmtGB(dm.size) });
    }
    case "loading": return t("st_loading");
    case "transcribing": case "checking": case "finishing": {
      const { p, eta } = live(j);
      const ph = j.phase && j.phase !== "decode" && j.status !== "finishing" ? " " + t("ph_" + j.phase) : "";
      const left = eta == null ? "" : eta < 15 ? " " + t("st_soon") : " " + t("st_left", { d: fmtDur(eta) });
      return t("st_" + j.status, { pct: Math.floor(p * 100) }) + ph + left;
    }
    case "done": return t("st_done", { n: j.cues }) + (j.checking ? " " + t("st_checking_bg", { pct: Math.floor((j.check || 0) * 100) }) : "") + (j.disagree ? " " + t("st_disagree", { n: j.disagree }) : "") + (j.rescued ? " " + t("st_rescued", { n: j.rescued }) : "") + (j.edited ? " " + t("st_edited") : "");
    case "error":
      if (j.error_kind === "download") return t("err_download", { msg: j.message || "" });
      if (j.error_kind === "missing") return t("err_missing");
      return t("st_error", { msg: j.message || "" });
    case "cancelled": return t("st_cancelled");
    default: return j.status;
  }
}

function metricsLine(j) {
  if (j.status !== "done") return null;
  const parts = [];
  if (j.work_seconds >= 30) {
    const ratio = j.duration ? j.work_seconds / j.duration : null;
    parts.push(t("m_work", { w: fmtDur(j.work_seconds) }) + (ratio ? " " + t("m_ratio", { r: num(ratio, 1) }) : ""));
  }
  if (j.edit_rate) parts.push(t("m_edit", { p: num(j.edit_rate * 100, 0) }));
  if (j.autofixed) parts.push(t("m_autofix", { n: j.autofixed }));
  return parts.length ? h("div", { class: "job-m" }, parts.join(" ")) : null;
}

const STATUS_ICON = {
  done: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".14"/><path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  running: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4" opacity=".18"/><path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1.1s" repeatCount="indefinite"/></path></svg>',
  queued: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" opacity=".5"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".7"/></svg>',
  error: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="10" fill="currentColor" opacity=".14"/><path d="M12 7v6M12 16.5v.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
  cancelled: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" opacity=".45"/><path d="M8.5 12h7" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".6"/></svg>',
};

function exportLine(j) {
  const x = j.export;
  if (!x || !x.status || x.status === "cancelled") return null;
  if (x.status === "queued") return h("div", { class: "job-x" }, t("x_queued"));
  if (x.status === "running") return h("div", { class: "job-x" }, t("x_running", { pct: Math.floor((x.progress || 0) * 100) }), " ",
    h("button", { class: "link", type: "button", onclick: async () => { S.state = await api("POST", `/api/projects/${j.id}/burn/cancel`); updateJobs(); } }, t("stop")));
  if (x.status === "done") return h("div", { class: "job-x ok" }, t("x_saved"), " ",
    h("button", { class: "link", type: "button", onclick: () => api("POST", "/api/open-folder", { path: x.path }) }, t("show_in_folder")));
  if (x.status === "error") return h("div", { class: "job-x bad" }, t("x_error", { msg: x.message || "" }));
  return null;
}

function jobRow(j) {
  const running = RUNNING.includes(j.status);
  const armed = S.armed && S.armed.id === j.id && S.armed.until > Date.now();
  const removeBtn = h("button", {
    class: "btn small " + (armed ? "danger" : "quiet"), type: "button",
    onclick: async () => {
      if (armed || j.status === "queued" || j.status === "cancelled" || j.status === "error") {
        S.state = await api("DELETE", "/api/jobs/" + j.id); S.armed = null; updateJobs();
      } else { S.armed = { id: j.id, until: Date.now() + 4000 }; updateJobs(); setTimeout(updateJobs, 4100); }
    },
  }, armed ? t("remove_confirm") : t("remove"));
  const actions = [];
  if (j.status === "done") actions.push(h("a", { class: "btn small primary", href: "#/edit/" + j.id }, t("proofread")), removeBtn);
  else if (running) actions.push(h("button", { class: "btn small quiet", type: "button", onclick: async () => { S.state = await api("POST", `/api/jobs/${j.id}/cancel`); updateJobs(); } }, t("stop")));
  else if (j.status === "queued") actions.push(removeBtn);
  else actions.push(h("button", { class: "btn small", type: "button", onclick: async () => { S.state = await api("POST", `/api/jobs/${j.id}/retry`); updateJobs(); } }, t("retry")), removeBtn);
  const meta = [j.duration ? fmtDur(j.duration) : null, t("model_short_" + j.model), j.language === "nn" ? "Nynorsk" : "Bokmål"].filter(Boolean).join(", ");
  return h("li", { class: "job s-" + j.status, "data-id": j.id },
    h("span", { class: "st-ic", "aria-hidden": "true", html: STATUS_ICON[running ? "running" : j.status] || "" }),
    h("div", { class: "job-main" },
      h("div", { class: "job-name" }, j.status === "done" ? h("a", { href: "#/edit/" + j.id }, j.name) : j.name),
      h("div", { class: "job-meta" }, meta),
      h("div", { class: "job-path", title: j.path }, dirname(j.path))),
    h("div", { class: "job-status" },
      h("div", { class: "job-st" }, statusText(j)),
      metricsLine(j),
      exportLine(j),
      running ? h("div", { class: "bar" + (j.status === "loading" ? " indet" : j.status === "downloading" ? "" : " live") }, h("span", { style: `width:${(live(j).p * 100).toFixed(2)}%` })) : null),
    h("div", { class: "job-actions" }, actions));
}

function updateJobs() {
  const list = $("#joblist");
  if (!list || !S.state) return;
  const jobs = S.state.jobs;
  if (!jobs.length) {
    list.replaceChildren(h("li", { class: "empty" }, h("p", null, t("empty_title")), h("p", { class: "muted" }, t("empty_body"))));
  } else {
    const keep = new Map($$(".job", list).map((el) => [el.dataset.id, el]));
    const rows = jobs.map((j) => {
      const sig = JSON.stringify([Math.round((j.work_seconds || 0) / 30), j.edit_rate, j.autofixed, j.export, j.status, j.status === "downloading" ? Math.floor((j.progress || 0) * 200) : 0, j.cues, j.edited, j.message, j.checking && Math.floor((j.check || 0) * 100), j.disagree, LANG, S.armed && S.armed.id === j.id && S.armed.until > Date.now(), S.state.models[j.model]?.ready]);
      const old = keep.get(j.id);
      if (old && old.dataset.sig === sig) return old;
      const row = jobRow(j);
      row.dataset.sig = sig;
      return row;
    });
    if (rows.some((r, i) => list.children[i] !== r) || list.children.length !== rows.length) list.replaceChildren(...rows);
  }
  // queue line
  const q = $("#queueline");
  const cur = jobs.find((j) => RUNNING.includes(j.status)) || jobs.find((j) => j.checking);
  const waiting = jobs.filter((j) => j.status === "queued");
  const waitTime = waiting.reduce((a, j) => a + (jobEstimate(j) || 0), 0)
    + (cur ? (cur.status === "done" ? 0 : live(cur).eta ?? jobEstimate(cur) ?? 0) + checkLeft(cur) : 0);
  const parts = [];
  if (S.state.paused) parts.push(h("span", null, t("q_paused")));
  else if (cur) parts.push(h("span", null, t("q_working", { name: cur.name })), waitTime ? h("span", null, " " + t("q_total", { d: fmtDur(waitTime) })) : null, h("span", { class: "muted" }, " " + t("q_awake")));
  else if (waiting.length) parts.push(h("span", null, t("q_starting")));
  if (cur || waiting.length || S.state.paused) {
    parts.push(h("button", { class: "btn small quiet", type: "button", "data-tip": t("tip_pause"), onclick: async () => { S.state = await api("POST", "/api/queue", { paused: !S.state.paused }); updateJobs(); } },
      S.state.paused ? t("resume") : t("pause")));
  }
  q.replaceChildren(...parts.filter(Boolean));
  q.hidden = !parts.length;
  // average work time per video minute (goal: under 3, and much faster over time)
  const measured = jobs.filter((j) => j.status === "done" && j.work_seconds >= 60 && j.duration);
  const sl = $("#statsline");
  if (measured.length) {
    const ratio = measured.reduce((a, j) => a + j.work_seconds, 0) / measured.reduce((a, j) => a + j.duration, 0);
    sl.replaceChildren(h("strong", { class: ratio < 3 ? "ok" : "bad" }, t("avg_ratio", { r: num(ratio, 1) })), " ",
      h("span", { class: "muted" }, t("avg_detail", { n: measured.length })));
    sl.hidden = false;
  } else sl.hidden = true;
  // batch export
  const bb = $("#batchbar");
  const nDone = jobs.filter((j) => j.status === "done").length;
  bb.hidden = nDone < 1;
  const burnOn = !!S.state.settings.burn_tools;
  if (bb.dataset.burn !== String(burnOn)) { bb.replaceChildren(); bb.dataset.burn = String(burnOn); }
  if (nDone && !bb.childElementCount) {
    bb.append(...[h("span", { class: "muted" }, t("batch_label")),
      h("button", { class: "btn small", type: "button", "data-tip": t("tip_batch_srt"), onclick: async () => {
        const r = await api("POST", "/api/export-all", { kind: "srt" }); S.state = r;
        toast(t(r.count === 1 ? "batch_srt_done_1" : "batch_srt_done", { n: r.count }));
        if (r.failed && r.failed.length) toast(t("batch_srt_failed", { names: r.failed.map((f) => f.name).join(", ") }), null, 12000); } }, t("batch_srt")),
      !burnOn ? null : h("button", { class: "btn small", type: "button", "data-tip": t("tip_batch_burn"), onclick: async () => {
        const r = await api("POST", "/api/export-all", { kind: "burn" }); S.state = r; toast(t("batch_burn_done", { n: r.count })); updateJobs(); } }, t("batch_burn"))].filter(Boolean));
  }
}

// ------------------------------------------------------------- settings ---
function viewSettings() {
  const v = $("#view");
  v.className = "page settings";
  const st = S.state.settings;
  const r = st.rules;
  const numField = (key, label, step, min, max) =>
    h("label", { class: "field num" }, h("span", null, label),
      h("input", { type: "number", name: key, value: r[key], step, min, max, required: true }));
  const form = h("form", { class: "settings-form", onsubmit: async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const rules = {};
    for (const k of ["max_chars", "char_slack", "max_cps", "min_dur", "max_dur"]) rules[k] = Number(f.get(k));
    await saveSettings({ glossary: f.get("glossary"), hotwords: f.get("hotwords") === "on",
      collapse_repeats: f.get("collapse_repeats") === "on", double_check: f.get("double_check") === "on",
      pause_on_type: f.get("pause_on_type") === "on", burn_tools: f.get("burn_tools") === "on",
      auto_update: f.get("auto_update") === "on", rules });
    toast(t("settings_saved"));
  } },
    h("section", null,
      h("h2", null, t("glossary")),
      h("p", { class: "muted" }, t("glossary_help")),
      h("textarea", { name: "glossary", rows: 8, spellcheck: "false", placeholder: t("glossary_ph") }, S.state.glossary),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "hotwords", checked: st.hotwords }), h("span", null, t("hotwords")))),
    h("section", null,
      h("h2", null, t("learned")),
      h("p", { class: "muted" }, t("learned_help")),
      h("div", { id: "learnedlist", class: "learnedlist" }, h("p", { class: "muted" }, t("loading")))),
    h("section", null,
      h("h2", null, t("rules")),
      h("p", { class: "muted" }, t("rules_help")),
      h("div", { class: "num-grid" },
        numField("max_chars", t("r_max_chars"), 1, 20, 60),
        numField("char_slack", t("r_char_slack"), 1, 0, 10),
        numField("max_cps", t("r_max_cps"), 0.5, 8, 30),
        numField("min_dur", t("r_min_dur"), 0.1, 0.3, 3),
        numField("max_dur", t("r_max_dur"), 0.5, 3, 12)),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "collapse_repeats", checked: st.collapse_repeats }), h("span", null, t("collapse_repeats")))),
    h("section", null,
      h("h2", null, t("workflow")),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "double_check", checked: st.double_check }), h("span", null, t("double_check"))),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "pause_on_type", checked: st.pause_on_type }), h("span", null, t("pause_on_type"))),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "burn_tools", checked: st.burn_tools }), h("span", null, t("burn_tools"))),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "auto_update", checked: st.auto_update }), h("span", null, t("auto_update"))),
      h("p", { class: "muted" }, updateLine())),
    h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "submit" }, t("save_settings"))));
  v.replaceChildren(
    h("section", { class: "intro" }, h("h1", null, t("settings_title"))),
    form,
    h("section", { class: "models" },
      h("h2", null, t("models")),
      h("p", { class: "muted" }, t("models_help")),
      h("ul", { id: "modellist", class: "modellist" })),
    h("section", null,
      h("h2", null, t("data_folder")),
      h("p", { class: "muted" }, t("data_help")),
      h("p", { class: "path" }, h("code", null, S.state.data_dir), " ",
        h("button", { class: "btn small quiet", type: "button", onclick: () => api("POST", "/api/open-folder", { path: S.state.data_dir }) }, t("open_folder")))));
  updateModels();
  loadLearned();
}

async function loadLearned() {
  const box = $("#learnedlist");
  if (!box) return;
  let r;
  try { r = await api("GET", "/api/learned"); } catch (_) { return; }
  if (!r.rules.length) { box.replaceChildren(h("p", { class: "muted" }, t("learned_empty"))); return; }
  box.replaceChildren(h("ul", { class: "rules" }, r.rules.map((x) => {
    const sel = h("select", { "aria-label": t("learned_state"), onchange: async (e) => {
      await api("PUT", "/api/learned", { key: x.key, state: e.target.value }); loadLearned(); } },
      ["auto", "on", "off", "delete"].map((s) => h("option", { value: s, selected: x.state === s }, t("rule_" + s))));
    return h("li", null,
      h("div", null, h("span", { class: "rule-a" }, x.a), h("span", { class: "muted" }, "  ➜  "), h("strong", null, x.b)),
      h("div", { class: "rule-meta" },
        h("span", { class: x.active ? "ok" : "muted" }, x.active ? t("rule_active") : t("rule_waiting")),
        h("span", { class: "muted" }, (x.videos === 1 ? t("rule_seen_1") : t("rule_seen", { n: x.videos })) + (x.rejected ? " " + t("rule_rejected", { n: x.rejected }) : "")),
        sel));
  })));
}

function updateModels() {
  const ul = $("#modellist");
  if (!ul) return;
  const busy = !!S.state.current || S.state.jobs.some((j) => RUNNING.includes(j.status) || j.checking);
  ul.replaceChildren(...["large", "medium", "small"].map((n) => {
    const m = S.state.models[n];
    const p = S.dl[n];
    let right;
    if (p != null) right = h("div", { class: "model-dl" }, h("span", null, t("st_downloading_short", { done: fmtGB(p * m.size), total: fmtGB(m.size) })), h("div", { class: "bar" }, h("span", { style: `width:${Math.round(p * 100)}%` })));
    else if (m.ready) right = h("button", { class: "btn small quiet", type: "button", disabled: busy, onclick: async () => {
      if (await ask(t("delete_model_q", { m: t("model_" + n) }), t("delete_model_body"), t("delete_model"), { danger: true })) { S.state = await api("DELETE", "/api/models/" + n); updateModels(); }
    } }, t("delete_model"));
    else right = h("button", { class: "btn small", type: "button", disabled: busy, onclick: async () => { try { await api("POST", `/api/models/${n}/download`); poll(); } catch (e) { toast(e.message); } } }, t("download_now"));
    return h("li", null,
      h("div", null, h("strong", null, t("model_" + n)), h("div", { class: "muted" }, t("model_desc_" + n, { size: fmtGB(m.size), speed: num(m.speed) }))),
      h("div", { class: "model-state" }, h("span", { class: m.ready ? "ok" : "muted" }, m.ready ? t("downloaded") : t("not_downloaded")), right));
  }));
}

// ----------------------------------------------------------------- boot ---
$("#lang-toggle").addEventListener("click", async () => {
  await saveSettings({ ui_lang: LANG === "nb" ? "en" : "nb" });
  applyLang();
});
$("#quit").addEventListener("click", async () => {
  const busy = S.state && S.state.jobs.some((j) => RUNNING.includes(j.status) || j.status === "queued");
  if (!(await ask(t("quit_q"), busy ? t("quit_busy") : t("quit_body"), t("quit"), { danger: busy }))) return;
  if (S.editor) await S.editor.destroy();
  await api("POST", "/api/quit").catch(() => {});
  document.body.replaceChildren(h("main", { class: "page bye" }, h("h1", null, t("bye_title")), h("p", null, t("bye_body"))));
  setTimeout(() => window.close(), 600);  // closes the app window (works in app mode)
  S.stopped = true;
  clearTimeout(S.pollT);
});
window.addEventListener("beforeunload", () => { if (S.editor && S.editor.dirty) S.editor.save(true); });
// Drag videos (or a folder) onto the window. The app window (tekst/launch.py) gets their full paths and adds
// them; a plain browser cannot see where a dropped file lives, so there the button is the way.
const DROP = h("div", { class: "dropzone", hidden: true }, h("div", null, h("strong", { "data-t": "drop_here" }), h("span", { "data-t": "drop_help" })));
document.body.append(DROP);
let dragDepth = 0;
const hasFiles = (e) => [...((e.dataTransfer && e.dataTransfer.types) || [])].includes("Files");
const dropDone = () => { dragDepth = 0; DROP.hidden = true; };
document.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; DROP.hidden = false; } });
document.addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) dropDone(); });
document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dropDone();
  if (!window.pywebview) toast(t("drop_browser"), null, 7000);
});
window.tekstingDropped = (added, skipped) => {
  if (added) toast(t(added === 1 ? "drop_added_1" : "drop_added", { n: added }) + (skipped ? " " + t("drop_skipped", { n: skipped }) : ""));
  else toast(t("drop_none"), null, 7000);
  poll();
};

// The app window calls this before it closes (tekst/launch.py): the last edit, work time and place are saved first.
window.tekstingFlush = async () => {
  const e = S.editor;
  if (!e || !e.alive) return 1;
  await Promise.all([e.dirty ? e.save() : null, e.flushWork(), e.saveResume()]);
  return 1;
};

(async function boot() {
  await poll();
  render();
})();
