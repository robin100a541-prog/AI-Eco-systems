// Gemensamt för sidorna: rubrik, och laddnings-, fel- och tomvy runt varje del.
import { esc, errorView, skeleton } from "../ui.js";

export function head(label, title, extra = "") {
  return `<div class="page-head"><div><div class="label">${esc(label)}</div><h1>${esc(title)}</h1></div>${extra}</div>`;
}

// Kör draw(snapshot) när data finns, annars laddningsvy eller felvy.
export function guard(ctx, draw, lines = 3) {
  if (!ctx.snapshot) {
    if (ctx.snapshotError) return errorView(`No data: ${ctx.snapshotError.message}`);
    return skeleton(lines, true);
  }
  return draw(ctx.snapshot);
}

export const part = (name, cls = "") => `<div data-part="${esc(name)}" class="${esc(cls)}"></div>`;

export const agentsById = (s) => Object.fromEntries(s.agents.items.map((a) => [a.id, a]));

// Händelser ur snapshoten och GitHub i ett flöde, nyast först. Varje rad har ett unikt id.
export function mergedEvents(ctx, limit = 30) {
  const items = [];
  for (const e of (ctx.snapshot ? ctx.snapshot.events.items : [])) {
    items.push({ id: e.id, at: e.at, kind: e.type, text: e.action, actor: e.actor, src: "audit" });
  }
  const g = ctx.github;
  if (g) {
    for (const c of g.commits) items.push({ id: c.id, at: c.at, kind: "commit", text: c.message, actor: c.author, src: "github", url: c.url });
    for (const p of g.pulls) items.push({ id: p.id, at: p.at, kind: `PR ${p.state}`, text: `#${p.number} ${p.title}`, actor: p.author, src: "github", url: p.url });
    for (const r of g.runs) items.push({ id: r.id, at: r.at, kind: `run ${r.conclusion || r.status}`, text: `${r.name} (${r.branch})`, actor: r.event, src: "github", url: r.url });
  }
  const seen = new Set();
  return items.filter((i) => (seen.has(i.id) ? false : seen.add(i.id))).sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, limit);
}

const SRC_ICON = { "revenue recorded": "trending-up", "transaction recorded": "wallet", "transaction completed": "wallet", error: "circle-x",
  blocked: "octagon-x", approval: "circle-check", "kill switch": "octagon-x", "protected mode": "shield", "run completed": "refresh-cw",
  "agent started": "play", "agent stopped": "pause", "task completed": "circle-check", "founder control": "user", commit: "git-commit-horizontal" };

export function feedItem(e) {
  const iconName = e.src === "github" ? (e.kind === "commit" ? "git-commit-horizontal" : e.kind.startsWith("PR") ? "git-pull-request" : "workflow") : (SRC_ICON[e.kind] || "circle-dot");
  const cls = e.src === "github" ? "github" : ["error", "blocked", "kill switch"].includes(e.kind) ? "error" : e.kind.includes("revenue") || e.kind.includes("transaction") ? "money" : "";
  const text = e.url ? `<a href="${esc(e.url)}" rel="noreferrer" target="_blank">${esc(e.text)}</a>` : esc(e.text);
  return `<li data-id="${esc(e.id)}"><span class="src ${cls}"><svg class="icon sm" aria-hidden="true"><use href="/assets/icons/lucide-sprite.svg#i-${iconName}"></use></svg></span>
    <span class="what">${text}<br><span class="muted mono">${esc(e.actor || "")} · ${esc(e.kind)}</span></span><span class="when">${esc(String(e.at || "").slice(0, 16).replace("T", " "))}</span></li>`;
}
