// Rörelse (D-084, DESIGN.md "Rörelse"). Vanlig JavaScript ovanpå GSAP om det finns; utan GSAP visas slutläget.
//
// Tre effekter är ombyggda efter React Bits (https://github.com/davidhdev/react-bits, commit b0422bb, 2026-11-08),
// Copyright (c) 2026 David Haz, MIT + Commons Clause License Condition v1.0. Licensen ligger i
// vendor/react-bits/LICENSE.md. De ombyggda effekterna är en del av appen och sprids inte som egna komponenter.
//   - countUp   <- src/content/TextAnimations/CountUp/CountUp.jsx      (ease-out, ingen fjäder)
//   - spotlight <- src/content/Components/SpotlightCard/SpotlightCard.jsx (ljus under pekaren, bara mus)
//   - listAdd   <- src/content/Components/AnimatedList/AnimatedList.jsx  (varianten "fade")

const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
export const reduced = () => reduceQuery.matches || !window.gsap;
const EASE = "power2.out";

// Räknar upp ett tal en gång. Texten ändras först när animationen faktiskt går; slutvärdet står i HTML.
export function countUp(el) {
  const target = parseFloat(el.dataset.count);
  if (!Number.isFinite(target) || el.dataset.counted || reduced()) return;
  el.dataset.counted = "1";
  const decimals = parseInt(el.dataset.decimals || "0", 10);
  const suffix = el.dataset.suffix || "";
  const final = el.textContent;
  el.setAttribute("aria-label", final.trim());
  const state = { v: 0 };
  window.gsap.to(state, {
    v: target, duration: 0.25 + Math.min(0.5, Math.log10(Math.abs(target) + 1) * 0.08), ease: "power3.out",
    onUpdate: () => {
      const [i, f] = Math.abs(state.v).toFixed(decimals).split(".");
      el.textContent = `${state.v < 0 ? "−" : ""}${i.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${f ? `.${f}` : ""}${suffix}`;
    },
    onComplete: () => { el.textContent = final; },
  });
}

export function spotlight(el) {
  if (el.dataset.spot) return;
  el.dataset.spot = "1";
  el.classList.add("spotlight");
  if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  el.addEventListener("pointerenter", () => el.classList.add("is-lit"));
  el.addEventListener("pointerleave", () => el.classList.remove("is-lit"));
  el.addEventListener("pointermove", (ev) => {
    if (reduced()) return;
    const b = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", (((ev.clientX - b.left) / b.width) * 100).toFixed(1));
    el.style.setProperty("--spot-y", (((ev.clientY - b.top) / b.height) * 100).toFixed(1));
  });
}

// Ny rad överst i ett flöde, som tonar in 4 px. Äldre rader faller bort efter max.
export function listAdd(list, item, max = 50) {
  list.prepend(item);
  while (list.children.length > max) list.lastElementChild.remove();
  if (reduced()) return;
  window.gsap.from(item, { autoAlpha: 0, y: -4, duration: 0.2, ease: EASE, clearProps: "all" });
}

export function enhance(root) {
  root.querySelectorAll("[data-count]").forEach(countUp);
  root.querySelectorAll("[data-spotlight]").forEach(spotlight);
}

// Mjuk huvudscroll (Lenis): bara desktop med mus, aldrig touch eller reducerad rörelse,
// aldrig i tabeller, dialoger, chatt eller rullbara paneler.
let lenis = null;
const desktopQuery = window.matchMedia("(min-width: 768px) and (hover: hover) and (pointer: fine)");
export function syncLenis() {
  const touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const want = !!window.Lenis && !touch && !reduceQuery.matches &&
    desktopQuery.matches;
  if (want && !lenis) {
    lenis = new window.Lenis({ autoRaf: true, lerp: 0.14, smoothWheel: true,
      prevent: (node) => !!(node.closest && node.closest("table, dialog, .table-wrap, .chat, .scroll-panel, [data-lenis-prevent]")) });
  } else if (!want && lenis) {
    lenis.destroy();
    lenis = null;
  }
}
reduceQuery.addEventListener("change", syncLenis);
desktopQuery.addEventListener("change", syncLenis);
