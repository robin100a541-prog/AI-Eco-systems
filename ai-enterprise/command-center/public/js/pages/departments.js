// Departments: ett kort per departement i config, ritat som en byggnad där tända fönster är aktiva agenter.
import { deptBadge, deptName, esc, hue, pill, emptyView } from "../ui.js";
import { guard, head } from "./common.js";

export function building(dept, agents) {
  const cols = 4, rows = Math.max(2, Math.ceil(Math.max(agents.length, 1) / cols));
  const w = 200, floorH = 30, h = rows * floorH + 46;
  let wins = "";
  for (let i = 0; i < rows * cols; i++) {
    const a = agents[i];
    const x = 22 + (i % cols) * 42, y = 30 + Math.floor(i / cols) * floorH;
    wins += `<rect class="win ${a && a.status === "working" ? "lit" : ""}" x="${x}" y="${y}" width="30" height="18" rx="3">${a ? `<title>${esc(a.name)}: ${esc(a.status)}</title>` : ""}</rect>`;
  }
  return `<svg class="building ${hue(dept)}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(deptName(dept))}: ${agents.filter((a) => a.status === "working").length} of ${agents.length} agents working">
    <rect class="facade" x="10" y="14" width="${w - 20}" height="${h - 14}" rx="6"/>${wins}
    <rect class="win" x="${w / 2 - 14}" y="${h - 24}" width="28" height="24" rx="3"/></svg>`;
}

function cards(s) {
  const deps = s.departments.items;
  if (!deps.length) return emptyView("No departments in config.");
  const byId = Object.fromEntries(s.agents.items.map((a) => [a.id, a]));
  return `<div class="grid g-3">${deps.map((d) => {
    const agents = d.agents.map((id) => byId[id]).filter(Boolean);
    const working = agents.filter((a) => a.status === "working").length;
    return `<a class="card ${hue(d.id)}" href="#/department/${encodeURIComponent(d.id)}" data-spotlight>
      <div class="row between"><span class="row">${deptBadge(d.id)}<h3>${esc(deptName(d.id))}</h3></span><span class="mono muted">${agents.length} agents</span></div>
      ${building(d.id, agents)}
      <div class="row">${working ? pill("working", `${working} working`) : pill("idle", "None working")}<span class="mono muted">roles: ${esc(d.roles.join(", ") || "none")}</span></div></a>`;
  }).join("")}</div>`;
}

export function view() {
  return {
    title: "Departments",
    html: `${head("Organization", "Departments.")}<div data-part="cards"></div>`,
    parts: { cards: { select: (c) => c.snapshot && [c.snapshot.departments, c.snapshot.agents.items.map((a) => [a.id, a.status])], draw: (c) => guard(c, cards, 6) } },
  };
}
