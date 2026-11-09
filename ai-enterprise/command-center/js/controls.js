// Bekräftelser för knappar som lägger ett beslut i kön (D-089). Inget ändras direkt i webbläsaren.
import { esc } from "./ui.js";

function dialog(html) {
  const d = document.createElement("dialog");
  d.innerHTML = html;
  document.body.appendChild(d);
  d.addEventListener("close", () => d.remove());
  d.showModal();
  return d;
}

export function confirmAction(title, text, onConfirm, { confirmLabel = "Queue decision", danger = false } = {}) {
  const d = dialog(`<form method="dialog" class="stack">
    <div class="label">Founder decision</div><h2>${esc(title)}</h2><p class="muted">${esc(text)}</p>
    <p class="muted">The decision is queued and applied by the engine through core functions, and it is logged with your email.</p>
    <div class="row between"><button class="btn" value="cancel">Cancel</button>
    <button class="btn ${danger ? "danger" : "primary"}" value="ok">${esc(confirmLabel)}</button></div></form>`);
  d.addEventListener("close", () => { if (d.returnValue === "ok") onConfirm(); });
}

// Kill kräver att man skriver KILL i rutan.
export function confirmKill(onConfirm) {
  const d = dialog(`<form method="dialog" class="stack">
    <div class="label">Emergency stop</div><h2>Engage the kill switch</h2>
    <p class="muted">All agents stop and no new transactions are made. Nothing is deleted. Releasing it again takes a founder vote, as today.</p>
    <label for="kill-confirm">Type <b class="mono">KILL</b> to confirm</label>
    <input id="kill-confirm" type="text" autocomplete="off" spellcheck="false">
    <div class="row between"><button class="btn" value="cancel">Cancel</button>
    <button class="btn danger" value="ok" id="kill-ok" disabled>Engage kill switch</button></div></form>`);
  const input = d.querySelector("#kill-confirm"), ok = d.querySelector("#kill-ok");
  input.addEventListener("input", () => { ok.disabled = input.value.trim() !== "KILL"; });
  input.focus();
  d.addEventListener("close", () => { if (d.returnValue === "ok" && input.value.trim() === "KILL") onConfirm(); });
}
