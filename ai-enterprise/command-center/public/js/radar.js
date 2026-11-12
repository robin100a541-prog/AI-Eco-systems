// Radarn: agenterna är prickar i banor efter departement och rör sig långsamt. Aktiva agenter pulserar.
// Placeringen är deterministisk (hash av ID), så samma agent står på samma ställe för båda grundarna.
// Rörelsen är en långsam rotation av banorna via SVG-attribut (CSP-säkert); av vid prefers-reduced-motion.
import { esc, deptName } from "./ui.js";

const SIZE = 400, C = SIZE / 2;

function angleFor(id) {
  let h = 2166136261;
  for (const ch of id) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return ((h >>> 0) % 360) * (Math.PI / 180);
}

export function radarSvg(agents, departments) {
  const deps = departments.map((d) => d.id);
  const step = (C - 28) / Math.max(1, deps.length);
  const orbits = deps.map((d, i) => {
    const r = 28 + step * (i + 0.5);
    return `<circle class="orbit" cx="${C}" cy="${C}" r="${r.toFixed(1)}"/><text x="${C + 4}" y="${(C - r - 3).toFixed(1)}">${esc(deptName(d).toUpperCase())}</text>`;
  }).join("");
  const dots = agents.map((a) => {
    const i = Math.max(0, deps.indexOf(a.department));
    const r = 28 + step * (i + 0.5);
    const t = angleFor(a.id);
    const x = (C + r * Math.cos(t)).toFixed(1), y = (C + r * Math.sin(t)).toFixed(1);
    const active = a.status === "working";
    return `<g class="hue-${esc(["executive", "research", "finance"].includes(a.department) ? a.department : (["risk", "compliance", "audit"].includes(a.department) ? "risk" : "other"))}" data-orbit="${i}">
      ${active ? `<circle class="pulse" cx="${x}" cy="${y}" r="6"/>` : ""}
      <circle class="agent-dot" cx="${x}" cy="${y}" r="${active ? 6 : 4.5}"><title>${esc(a.name)} (${esc(a.role)}): ${esc(a.status)}</title></circle></g>`;
  }).join("");
  return `<svg class="radar" viewBox="0 0 ${SIZE} ${SIZE}" role="img" aria-label="Agents by department: ${agents.length} agents">
    <circle class="sweep" cx="${C}" cy="${C}" r="${C - 4}"/>${orbits}<g class="radar-agents">${dots}</g>
    <circle cx="${C}" cy="${C}" r="3" fill="currentColor" class="muted"/></svg>`;
}

// Långsam rotation: inre banor snabbare än yttre, ett varv på 90–240 s. Pausas när fliken är dold.
let raf = 0;
export function animateRadar(svg) {
  cancelAnimationFrame(raf);
  if (!svg || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const groups = [...svg.querySelectorAll("[data-orbit]")];
  const start = performance.now();
  const frame = (now) => {
    if (!svg.isConnected) return;
    if (!document.hidden) {
      const s = (now - start) / 1000;
      for (const g of groups) {
        const o = Number(g.dataset.orbit);
        g.setAttribute("transform", `rotate(${((s * 360) / (90 + o * 30)).toFixed(2)} ${C} ${C})`);
      }
    }
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
}
