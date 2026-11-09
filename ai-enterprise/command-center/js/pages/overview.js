// Command center (översikt): nyckeltal, radar, direktiv, kontextfönster, statsrad, diagram, hälsa och live-flöde.
import { NA, esc, icon, metricCard, money, num, panel, pct, pill, segments, value, emptyView, errorView, bar, ago, agentLink } from "../ui.js";
import { lineChart, barsChart } from "../charts.js";
import { radarSvg, animateRadar } from "../radar.js";
import { guard, head, part, mergedEvents, feedItem } from "./common.js";
import { listAdd, reduced } from "../effects.js";

const counted = (minor, cur) => (minor === null || minor === undefined ? NA
  : `<span data-count="${(minor / 100).toFixed(2)}" data-decimals="2" data-suffix=" ${esc(cur)}">${money(minor, cur).replace(/<[^>]+>/g, "")}</span>`);

function metrics(s) {
  const e = s.economy, cur = s.currency, ag = s.agents.items;
  const runs = ag.reduce((n, a) => n + a.runs, 0);
  const done = ag.reduce((n, a) => n + a.actions_done, 0), failed = ag.reduce((n, a) => n + a.actions_failed, 0);
  const active = ag.filter((a) => a.lifecycle === "active").length;
  const cards = [
    ["Total revenue", value(e.revenue_gross, (v) => counted(v, cur)), "gross, settled", e.revenue_gross?.source],
    ["Total costs", value(e.costs, (v) => counted(v + (e.platform_fees?.value || 0) + (e.refunds?.value || 0), cur)), "costs, fees and refunds", e.costs?.source],
    ["Net profit", value(e.net_profit_realized, (v) => counted(v, cur)), e.preliminary?.value?.length ? "Preliminary" : "realized, before tax", e.net_profit_realized?.source],
    ["Available capital", value(e.disposable_capital, (v) => counted(v, cur)), "after reserve and commitments", e.disposable_capital?.source],
    ["Tax reserve", value(e.tax_reserve, (v) => counted(v, cur)), "reserved, not available", e.tax_reserve?.source],
    ["Protected reserve", value(e.protected_reserve, (v) => counted(v, cur)), "MINIMUM_RESERVE", e.protected_reserve?.source],
    ["Active agents", `<span data-count="${active}">${active}</span>`, `of ${ag.length} registered`, "AgentRegistry"],
    ["Total runs", `<span data-count="${runs}">${runs}</span>`, "model calls by agents", "audit_log: llm.call"],
    ["Success rate", done + failed ? pct(done / (done + failed)) : NA, `${done} done of ${done + failed} actions`, "audit_log: simulation.action"],
    ["Failed runs", `<span data-count="${failed}">${failed}</span>`, "failed actions and denials", "audit_log"],
  ];
  return `<div class="metrics">${cards.map(([l, v, sub, src]) => metricCard(l, v, { sub: esc(sub), source: src })).join("")}</div>`;
}

function directive(s) {
  const ceo = s.agents.items.find((a) => a.role === "ceo");
  const decision = s.events.items.find((e) => e.actor === (ceo && ceo.id) && /decision|task\.(create|assign)/.test(e.action));
  const task = s.tasks.items.find((t) => ceo && t.owner && s.agents.items.find((a) => a.id === t.owner && a.manager === ceo.id));
  if (!ceo) return emptyView("No CEO agent is registered.");
  if (!decision && !task) return emptyView("The CEO has no recorded decision yet.", "Decisions appear here when the CEO records one in the core.");
  return `<div class="stack"><div class="row">${pill(ceo.status)}<span class="mono muted">${esc(ceo.name)} · ceo</span></div>
    ${task ? `<h3>${esc(task.title)}</h3><p class="muted">Assigned to ${agentLink(task.owner)} · task #${esc(task.id)} · ${esc(task.status)}</p>` : ""}
    ${decision ? `<p class="muted mono">${esc(decision.action)} · ${esc(decision.at.slice(0, 16).replace("T", " "))}</p>` : ""}</div>`;
}

function contextWindow(s) {
  const ranked = s.agents.items.filter((a) => a.last_run).sort((a, b) => b.last_run.localeCompare(a.last_run));
  const a = s.agents.items.find((x) => x.status === "working") || ranked[0];
  if (!a) return emptyView("No agent has run yet.");
  return `<div class="stack"><div class="row between"><span class="row">${agentLink(a.id, a.name)}<span class="mono muted">${esc(a.role)}</span></span>${pill(a.status)}</div>
    <div><div class="label">Task</div><p>${a.task ? esc(a.task.title) : '<span class="muted">No open task</span>'}</p></div>
    <div><div class="row between"><span class="label">Progress</span><span class="muted mono">${a.progress === null ? "N/A (not tracked)" : `${Math.round(a.progress * 100)} %`}</span></div>${segments(a.progress)}</div>
    <div class="muted mono">Last run ${a.last_run ? esc(ago(a.last_run)) : "N/A"} · ${esc(a.model || "model N/A")}</div></div>`;
}

function statsline(s) {
  const ag = s.agents.items;
  const tokens = s.quotas.items.reduce((n, q) => n + (q.tokens || 0), 0);
  const errors = s.events.items.filter((e) => e.type === "error").length;
  const chain = s.audit_chain;
  return `<div class="statsline" role="group" aria-label="System statistics">
    <span>integrity <b class="${chain.ok ? "" : "bad"}">${chain.ok ? "verified" : `BROKEN at ${chain.first_bad_seq}`}</b> (${num(chain.length)} entries)</span>
    <span>agent calls <b>${num(ag.reduce((n, a) => n + a.runs, 0))}</b></span>
    <span>messages <b>N/A</b></span>
    <span>tokens today <b>${num(tokens)}</b></span>
    <span>errors <b>${num(errors)}</b></span></div>`;
}

function charts(s) {
  const days = s.periods.day.items;
  const per = s.per_agent.items.map((r) => ({ label: r.agent, a: r.revenue, b: r.cost }));
  return `<div class="grid g-12">
    <div class="span-7">${panel("Revenue and profit over time", days.length ? `${lineChart(days.map((d) => d.period), [
      { name: "Revenue", cls: "s-revenue", values: days.map((d) => d.revenue), area: true },
      { name: "Net profit", cls: "s-profit", values: days.map((d) => d.net) }])}
      <div class="legend"><span><i class="legend-rev"></i>Revenue</span><span><i class="legend-net"></i>Net profit</span><span class="mono">${esc(s.currency)} per day</span></div>` : emptyView("No settled transactions yet."), { label: "Finance" })}</div>
    <div class="span-5">${panel("Revenue per agent", per.length ? `${barsChart(per)}<p class="muted">Per booking actor (ledger recorded_by). In SIM, sales are booked by system:simulation.</p>` : emptyView("No revenue recorded yet."), { label: "Finance" })}</div></div>`;
}

function health(s, g) {
  const groq = s.quotas.items.find((q) => q.provider === "groq");
  const minutes = g && g.actions_month ? g.actions_month.minutes_estimate : null;
  return `<dl class="kv">
    <dt>Actions minutes</dt><dd>${minutes === null || minutes === undefined ? NA : `${num(minutes)} of 2 000 (est.)`}${minutes !== null && minutes !== undefined ? bar(minutes / 2000, minutes > 1400 ? "warn" : "") : ""}</dd>
    <dt>Groq quota</dt><dd>${groq ? `${num(groq.tokens)} of ${num(groq.tokens_limit)} tokens (${esc(groq.day || "today")})` : NA}${groq && groq.tokens_limit ? bar(groq.tokens / groq.tokens_limit) : ""}</dd>
    <dt>Last run</dt><dd>${s.system.last_run.value ? `${esc(ago(s.system.last_run.value))} (day ${esc(s.system.last_run_day.value)})` : NA}</dd>
    <dt>Database size</dt><dd>${value(s.system.database_bytes, (v) => `${(v / 1024).toFixed(0)} KB`)}</dd>
    <dt>Version</dt><dd class="mono">${value(s.system.version)}</dd></dl>`;
}

export function view() {
  return {
    title: "Command center",
    html: `${head("Overview", "Command center.")}
      <div data-part="metrics"></div><div data-part="stats"></div>
      <div class="grid g-12">
        <div class="span-5">${panel("Agent radar", '<div data-part="radar"></div>', { label: "Departments" })}</div>
        <div class="span-7 stack">${panel("Current directive", '<div data-part="directive"></div>', { label: "CEO" })}
          ${panel("Context window", '<div data-part="context"></div>', { label: "Active agent" })}</div>
        <div class="span-12" data-part="charts"></div>
        <div class="span-4 stack">${panel("System health", '<div data-part="health"></div>', { label: "System" })}
          ${panel("Chat with an agent", '<div data-part="chat"></div>', { label: "Agents" })}</div>
        <div class="span-8">${panel("Live activity", '<ul class="feed" data-part="feed"></ul>', { label: "Audit and GitHub" })}</div>
      </div>`,
    parts: {
      metrics: { select: (c) => c.snapshot && [c.snapshot.economy, c.snapshot.agents.items.map((a) => [a.lifecycle, a.runs, a.actions_done, a.actions_failed])], draw: (c) => guard(c, metrics, 2) },
      stats: { select: (c) => c.snapshot && [c.snapshot.audit_chain, c.snapshot.quotas, c.snapshot.events.items.length], draw: (c) => guard(c, statsline, 1) },
      radar: {
        select: (c) => c.snapshot && c.snapshot.agents.items.map((a) => [a.id, a.status, a.department]),
        draw: (c) => guard(c, (s) => `${radarSvg(s.agents.items, s.departments.items)}<div class="row">${pill("working")}<span class="muted">pulses</span>${pill("idle")}${pill("waiting")}</div>`, 6),
        after: (el) => animateRadar(el.querySelector("svg")),
      },
      directive: { select: (c) => c.snapshot && [c.snapshot.tasks, c.snapshot.events.items.slice(0, 50).map((e) => e.id)], draw: (c) => guard(c, directive) },
      context: { select: (c) => c.snapshot && c.snapshot.agents.items.map((a) => [a.id, a.status, a.task, a.last_run]), draw: (c) => guard(c, contextWindow) },
      charts: { select: (c) => c.snapshot && [c.snapshot.periods.day, c.snapshot.per_agent], draw: (c) => guard(c, charts, 6) },
      health: { select: (c) => c.snapshot && [c.snapshot.quotas, c.snapshot.system, c.github && c.github.actions_month], draw: (c) => guard(c, (s) => health(s, c.github)) },
      chat: {
        select: (c) => c.snapshot && c.snapshot.agents.items.map((a) => a.id),
        draw: (c) => guard(c, (s) => `<p class="muted">Ask an agent to explain its work. Chat can explain, never act.</p>
          <div class="row">${s.agents.items.slice(0, 7).map((a) => `<a class="btn sm" href="#/agent/${encodeURIComponent(a.id)}?chat">${icon("message-square", "sm")}${esc(a.name)}</a>`).join("")}</div>`),
      },
      feed: {
        select: (c) => mergedEvents(c, 30).map((e) => e.id),
        draw: (c) => {
          if (!c.snapshot && !c.github) return c.snapshotError ? errorView(c.snapshotError.message) : '<li><div class="skeleton sk-line"></div></li>';
          const items = mergedEvents(c, 30);
          return items.length ? items.map(feedItem).join("") : `<li>${emptyView("No activity yet.")}</li>`;
        },
        after: (el) => {
          // Nya rader (som inte fanns förra gången) tonar in högst upp.
          const ids = [...el.children].map((li) => li.dataset.id);
          const before = new Set(el._seen || []);
          if (el._seen && !reduced()) [...el.children].filter((li) => !before.has(li.dataset.id)).reverse().forEach((li) => listAdd(el, li));
          el._seen = ids;
        },
      },
    },
  };
}
