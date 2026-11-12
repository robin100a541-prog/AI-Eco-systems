// Settings: notiskanaler, grundare och godkännanderegler, modeller och åtkomst. Gränserna visas, ändras aldrig här.
import { NA, esc, money, table, num, icon } from "../ui.js";
import { guard, head } from "./common.js";

function notifications(s) {
  const n = s.notifications || null;
  const row = (name, on, what) => `<li><span class="src">${icon(name === "ntfy" ? "bell" : "mail", "sm")}</span><span class="what"><b>${esc(name)}</b><br><span class="muted">${esc(what)}</span></span>
    <span class="when">${on === null || on === undefined ? "N/A" : on ? "configured" : "not configured"}</span></li>`;
  return `<ul class="feed">${row("ntfy", n && n.ntfy, "Push to phone with generic text only, never amounts or names")}
    ${row("Gmail", n && n.email, "Daily summary at 21:00 and alerts")}</ul>
    <p class="muted">Channels are switched on or off by setting or removing their GitHub secrets (DEPLOY.md). A missing secret skips the channel without errors.</p>`;
}

function founders(s) {
  const r = s.rules || {};
  return `<dl class="kv"><dt>Founders</dt><dd>${(r.founders || []).map(esc).join(", ") || NA}</dd>
    <dt>Approval threshold</dt><dd>${r.approval_threshold === undefined || r.approval_threshold === null ? NA : money(r.approval_threshold, s.currency)} (HUMAN_APPROVAL_THRESHOLD)</dd>
    <dt>While simulated</dt><dd>One founder is enough for every decision (D-049, D-081).</dd>
    <dt>Before phase 7</dt><dd>Both founders for real money, limits, new channels and agent disagreements (D-081).</dd>
    <dt>Buttons</dt><dd>Never change anything directly; they queue a decision that the engine applies (D-089).</dd></dl>`;
}

function models(s) {
  return table([{ label: "Provider", html: (q) => `<span class="mono">${esc(q.provider)}</span>` }, { label: "Calls today", right: true, html: (q) => `${num(q.calls)} / ${num(q.calls_limit)}` },
    { label: "Tokens today", right: true, html: (q) => `${num(q.tokens)} / ${num(q.tokens_limit)}` }], s.quotas.items, { empty: "No providers in config/providers.toml." });
}

function access(c) {
  return `<dl class="kv"><dt>Signed in as</dt><dd>${esc((c.me && c.me.founder) || "N/A")}</dd>
    <dt>Protection</dt><dd>${c.me && c.me.mode === "local" ? "Local server: access code per founder (D1)" : "Own sign-in: one access code per founder, stored only as a hash; session for 12 hours (D-094)"}</dd>
    <dt>Sign-up</dt><dd>Not possible. Only the two founders can sign in.</dd></dl>`;
}

export function view() {
  return {
    title: "Settings",
    html: `${head("System", "Settings.")}<div class="grid g-2">
      <section class="panel"><div class="panel-head"><h2>Notification channels</h2></div><div data-part="notify"></div></section>
      <section class="panel"><div class="panel-head"><h2>Founders and approval rules</h2></div><div data-part="founders"></div></section>
      <section class="panel"><div class="panel-head"><h2>Models and quotas</h2></div><div data-part="models"></div></section>
      <section class="panel"><div class="panel-head"><h2>Access</h2></div><div data-part="access"></div></section></div>
      <p class="muted">Risk limits are shown on Risk and rules and never changed in the command center.</p>`,
    parts: {
      notify: { select: (c) => c.snapshot && c.snapshot.notifications, draw: (c) => guard(c, notifications) },
      founders: { select: (c) => c.snapshot && c.snapshot.rules, draw: (c) => guard(c, founders) },
      models: { select: (c) => c.snapshot && c.snapshot.quotas, draw: (c) => guard(c, models) },
      access: { select: (c) => c.me, draw: (c) => access(c) },
    },
  };
}
