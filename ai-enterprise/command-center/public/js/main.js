// Command Center: skal, routing och uppdatering. Snapshoten hämtas var 30:e sekund, GitHub var 60:e,
// och bara de delar vars data ändrats ritas om (varje sida delar sig i "parts" med en egen select()).
import { fetchGithub, fetchMe, fetchSnapshot, postAction, postLogout, setCsrf } from "./api.js";
import { applyWidths, ago, esc, icon, pill, toast } from "./ui.js";
import { enhance, syncLenis } from "./effects.js";
import { confirmKill, confirmAction, confirmRelease } from "./controls.js";
import * as overview from "./pages/overview.js";
import * as agents from "./pages/agents.js";
import * as departments from "./pages/departments.js";
import * as department from "./pages/department.js";
import * as agent from "./pages/agent.js";
import * as approvals from "./pages/approvals.js";
import * as finance from "./pages/finance.js";
import * as risk from "./pages/risk.js";
import * as activity from "./pages/activity.js";
import * as settings from "./pages/settings.js";

export const STALE_HOURS = 26;
const SNAPSHOT_MS = 30_000, GITHUB_MS = 60_000;

const ROUTES = [
  { path: "", page: overview, nav: "Command center", icon: "layout-dashboard" },
  { path: "agents", page: agents, nav: "Agents", icon: "bot" },
  { path: "departments", page: departments, nav: "Departments", icon: "building-2" },
  { path: "department", page: department, param: true },
  { path: "agent", page: agent, param: true },
  { path: "approvals", page: approvals, nav: "Approvals", icon: "circle-check" },
  { path: "finance", page: finance, nav: "Finance", icon: "wallet" },
  { path: "risk", page: risk, nav: "Risk and rules", icon: "shield" },
  { path: "activity", page: activity, nav: "Activity", icon: "activity" },
  { path: "settings", page: settings, nav: "Settings", icon: "settings" },
];

// Delat tillstånd för alla sidor.
export const state = { snapshot: null, snapshotError: null, github: null, githubError: null, me: null, loaded: false };

let current = { route: null, param: null, parts: {}, keys: {}, cleanup: null };

function parseHash() {
  const [, first = "", second = ""] = (location.hash || "#/").split("/");
  const route = ROUTES.find((r) => r.path === first) || ROUTES[0];
  return { route, param: second ? decodeURIComponent(second) : null };
}

function ctx() {
  return { ...state, param: current.param, act: runAction };
}

// Ritar om en del bara när dess data ändrats (jämförs som JSON).
function refreshParts(force = false) {
  const c = ctx();
  for (const [name, part] of Object.entries(current.parts)) {
    const el = document.querySelector(`[data-part="${name}"]`);
    if (!el) continue;
    let key;
    try { key = JSON.stringify(part.select(c)); } catch { key = String(Math.random()); }
    if (!force && current.keys[name] === key) continue;
    current.keys[name] = key;
    try {
      el.innerHTML = part.draw(c);
    } catch (e) {
      console.error(e);
      el.innerHTML = `<div class="error-view" role="alert">This part could not be shown: ${esc(e.message)}</div>`;
    }
    applyWidths(el);
    enhance(el);
    if (part.after) part.after(el, c);
  }
}

function render() {
  const { route, param } = parseHash();
  if (current.cleanup) current.cleanup();
  current = { route, param, parts: {}, keys: {}, cleanup: null };
  const view = route.page.view(ctx());
  const content = document.getElementById("content");
  content.innerHTML = `<div>${view.html}</div>`;  // ingen fade på innehållet: det ska synas även om inga bildrutor körs
  current.parts = view.parts || {};
  current.cleanup = view.cleanup || null;
  if (view.mount) view.mount(content, ctx);
  refreshParts(true);
  renderNav(route);
  closeMenu();
  document.title = `${view.title || "Command center"} · Command center`;
}

function renderNav(active) {
  document.getElementById("nav").innerHTML = ROUTES.filter((r) => r.nav).map((r) =>
    `<a href="#/${r.path}" ${r === active || (active.path === "department" && r.path === "departments") || (active.path === "agent" && r.path === "agents") ? 'aria-current="page"' : ""}>${icon(r.icon)}<span>${esc(r.nav)}</span></a>`).join("");
}

function renderShell() {
  const s = state.snapshot;
  const status = document.getElementById("system-status");
  if (s) {
    const mode = s.system.mode.value;
    const cls = mode === "normal" ? "ok" : "bad";
    const text = mode === "normal" ? "System normal" : mode === "protected" ? "Protected mode" : "Kill switch on";
    status.className = `pill ${cls}`;
    status.innerHTML = `<span class="dot" aria-hidden="true"></span>${esc(text)}`;
    document.getElementById("data-as-of").textContent = `Data as of ${s.generated_at.slice(0, 16).replace("T", " ")} UTC (${ago(s.generated_at)})`;
    document.getElementById("env-label").textContent = s.currency === "SIM" ? "SIM" : "REAL";
    document.getElementById("env-label").className = s.currency === "SIM" ? "pill sim" : "pill bad";
    const list = s.agents.items.slice().sort((a, b) => a.name.localeCompare(b.name));
    document.getElementById("side-agents").innerHTML = list.map((a) =>
      `<a class="side-agent" href="#/agent/${encodeURIComponent(a.id)}"><span class="who"><span class="avatar sm hue-${esc(a.department)}">${esc(a.name.slice(0, 2).toUpperCase())}</span><span>${esc(a.name)}</span></span>${pill(a.status)}</a>`).join("");
  } else if (state.snapshotError) {
    status.className = "pill bad";
    status.innerHTML = '<span class="dot" aria-hidden="true"></span>No data';
    document.getElementById("side-agents").innerHTML = '<div class="muted">N/A</div>';
  }
  const banner = document.getElementById("banner");
  const hours = s ? (Date.now() - Date.parse(s.generated_at)) / 3_600_000 : 0;
  if (state.snapshotError && state.snapshotError.status === 401) {
    banner.innerHTML = `<div class="banner error" role="alert">${icon("lock")}You are not signed in. Reload the page to sign in.</div>`;
  } else if (state.snapshotError && !s) {
    banner.innerHTML = `<div class="banner error" role="alert">${icon("circle-x")}The snapshot could not be loaded: ${esc(state.snapshotError.message)}</div>`;
  } else if (s && hours > STALE_HOURS) {
    banner.innerHTML = `<div class="banner stale" role="status">${icon("triangle-alert")}Data is stale: the latest snapshot is ${Math.floor(hours)} hours old.</div>`;
  } else {
    banner.innerHTML = "";
  }
  const killOn = s && s.system.kill_switch.value;
  document.getElementById("btn-kill").textContent = killOn ? "Release kill switch" : "Kill switch";
  document.getElementById("btn-kill").disabled = !s;
  document.getElementById("btn-pause").disabled = !s || killOn;
}

async function loadSnapshot() {
  try {
    state.snapshot = await fetchSnapshot();
    state.snapshotError = null;
  } catch (e) {
    state.snapshotError = { message: e.message, status: e.status };
  }
  state.loaded = true;
  renderShell();
  refreshParts();
}

async function loadGithub() {
  try {
    state.github = await fetchGithub();
    state.githubError = null;
  } catch (e) {
    state.githubError = { message: e.message, status: e.status };
  }
  refreshParts();
}

async function runAction(body, label) {
  try {
    const res = await postAction(body);
    toast(res.applied ? `${label}: applied through the core and logged.` : `${label}: queued (${res.id}). The engine applies it in the next control run.`);
    if (res.applied) loadSnapshot();
    return res;
  } catch (e) {
    toast(`${label} failed: ${e.message}`);
    throw e;
  }
}

function closeMenu() {
  document.getElementById("shell").classList.remove("menu-open");
  document.getElementById("menu-btn").setAttribute("aria-expanded", "false");
}

function tick() {
  const d = new Date();
  document.getElementById("clock").textContent = `${d.toISOString().slice(11, 16)} UTC`;
}

function boot() {
  document.getElementById("menu-btn").addEventListener("click", () => {
    const open = document.getElementById("shell").classList.toggle("menu-open");
    document.getElementById("menu-btn").setAttribute("aria-expanded", String(open));
  });
  document.getElementById("scrim").addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  document.getElementById("btn-pause").addEventListener("click", () =>
    confirmAction("Pause all agents", "All active agents are paused through the core. Nothing is deleted, and you can resume each agent.",
      () => runAction({ type: "pause_all" }, "Pause agents")));
  document.getElementById("btn-kill").addEventListener("click", () => {
    if (state.snapshot && state.snapshot.system.kill_switch.value) {
      confirmRelease((note) => runAction({ type: "kill_release", confirm: "RELEASE", note }, "Release kill switch"));
    } else {
      confirmKill(() => runAction({ type: "kill", confirm: "KILL" }, "Kill switch"));
    }
  });
  document.getElementById("btn-logout").addEventListener("click", async () => {
    try { await postLogout(); } finally { location.href = "/login"; }
  });
  window.addEventListener("hashchange", render);
  fetchMe().then((me) => { state.me = me; setCsrf(me.csrf); document.getElementById("founder").textContent = me.founder || ""; }).catch(() => {});
  tick();
  setInterval(tick, 15_000);
  render();
  loadSnapshot();
  loadGithub();
  setInterval(loadSnapshot, SNAPSHOT_MS);
  setInterval(loadGithub, GITHUB_MS);
  if (document.readyState === "complete") syncLenis(); else window.addEventListener("load", syncLenis);
}

boot();
