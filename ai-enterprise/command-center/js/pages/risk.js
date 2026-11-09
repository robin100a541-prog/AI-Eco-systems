// Risk and rules: läge, kontrollkedjans steg med dagens blockeringar, gränser med användning och incidenter.
import { NA, esc, money, table, emptyView, bar, icon, num } from "../ui.js";
import { guard, head } from "./common.js";

const CHAIN = [
  ["Authorization", "tool.denied", "Role mandate, default deny (SR-02)"],
  ["Budget", "budget.blocked", "Budget engine and limits (ER-03)"],
  ["Ledger", "ledger.duplicate_refused", "Duplicates refused (ER-07)"],
  ["Stop-loss", null, "Stops an initiative at MAX_SINGLE_EXPERIMENT_LOSS"],
  ["Protected mode", null, "Stops spending and external tools"],
  ["Kill switch", null, "Stops all agents; nothing is deleted"],
];

function mode(s) {
  const sys = s.system;
  const m = sys.mode.value;
  return `<div class="row"><span class="pill ${m === "normal" ? "ok" : "bad"}"><span class="dot"></span>${esc(m === "normal" ? "Normal" : m === "protected" ? "Protected mode" : "Kill switch on")}</span>
    <span class="muted">Kill switch ${sys.kill_switch.value ? "on" : "off"} · protected mode ${sys.protected_mode.value ? "on" : "off"}</span></div>`;
}

function chain(s) {
  const counts = {};
  for (const b of s.blocks_today.items) counts[b.step] = (counts[b.step] || 0) + b.count;
  return `<ol class="feed">${CHAIN.map(([name, action, what]) => {
    const n = action ? counts[action] || 0 : null;
    return `<li><span class="src ${n ? "error" : ""}">${icon(n ? "octagon-x" : "shield-check", "sm")}</span><span class="what"><b>${esc(name)}</b><br><span class="muted">${esc(what)}</span></span>
      <span class="when">${n === null ? "N/A today" : `${num(n)} blocked today`}</span></li>`;
  }).join("")}</ol>`;
}

function limits(s) {
  return table([{ label: "Limit", html: (r) => `<span class="mono">${esc(r.name)}</span>` },
    { label: "Value", right: true, html: (r) => (r.limit === null ? NA : typeof r.limit === "number" ? money(r.limit, s.currency) : `<span class="mono">${esc(r.limit)}</span>`) },
    { label: "Used", right: true, html: (r) => (r.used === null || r.used === undefined ? NA : money(r.used, s.currency)) },
    { label: "", html: (r) => (typeof r.limit === "number" && typeof r.used === "number" && r.limit > 0 ? bar(r.used / r.limit, r.used > r.limit ? "bad" : r.used > 0.8 * r.limit ? "warn" : "") : "") }],
  s.risk_limits.items) + '<p class="muted">Limits are shown here and never changed here. They change only in config/risk_limits.toml with both founders (D-019).</p>';
}

function incidents(s) {
  return table([{ label: "ID", html: (r) => `<span class="mono">${esc(r.id)}</span>` }, { key: "title", label: "Incident" }, { key: "source", label: "Source" }, { key: "by", label: "Reported by" }, { key: "at", label: "Opened" }],
    s.incidents.items, { empty: "No incidents recorded." });
}

export function view() {
  return {
    title: "Risk and rules",
    html: `${head("Control", "Risk and rules.")}<div class="grid g-12">
      <div class="span-12"><section class="panel"><div class="panel-head"><h2>Mode</h2></div><div data-part="mode"></div></section></div>
      <div class="span-5"><section class="panel"><div class="panel-head"><h2>Control chain today</h2></div><div data-part="chain"></div></section></div>
      <div class="span-7"><section class="panel"><div class="panel-head"><h2>Limits and usage</h2></div><div data-part="limits"></div></section></div>
      <div class="span-12"><section class="panel"><div class="panel-head"><h2>Incidents</h2></div><div data-part="incidents"></div></section></div></div>`,
    parts: {
      mode: { select: (c) => c.snapshot && c.snapshot.system, draw: (c) => guard(c, mode, 1) },
      chain: { select: (c) => c.snapshot && c.snapshot.blocks_today, draw: (c) => guard(c, chain, 6) },
      limits: { select: (c) => c.snapshot && c.snapshot.risk_limits, draw: (c) => guard(c, limits, 8) },
      incidents: { select: (c) => c.snapshot && c.snapshot.incidents, draw: (c) => guard(c, incidents) },
    },
  };
}
