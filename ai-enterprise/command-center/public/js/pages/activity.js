// Activity: fliken Live (realtidsflöde) och fliken Logs (revisionslogg och GitHub, med filter och verifierad kedja).
import { esc, table, emptyView, errorView, num } from "../ui.js";
import { guard, head, mergedEvents, feedItem } from "./common.js";
import { listAdd, reduced } from "../effects.js";

let tab = "live", kind = "all", q = "";

function logs(c) {
  const all = mergedEvents(c, 1000);
  const kinds = ["all", ...new Set(all.map((e) => (e.src === "github" ? "github" : e.kind)))];
  const rows = all.filter((e) => (kind === "all" || (kind === "github" ? e.src === "github" : e.kind === kind)) && (!q || JSON.stringify(e).toLowerCase().includes(q)));
  const chain = c.snapshot ? c.snapshot.audit_chain : null;
  return `<div class="row between"><span>${chain ? (chain.ok ? `<span class="pill ok"><span class="dot"></span>Hash chain verified</span> <span class="muted mono">${num(chain.length)} entries</span>` : `<span class="pill bad"><span class="dot"></span>Hash chain broken at ${esc(chain.first_bad_seq)}</span>`) : ""}</span>
    <span class="row"><label class="sr-only" for="log-kind">Type</label><select id="log-kind">${kinds.map((k) => `<option ${k === kind ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>
    <label class="sr-only" for="log-q">Search</label><input id="log-q" type="search" placeholder="Search" value="${esc(q)}"></span></div>
    ${c.githubError ? `<p class="muted">GitHub: ${esc(c.githubError.message)}</p>` : ""}
    ${table([{ label: "When", html: (e) => `<span class="mono">${esc(String(e.at).slice(0, 19).replace("T", " "))}</span>` }, { label: "Source", html: (e) => esc(e.src) }, { label: "Type", html: (e) => esc(e.kind) },
      { label: "Event", html: (e) => (e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noreferrer">${esc(e.text)}</a>` : esc(e.text)) }, { label: "Actor", html: (e) => `<span class="mono">${esc(e.actor || "")}</span>` }, { label: "ID", html: (e) => `<span class="mono muted">${esc(e.id)}</span>` }],
      rows.slice(0, 300), { empty: "No events match." })}
    <p class="muted">The snapshot carries the latest ${c.snapshot ? c.snapshot.events.items.length : 0} audit events. The full log stays in the database.</p>`;
}

export function view() {
  return {
    title: "Activity",
    html: `${head("Events", "Activity.")}<div class="tabs" role="tablist"><button role="tab" data-tab="live" aria-selected="true">Live</button><button role="tab" data-tab="logs" aria-selected="false">Logs</button></div>
      <section class="panel" data-tabpanel="live"><ul class="feed" data-part="live"></ul></section>
      <section class="panel" data-tabpanel="logs" hidden><div data-part="logs"></div></section>`,
    mount: (root, getCtx) => {
      root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
        tab = b.dataset.tab;
        root.querySelectorAll("[data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
        root.querySelectorAll("[data-tabpanel]").forEach((p) => { p.hidden = p.dataset.tabpanel !== tab; });
      }));
      root.addEventListener("input", (e) => {
        if (e.target.id === "log-q") { q = e.target.value.toLowerCase(); redrawLogs(root, getCtx()); }
      });
      root.addEventListener("change", (e) => {
        if (e.target.id === "log-kind") { kind = e.target.value; redrawLogs(root, getCtx()); }
      });
    },
    parts: {
      live: {
        select: (c) => mergedEvents(c, 60).map((e) => e.id),
        draw: (c) => {
          if (!c.snapshot && !c.github) return c.snapshotError ? `<li>${errorView(c.snapshotError.message)}</li>` : '<li><div class="skeleton sk-line"></div></li>';
          const items = mergedEvents(c, 60);
          return items.length ? items.map(feedItem).join("") : `<li>${emptyView("No activity yet.")}</li>`;
        },
        after: (el) => {
          const before = new Set(el._seen || []);
          if (el._seen && !reduced()) [...el.children].filter((li) => !before.has(li.dataset.id)).reverse().forEach((li) => listAdd(el, li, 60));
          el._seen = [...el.children].map((li) => li.dataset.id);
        },
      },
      logs: { select: (c) => [mergedEvents(c, 1000).map((e) => e.id), c.snapshot && c.snapshot.audit_chain], draw: (c) => guard(c, () => logs(c), 8) },
    },
  };
}

function redrawLogs(root, c) {
  const el = root.querySelector('[data-part="logs"]');
  const focused = document.activeElement && document.activeElement.id;
  el.innerHTML = guard(c, () => logs(c), 8);
  if (focused) { const f = el.querySelector(`#${focused}`); if (f) { f.focus(); if (f.setSelectionRange && f.value) f.setSelectionRange(f.value.length, f.value.length); } }
}
