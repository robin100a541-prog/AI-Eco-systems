// Department (huset): planritning med ett glasrum per agent, mötesrum (samråd), arkiv (lärdomar) och uppgiftskö.
import { avatar, deptBadge, deptName, esc, hue, pill, segments, table, emptyView, agentLink, icon } from "../ui.js";
import { guard, head } from "./common.js";

function house(s, id) {
  const d = s.departments.items.find((x) => x.id === id);
  if (!d) return emptyView(`There is no department "${id}" in config.`, "Departments come from config/permissions.toml.");
  const agents = s.agents.items.filter((a) => a.department === id);
  const ids = new Set(agents.map((a) => a.id));
  const tasks = s.tasks.items.filter((t) => ids.has(t.owner));
  const meetings = s.consultations.items.filter((c) => ids.has(c.opened_by) || c.opinions.some((o) => ids.has(o.by)));
  const lessons = s.lessons.items.filter((l) => ids.has(l.by));
  const rooms = agents.map((a) => `<div class="room ${hue(a.department)}" data-spotlight>
      <div class="row between"><span class="row">${avatar(a)}<span>${agentLink(a.id, a.name)}<br><span class="mono muted">${esc(a.role)}</span></span></span>${pill(a.status)}</div>
      <div><div class="label">Task</div><p>${a.task ? esc(a.task.title) : '<span class="muted">No open task</span>'}</p></div>
      <div>${segments(a.progress)}<span class="muted mono">${a.progress === null ? "progress N/A" : ""}</span></div>
      <div class="mono muted">${esc(a.model || "model N/A")}</div></div>`).join("");
  const meeting = `<div class="room special"><div class="row">${icon("users")}<h3>Meeting room</h3></div>
    ${meetings.length ? meetings.slice(0, 5).map((m) => `<p>${esc(m.subject)}<br><span class="mono muted">${esc(m.opinions.length)} opinions · ${esc(m.risk_class)}</span></p>`).join("") : '<p class="muted">No consultation in progress.</p>'}</div>`;
  const archive = `<div class="room special"><div class="row">${icon("archive")}<h3>Archive</h3></div>
    ${lessons.length ? lessons.slice(0, 5).map((l) => `<p>${esc(l.statement)}</p>`).join("") : '<p class="muted">No lessons recorded yet.</p>'}</div>`;
  return `<div class="row mb-2">${deptBadge(id, "lg")}<span class="muted">${agents.length} agents · roles ${esc(d.roles.join(", "))}</span></div>
    <div class="floorplan">${rooms || emptyView("No agents in this department.")}${meeting}${archive}</div>
    <section class="panel mt-2"><div class="panel-head"><h2>Task queue</h2></div>
    ${table([{ label: "Task", html: (t) => `#${esc(t.id)} ${esc(t.title)}` }, { label: "Owner", html: (t) => agentLink(t.owner) }, { key: "status", label: "Status" }, { key: "updated_at", label: "Updated" }], tasks, { empty: "No tasks in this department." })}</section>`;
}

export function view(ctx) {
  const id = (ctx.param || "").split("?")[0];
  return {
    title: deptName(id),
    html: `${head("Department", `${deptName(id)}.`)}<div data-part="house"></div>`,
    parts: { house: { select: (c) => c.snapshot && [c.snapshot.agents.items, c.snapshot.tasks, c.snapshot.consultations, c.snapshot.lessons], draw: (c) => guard(c, (s) => house(s, id), 8) } },
  };
}
