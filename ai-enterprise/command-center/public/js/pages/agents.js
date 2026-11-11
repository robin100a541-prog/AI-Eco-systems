// Agents: nätverksträd med CEO överst, departementschefer och kontrollfunktioner under, och deras agenter längst ner.
// Linjerna följer `manager` i registret. Kontrollfunktionerna lyder inte under CEO (§8) och ritas streckade
// till toppen med texten "reports to founders".
import { NA, avatar, esc, money, pct, pill, when, emptyView, ago } from "../ui.js";
import { guard, head } from "./common.js";

export function agentCard(a, per) {
  const p = per[a.id];
  return `<article class="card agent-card ${esc(`hue-${a.department}`)}" data-spotlight data-node="${esc(a.id)}">
    <div class="head">${avatar(a)}<div class="stack tight">
      <a href="#/agent/${encodeURIComponent(a.id)}"><h3>${esc(a.name)}</h3></a><span class="mono muted">${esc(a.role)} · ${esc(a.id)}</span></div></div>
    <p class="muted">${esc(a.description || "No description in permissions.toml.")}</p>
    <div class="row">${pill(a.status)}<span class="mono muted">${esc(a.model || "model N/A")}</span></div>
    <div class="facts"><div><span class="label">Last run</span>${a.last_run ? esc(ago(a.last_run)) : NA}</div>
      <div><span class="label">Success</span>${pct(a.success_rate)}</div><div><span class="label">Runs</span>${esc(a.runs)}</div>
      <div><span class="label">Revenue</span>${p ? money(p.revenue) : NA}</div><div><span class="label">Cost</span>${p ? money(p.cost) : NA}</div>
      <div><span class="label">Profit</span>${p ? money(p.net) : NA}</div></div></article>`;
}

function tree(s) {
  const agents = s.agents.items;
  if (!agents.length) return emptyView("No agents are registered yet.");
  const per = Object.fromEntries(s.per_agent.items.map((r) => [r.agent, r]));
  const ceo = agents.find((a) => a.role === "ceo");
  const heads = agents.filter((a) => a !== ceo && (a.manager === (ceo && ceo.id) || (a.manager === null && a.level === 2)));
  const rest = agents.filter((a) => a !== ceo && !heads.includes(a));
  return `<div class="tree" data-tree>
    <svg class="links" aria-hidden="true"></svg>
    ${ceo ? `<div class="tree-row top">${agentCard(ceo, per)}</div>` : ""}
    <div class="tree-row">${heads.map((a) => agentCard(a, per)).join("")}</div>
    ${rest.length ? `<div class="tree-row">${rest.map((a) => agentCard(a, per)).join("")}</div>` : ""}
    <p class="muted"><span class="mono">— —</span> Control functions (CFO, CRO, Compliance, Audit) report to the founders, not to the CEO (§8).</p></div>`;
}

// Linjer från chef till underställd, ritade efter att korten har placerats.
function drawLinks(root, s) {
  const t = root.querySelector("[data-tree]");
  if (!t) return;
  const svg = t.querySelector("svg.links");
  const box = t.getBoundingClientRect();
  const ceo = s.agents.items.find((a) => a.role === "ceo");
  const pos = (id) => {
    const el = t.querySelector(`[data-node="${CSS.escape(id)}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left - box.left + r.width / 2, top: r.top - box.top, bottom: r.bottom - box.top };
  };
  const paths = [];
  for (const a of s.agents.items) {
    if (a === ceo) continue;
    const from = a.manager ? pos(a.manager) : (ceo && a.level === 2 ? pos(ceo.id) : null);
    const to = pos(a.id);
    if (!from || !to) continue;
    const mid = (from.bottom + to.top) / 2;
    paths.push(`<path class="${a.manager ? "" : "dashed"}" d="M${from.x},${from.bottom} V${mid} H${to.x} V${to.top}"/>`);
  }
  svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  svg.innerHTML = paths.join("");
}

export function view() {
  let onResize = null;
  return {
    title: "Agents",
    html: `${head("Organization", "Agents.")}<div data-part="tree"></div>`,
    parts: {
      tree: {
        select: (c) => c.snapshot && [c.snapshot.agents.items, c.snapshot.per_agent],
        draw: (c) => guard(c, tree, 8),
        after: (el, c) => {
          if (!c.snapshot) return;
          const redraw = () => drawLinks(el, c.snapshot);
          requestAnimationFrame(redraw);
          window.removeEventListener("resize", onResize);
          onResize = redraw;
          window.addEventListener("resize", onResize);
        },
      },
    },
    cleanup: () => window.removeEventListener("resize", onResize),
  };
}
