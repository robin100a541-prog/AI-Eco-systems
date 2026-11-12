// Gemensamma komponenter. Varje komponent byggs en gång här och återanvänds på alla sidor (DESIGN.md).
// All text går genom esc(); inga inline-stilar (CSP style-src 'self'): bredder sätts via applyWidths().

export const SPRITE = "/assets/icons/lucide-sprite.svg";

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function icon(name, cls = "") {
  return `<svg class="icon ${cls}" aria-hidden="true"><use href="${SPRITE}#i-${esc(name)}"></use></svg>`;
}

export const NA = '<span class="na">N/A</span>';

// Pengar i minor units -> "1 234.56 SIM". null blir N/A, aldrig 0.
export function money(minor, currency = "SIM", { sign = false } = {}) {
  if (minor === null || minor === undefined || Number.isNaN(minor)) return NA;
  const v = Number(minor) / 100;
  const s = Math.abs(v).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const prefix = v < 0 ? "−" : sign && v > 0 ? "+" : "";
  return `<span class="num">${prefix}${s} ${esc(currency)}</span>`;
}

export function num(value, digits = 0) {
  if (value === null || value === undefined) return NA;
  return `<span class="num">${Number(value).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }).replace(/,/g, " ")}</span>`;
}

export function pct(value) {
  if (value === null || value === undefined) return NA;
  return `<span class="num">${(value * 100).toFixed(1)} %</span>`;
}

export function when(iso) {
  if (!iso) return NA;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  return `<time class="mono" datetime="${esc(d.toISOString())}" title="${esc(d.toISOString())}">${esc(d.toISOString().slice(0, 16).replace("T", " "))} UTC</time>`;
}

export function ago(iso, now = Date.now()) {
  if (!iso) return "N/A";
  const s = Math.round((now - Date.parse(iso)) / 1000);
  if (!Number.isFinite(s)) return "N/A";
  if (s < 60) return `${Math.max(s, 0)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

const STATUS_TEXT = { working: "Working", waiting: "Waiting", idle: "Idle", blocked: "Blocked", failed: "Failed", offline: "Offline" };

// Statuspill: alltid prick och text. Okänd status visas inte (DATA.md: "unknown").
export function pill(status, text) {
  if (!STATUS_TEXT[status] && !text) return "";
  return `<span class="pill ${esc(status)}"><span class="dot" aria-hidden="true"></span>${esc(text || STATUS_TEXT[status])}</span>`;
}

const DEPT_ICON = { executive: "crown", research: "flask-conical", finance: "landmark", risk: "shield", compliance: "scale", audit: "file-search" };
const DEPT_NAME = { executive: "Executive", research: "Research", finance: "Finance", risk: "Risk", compliance: "Compliance", audit: "Audit" };
export const deptName = (id) => DEPT_NAME[id] || String(id || "Unknown").replace(/^./, (c) => c.toUpperCase());
export const deptIcon = (id) => DEPT_ICON[id] || "building";
export const hue = (dept) => `hue-${["executive", "research", "finance", "risk", "compliance", "audit", "sales", "engineering"].includes(dept) ? dept : "other"}`;

export function avatar(agent, size = "") {
  const initials = (agent.name || agent.id || "?").slice(0, 2).toUpperCase();
  return `<span class="avatar ${size} ${hue(agent.department)}" aria-hidden="true">${esc(initials)}</span>`;
}

export function deptBadge(dept, size = "") {
  return `<span class="avatar ${size} ${hue(dept)}" aria-hidden="true">${icon(deptIcon(dept), "sm")}</span>`;
}

export function value(metric, fmt = (v) => esc(v)) {
  if (!metric || metric.value === null || metric.value === undefined) return NA;
  return fmt(metric.value);
}

export function metricCard(label, html, { sub = "", source = "" } = {}) {
  return `<div class="card metric" ${source ? `title="Source: ${esc(source)}"` : ""}>
    <div class="label">${esc(label)}</div><div class="value">${html}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

export function panel(title, body, { label = "", actions = "", id = "" } = {}) {
  return `<section class="panel" ${id ? `id="${esc(id)}"` : ""}>
    <div class="panel-head"><div>${label ? `<div class="label">${esc(label)}</div>` : ""}<h2>${esc(title)}</h2></div>${actions}</div>${body}</section>`;
}

export function skeleton(lines = 3, big = false) {
  return `<div aria-busy="true" aria-label="Loading">${big ? '<div class="skeleton sk-big"></div>' : ""}${'<div class="skeleton sk-line"></div>'.repeat(lines)}</div>`;
}

export function emptyView(text, hint = "") {
  return `<div class="empty">${icon("inbox")}<div>${esc(text)}</div>${hint ? `<div class="muted">${esc(hint)}</div>` : ""}</div>`;
}

export function errorView(text) {
  return `<div class="error-view" role="alert">${icon("circle-x")}<div>${esc(text)}</div></div>`;
}

// Tabell: cols = [{ key, label, right, html: (row) => string }]
export function table(cols, rows, { empty = "Nothing here yet." } = {}) {
  if (!rows || rows.length === 0) return emptyView(empty);
  const head = cols.map((c) => `<th class="${c.right ? "r" : ""}" scope="col">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.right ? "r" : ""}">${c.html ? c.html(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// Segmenterad framstegsstapel. progress null -> alla segment tomma och "N/A" (framsteg registreras inte).
export function segments(progress) {
  const on = progress === null || progress === undefined ? 0 : Math.round(Math.max(0, Math.min(1, progress)) * 10);
  return `<div class="segments" role="img" aria-label="${progress === null || progress === undefined ? "Progress not tracked" : `${on * 10} %`}">${Array.from({ length: 10 }, (_, i) => `<span class="${i < on ? "on" : ""}"></span>`).join("")}</div>`;
}

// En stapel med bredd satt via JS (CSP tillåter inte style-attribut).
export function bar(fraction, cls = "") {
  const f = fraction === null || fraction === undefined || !Number.isFinite(fraction) ? 0 : Math.max(0, Math.min(1, fraction));
  return `<div class="bar ${esc(cls)}"><span data-w="${(f * 100).toFixed(2)}"></span></div>`;
}

export function applyWidths(root) {
  root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
}

export function toast(text, ms = 5000) {
  const root = document.getElementById("toast-root");
  if (!root) return;
  root.innerHTML = `<div class="toast fade-in" role="status">${esc(text)}</div>`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { root.innerHTML = ""; }, ms);
}

export function agentLink(id, label) {
  return `<a href="#/agent/${encodeURIComponent(id)}">${esc(label || id)}</a>`;
}
