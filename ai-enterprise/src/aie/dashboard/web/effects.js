// Command center motion effects (D-084). Plain JavaScript on top of GSAP; no React.
//
// Three effects are rebuilt from ideas in React Bits (https://github.com/davidhdev/react-bits,
// commit b0422bb, 2026-11-08), Copyright (c) 2026 David Haz, MIT + Commons Clause License Condition v1.0.
// The license is in vendor/react-bits/LICENSE.md. These ports are part of this application only and are
// not sold, sublicensed or redistributed on their own.
//   - countUp   <- src/content/TextAnimations/CountUp/CountUp.jsx    (ease-out count, no spring)
//   - spotlight <- src/content/Components/SpotlightCard/SpotlightCard.jsx (pointer light and border glow)
//   - list      <- src/content/Components/AnimatedList/AnimatedList.jsx (the "fade" variant only)
//
// Rules (DESIGN.md, "Rörelse"): short, ease-out, no bounce, nothing moves without meaning.
// With prefers-reduced-motion every effect shows its final state at once.
"use strict";

(function () {
  const gsap = window.gsap;
  const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const EASE = "power2.out"; // close to cubic-bezier(0.33, 1, 0.68, 1), the React Bits ease-out
  const reduced = () => reduceQuery.matches || !gsap;

  // --- countUp: numbers count from 0 to their value once, when they come into view -------------------
  function format(value, decimals, separator) {
    const [int, frac] = Math.abs(value).toFixed(decimals).split(".");
    const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    return (value < 0 ? "-" : "") + grouped + (frac ? "." + frac : "");
  }

  function countUp(el) {
    const target = parseFloat(el.dataset.count);
    if (!Number.isFinite(target) || el.dataset.counted) return;
    el.dataset.counted = "1";
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const suffix = el.dataset.suffix || "";
    const final = el.textContent;
    el.setAttribute("aria-label", final.trim()); // screen readers get the final value, not the ticking one
    if (reduced()) return;
    // The text only changes once frames actually run. If the animation never starts (a hidden tab pauses
    // requestAnimationFrame), the correct final value stays on screen; a wrong number is never shown.
    const state = { value: 0 };
    gsap.to(state, {
      value: target,
      duration: Math.min(1.1, 0.6 + Math.log10(Math.abs(target) + 1) * 0.15),
      ease: "power3.out",
      onUpdate: () => { el.textContent = format(state.value, decimals, " ") + suffix; },
      onComplete: () => { el.textContent = final; },
    });
  }

  function countAll(root) {
    const items = (root || document).querySelectorAll("[data-count]");
    if (!("IntersectionObserver" in window)) return items.forEach(countUp);
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { countUp(e.target); seen.unobserve(e.target); } });
    }, { threshold: 0.4 });
    items.forEach((el) => seen.observe(el));
  }

  // --- spotlight: a soft gold light follows the pointer inside a card, and lights the border nearby ---
  // Only for fine pointers that can hover. With reduced motion the light does not follow; the border is lit.
  function spotlight(el) {
    if (el.dataset.spotlightReady) return;
    el.dataset.spotlightReady = "1";
    el.classList.add("spotlight");
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const setX = reduced() ? null : gsap.quickTo(el, "--spot-x", { duration: 0.25, ease: EASE });
    const setY = reduced() ? null : gsap.quickTo(el, "--spot-y", { duration: 0.25, ease: EASE });
    el.addEventListener("pointerenter", () => el.classList.add("is-lit"));
    el.addEventListener("pointerleave", () => el.classList.remove("is-lit"));
    el.addEventListener("pointermove", (ev) => {
      if (!setX) return;
      const box = el.getBoundingClientRect();
      setX(((ev.clientX - box.left) / box.width) * 100);
      setY(((ev.clientY - box.top) / box.height) * 100);
    });
  }

  // --- list: items fade in with a 4 px rise, staggered; new items for a live feed enter at the top -----
  function listIn(list) {
    const items = Array.from(list.children);
    if (reduced() || !items.length) return;
    gsap.from(items, { autoAlpha: 0, y: 4, duration: 0.3, ease: EASE, stagger: 0.05, clearProps: "all" });
  }

  function listAdd(list, item, max) {
    list.prepend(item);
    while (max && list.children.length > max) list.lastElementChild.remove();
    if (reduced()) return;
    gsap.from(item, { autoAlpha: 0, y: -4, height: 0, duration: 0.3, ease: EASE, clearProps: "all" });
  }

  window.AIE = window.AIE || {};
  window.AIE.effects = { countUp, countAll, spotlight, listIn, listAdd, reduced, EASE };
})();
