// Agent: profil, mandat, prestation, körhistorik, intäkt och kostnad, senaste arbete, kontroller och chatt.
import { NA, avatar, esc, money, pct, pill, table, emptyView, ago, num, icon, deptName, toast } from "../ui.js";
import { guard, head } from "./common.js";
import { postChat } from "../api.js";
import { confirmAction } from "../controls.js";

function profile(s, a) {
  const per = s.per_agent.items.find((r) => r.agent === a.id);
  const rules = s.rules || {};
  const threshold = rules.approval_threshold;
  const governance = rules.governance_tools || [];
  return `<div class="grid g-12">
    <div class="span-4 stack"><section class="panel"><div class="row">${avatar(a, "lg")}<div><h2>${esc(a.name)}</h2><div class="mono muted">${esc(a.role)} · ${esc(a.id)}</div></div></div>
      <p class="muted mt-2">${esc(a.description || "")}</p>
      <dl class="kv mt-2"><dt>Status</dt><dd>${pill(a.status) || '<span class="muted">not verifiable</span>'}</dd><dt>Lifecycle</dt><dd class="mono">${esc(a.lifecycle)}</dd>
      <dt>Department</dt><dd><a href="#/department/${encodeURIComponent(a.department)}">${esc(deptName(a.department))}</a></dd><dt>Reports to</dt><dd>${a.manager ? `<a href="#/agent/${encodeURIComponent(a.manager)}">${esc(a.manager)}</a>` : "the founders"}</dd>
      <dt>Model</dt><dd class="mono">${esc(a.model || "N/A")}</dd><dt>Task</dt><dd>${a.task ? esc(a.task.title) : NA}</dd></dl></section>
      <section class="panel"><div class="panel-head"><h2>Controls</h2></div><div class="row">
        <button class="btn" data-act="pause_agent" ${a.paused || !["active", "probation"].includes(a.lifecycle) ? "disabled" : ""}>${icon("pause", "sm")}Pause</button>
        <button class="btn" data-act="resume_agent" ${a.paused ? "" : "disabled"}>${icon("play", "sm")}Resume</button>
        <button class="btn" disabled title="The engine has no safe way to run one agent on demand">${icon("refresh-cw", "sm")}Run now</button></div>
        <p class="muted">Run now is read-only: agents run in the daily cycle, and the core has no safe single-agent run (see DATA.md).</p></section></div>
    <div class="span-8 stack"><section class="panel"><div class="panel-head"><div><div class="label">Mandate</div><h2>What this agent may do</h2></div></div>
      <div class="grid g-3"><div><div class="label">On its own</div><ul class="mono muted">${a.tools.map((t) => `<li>${esc(t)}</li>`).join("") || "<li>No tools</li>"}</ul></div>
      <div><div class="label">Needs approval</div><p class="muted">Any decision above ${threshold === undefined || threshold === null ? "N/A" : money(threshold, s.currency)} (HUMAN_APPROVAL_THRESHOLD) waits for a founder (D-019, D-049). Spending goes through the budget engine.</p></div>
      <div><div class="label">Never</div><p class="muted">Every tool outside the mandate (default deny, SR-02) and the governance tools ${governance.map((g) => `<span class="mono">${esc(g)}</span>`).join(", ") || ""} (SR-04).</p></div></div></section>
      <div class="metrics">${[["Runs", num(a.runs)], ["Success rate", pct(a.success_rate)], ["Revenue", per ? money(per.revenue, s.currency) : NA], ["Cost", per ? money(per.cost, s.currency) : NA], ["Profit", per ? money(per.net, s.currency) : NA]]
        .map(([l, v]) => `<div class="card metric"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("")}</div>
      <section class="panel"><div class="panel-head"><h2>Run history</h2><span class="mono muted">${esc(a.actions_done)} done · ${esc(a.actions_failed)} failed</span></div>
      ${table([{ label: "When", html: (r) => `<span class="mono">${esc(r.at.slice(0, 19).replace("T", " "))}</span>` }, { label: "Model", html: (r) => `<span class="mono">${esc(r.model)}</span>` }, { label: "Tokens", right: true, html: (r) => num(r.tokens) }, { key: "data_class", label: "Data class" }], a.recent_runs, { empty: "This agent has not run yet." })}</section></div></div>`;
}

function work(s, a) {
  const mine = s.events.items.filter((e) => e.actor === a.id || e.action.includes(a.id));
  const checks = s.blocks_today.items.filter((b) => (b.what || "").includes(a.id));
  return `<div class="grid g-2">
    <section class="panel"><div class="panel-head"><h2>Latest work</h2></div>${mine.length ? `<ul class="feed">${mine.slice(0, 12).map((e) => `<li><span class="src">${icon("circle-dot", "sm")}</span><span class="what">${esc(e.type)}<br><span class="mono muted">${esc(e.action)}</span></span><span class="when">${esc(e.at.slice(0, 16).replace("T", " "))}</span></li>`).join("")}</ul>` : emptyView("No recorded work by this agent in the latest events.")}</section>
    <section class="panel"><div class="panel-head"><h2>Checks today</h2></div>${checks.length ? table([{ key: "step", label: "Step" }, { key: "what", label: "What" }, { key: "count", label: "Count", right: true }], checks) : emptyView("No blocked actions today.")}</section></div>`;
}

function chatPanel(a) {
  return `<section class="panel chat" id="chat"><div class="panel-head"><div><div class="label">Chat</div><h2>Ask ${esc(a.name)}</h2></div><span class="pill">${icon("lock", "sm")}No tools</span></div>
    <p class="muted">The agent answers from its role, mandate and latest data. It can explain, never approve, change limits or act. Suggestions are marked "Hypothesis — not verified".</p>
    <ol class="feed" data-chat-log></ol>
    <form class="stack" data-chat-form><label class="sr-only" for="chat-input">Message</label><textarea id="chat-input" maxlength="1000" required placeholder="Ask about its work, numbers or decisions"></textarea>
    <div class="row between"><span class="muted mono" data-chat-status></span><button class="btn primary" type="submit">${icon("send", "sm")}Send</button></div></form></section>`;
}

export function view(ctx) {
  const [id, query] = (ctx.param || "").split("?");
  const pick = (s) => s.agents.items.find((x) => x.id === id);
  return {
    title: id,
    html: `<div data-part="head"></div><div data-part="profile"></div><div data-part="work"></div><div data-part="chat"></div>`,
    parts: {
      head: { select: (c) => c.snapshot && pick(c.snapshot) && [pick(c.snapshot).name, pick(c.snapshot).status], draw: (c) => guard(c, (s) => { const a = pick(s); return head("Agent", a ? `${a.name}.` : `${id}.`, a ? pill(a.status) : ""); }, 1) },
      profile: { select: (c) => c.snapshot && [pick(c.snapshot), c.snapshot.per_agent, c.snapshot.rules], draw: (c) => guard(c, (s) => (pick(s) ? profile(s, pick(s)) : emptyView(`No agent "${id}" is registered.`)), 8),
        after: (el, c) => el.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => {
          const type = b.dataset.act;
          confirmAction(type === "pause_agent" ? `Pause ${id}` : `Resume ${id}`, type === "pause_agent" ? "A control stop is placed on the agent through the core. It can use no tools until a founder lifts the stop. Nothing is deleted." : "The control stop on the agent is lifted through the core.",
            () => c.act({ type, agent: id }, type === "pause_agent" ? "Pause agent" : "Resume agent"));
        })) },
      work: { select: (c) => c.snapshot && pick(c.snapshot) && [c.snapshot.events.items.slice(0, 80).map((e) => e.id), c.snapshot.blocks_today], draw: (c) => guard(c, (s) => (pick(s) ? work(s, pick(s)) : ""), 4) },
      chat: { select: (c) => c.snapshot && !!pick(c.snapshot), draw: (c) => guard(c, (s) => (pick(s) ? chatPanel(pick(s)) : ""), 2),
        after: (el) => {
          const form = el.querySelector("[data-chat-form]");
          if (!form) return;
          if (query === "chat") el.querySelector("textarea").focus();
          const log = el.querySelector("[data-chat-log]"), status = el.querySelector("[data-chat-status]");
          form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            const ta = form.querySelector("textarea"), text = ta.value.trim();
            if (!text) return;
            log.insertAdjacentHTML("beforeend", `<li><span class="src">${icon("user", "sm")}</span><span class="what">${esc(text)}</span><span class="when">you</span></li>`);
            ta.value = ""; status.textContent = "Thinking...";
            try {
              const res = await postChat({ agent: id, message: text });
              log.insertAdjacentHTML("beforeend", `<li><span class="src github">${icon("bot", "sm")}</span><span class="what"><span class="pill waiting"><span class="dot"></span>${esc(res.label || "Hypothesis — not verified")}</span><br>${esc(res.reply)}</span><span class="when">${esc(res.model || "")}</span></li>`);
              status.textContent = `${res.remaining ?? "?"} messages left this hour`;
            } catch (e) {
              status.textContent = e.data && e.data.code === "quota" ? "Waiting for quota" : `Chat unavailable: ${e.message}`;
              if (!(e.data && e.data.code === "quota")) toast(`Chat failed: ${e.message}`);
            }
          });
        } },
    },
  };
}
