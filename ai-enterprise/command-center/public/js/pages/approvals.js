// Approvals: glaskort i ett rutnät, segmenterat filter (In review, Approved, Rejected), detaljvy och knappar.
// Knapparna lägger ett beslut i kön (D-089); motorn utför det via ApprovalQueue.approve/reject.
import { NA, esc, money, emptyView, icon, pill, agentLink, toast } from "../ui.js";
import { guard, head } from "./common.js";
import { confirmAction } from "../controls.js";

const FILTERS = { review: ["pending"], approved: ["approved"], rejected: ["rejected"] };
let filter = "review";

function card(r, cur) {
  return `<article class="glass" data-spotlight>
    <div class="row between"><span class="label">#${esc(r.id)} · ${esc(r.kind)}</span>${r.status === "pending" ? pill("waiting", "In review") : r.status === "approved" ? '<span class="pill ok"><span class="dot"></span>Approved</span>' : '<span class="pill bad"><span class="dot"></span>Rejected</span>'}</div>
    <h3>${esc(r.goal || r.reason)}</h3>
    <div class="amount">${money(r.amount, r.currency || cur)}</div>
    <div class="row muted mono">risk ${esc(r.risk_class || "N/A")} · from ${esc(r.requested_by)} · needs ${esc(r.required)} founder</div>
    <div class="row"><button class="btn sm" data-review="${esc(r.id)}">${icon("file-search", "sm")}Review</button>
    ${r.status === "pending" ? `<button class="btn sm primary" data-approve="${esc(r.id)}">${icon("circle-check", "sm")}Approve</button>` : ""}</div></article>`;
}

function grid(s) {
  const rows = s.approvals.items.filter((r) => FILTERS[filter].includes(r.status));
  return rows.length ? `<div class="approvals-grid">${rows.map((r) => card(r, s.currency)).join("")}</div>`
    : emptyView(filter === "review" ? "Nothing is waiting for a founder." : `No ${filter} requests yet.`);
}

function detail(r, cur) {
  const ops = (list, empty) => (list.length ? `<ul>${list.map((o) => `<li><b>${esc(o.by)}</b> (${esc(o.position)}): ${esc(o.text)}</li>`).join("")}</ul>` : `<p class="muted">${empty}</p>`);
  return `<div class="label">Request #${esc(r.id)}</div><h2>${esc(r.goal || r.reason)}</h2>
    <dl class="kv"><dt>Goal</dt><dd>${esc(r.goal || "N/A")}</dd><dt>Amount</dt><dd>${money(r.amount, r.currency || cur)}</dd>
    <dt>Risk class</dt><dd>${esc(r.risk_class || "N/A")}</dd><dt>Max loss</dt><dd>${r.max_loss === null || r.max_loss === undefined ? NA : money(r.max_loss, r.currency || cur)}</dd>
    <dt>Stop conditions</dt><dd>${esc(r.stop_conditions || "N/A")}</dd><dt>Requested by</dt><dd>${agentLink(r.requested_by)}</dd>
    <dt>Reason</dt><dd>${esc(r.reason)}</dd><dt>Votes</dt><dd>${r.votes.length ? r.votes.map((v) => `${esc(v.founder)}: ${esc(v.verdict)}`).join(", ") : "none"}</dd></dl>
    <h3>Consultation</h3>${ops(r.opinions, "No consultation is linked to this task.")}
    <h3>Objections</h3>${ops(r.objections, "No objections.")}`;
}

function openDetail(r, s, act) {
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="stack">${detail(r, s.currency)}
    ${r.status === "pending" ? `<label for="note">Note (required to reject)</label><input id="note" type="text" maxlength="300">` : ""}
    <div class="row between"><button class="btn" value="cancel">Close</button>${r.status === "pending" ? `<span class="row"><button class="btn danger" value="reject">Reject</button><button class="btn primary" value="approve">Approve</button></span>` : ""}</div></form>`;
  document.body.appendChild(d);
  d.addEventListener("close", () => {
    const note = (d.querySelector("#note") || {}).value || "";
    if (d.returnValue === "approve") act({ type: "approve", request: r.id, note }, `Approve #${r.id}`);
    if (d.returnValue === "reject") {
      if (!note.trim()) toast("A rejection needs a note.");
      else act({ type: "reject", request: r.id, note }, `Reject #${r.id}`);
    }
    d.remove();
  });
  d.showModal();
}

export function view() {
  return {
    title: "Approvals",
    html: `${head("Founders", "Approvals.", `<div class="segmented" role="group" aria-label="Filter" data-filter>
      <button type="button" data-f="review" aria-pressed="true">In review</button><button type="button" data-f="approved" aria-pressed="false">Approved</button><button type="button" data-f="rejected" aria-pressed="false">Rejected</button></div>`)}
      <div data-part="grid"></div>`,
    mount: (root, getCtx) => {
      root.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => {
        filter = b.dataset.f;
        root.querySelectorAll("[data-f]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        const el = root.querySelector('[data-part="grid"]');
        el.innerHTML = guard(getCtx(), grid, 4);
        wire(el, getCtx());
      }));
    },
    parts: { grid: { select: (c) => c.snapshot && c.snapshot.approvals.items, draw: (c) => guard(c, grid, 4), after: (el, c) => wire(el, c) } },
  };
}

function wire(el, c) {
  if (!c.snapshot) return;
  const byId = Object.fromEntries(c.snapshot.approvals.items.map((r) => [String(r.id), r]));
  el.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", () => openDetail(byId[b.dataset.review], c.snapshot, c.act)));
  el.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", () => {
    const r = byId[b.dataset.approve];
    confirmAction(`Approve #${r.id}`, `${r.goal || r.reason} for ${(r.amount / 100).toFixed(2)} ${r.currency}.`, () => c.act({ type: "approve", request: r.id, note: "" }, `Approve #${r.id}`));
  }));
}
