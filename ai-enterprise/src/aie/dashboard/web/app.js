// Command center shell (D1): clock, live indicator and motion (D-084). No data is computed here (FR-29).
"use strict";

(function () {
  const gsap = window.gsap;
  const fx = (window.AIE && window.AIE.effects) || null;
  const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motion = () => !!gsap && !!fx && !reduceQuery.matches;
  const root = document.documentElement;
  const clock = document.getElementById("clock");
  const live = document.getElementById("live");
  const content = document.getElementById("content");

  if (gsap) gsap.defaults({ ease: "power2.out", duration: 0.3 });

  // --- Clock -----------------------------------------------------------------------------------------
  function tick() {
    if (!clock) return;
    const now = new Date();
    clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    clock.setAttribute("datetime", now.toISOString());
  }

  // --- Live indicator: a status change is the only thing that moves here -----------------------------
  function setLive(state) {
    if (!live) return;
    const changed = live.dataset.state !== state;
    live.dataset.state = state;
    live.querySelector(".live-text").textContent = state === "live" ? "Live" : "Offline";
    if (changed && motion()) {
      gsap.fromTo(live.querySelector(".dot"), { scale: 1.8 }, { scale: 1, duration: 0.35 });
      gsap.fromTo(live, { autoAlpha: 0.5 }, { autoAlpha: 1, duration: 0.25 });
    }
  }

  // Until the event stream exists (D2), "Live" means the server answers.
  async function ping() {
    try {
      const res = await fetch("/api/ping", { cache: "no-store", credentials: "same-origin", redirect: "manual" });
      setLive(res.ok ? "live" : "offline");
    } catch (e) {
      setLive("offline");
    }
  }

  // --- Page enter: heading, then panels, short and staggered -----------------------------------------
  function enter() {
    if (!content) return;
    const parts = content.querySelectorAll(":scope > h1, :scope > .metrics > .card, :scope > .card");
    if (motion()) {
      const tween = gsap.fromTo(parts, { autoAlpha: 0, y: 8 },
        { autoAlpha: 1, y: 0, duration: 0.35, stagger: 0.05, clearProps: "transform,opacity,visibility" });
      // Failsafe: if no animation frame runs (hidden tab), jump to the end so nothing stays invisible.
      setTimeout(() => { if (tween.progress() < 1) tween.progress(1); }, 1200);
    }
    root.classList.remove("motion"); // the tween above has already set its start state inline
    content.querySelectorAll("[data-animated-list]").forEach((list) => fx && fx.listIn(list));
    content.querySelectorAll("[data-spotlight]").forEach((el) => fx && fx.spotlight(el));
    if (fx) fx.countAll(content);
  }

  // --- Page leave: a quick fade before same-site navigation (not for new tabs or modified clicks) -----
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[href]");
    if (!a || !motion() || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || a.target || url.pathname === location.pathname) return;
    ev.preventDefault();
    gsap.to(content, { autoAlpha: 0, y: -4, duration: 0.15, ease: "power1.out", onComplete: () => { location.href = url.href; } });
  });
  window.addEventListener("pageshow", (ev) => { if (ev.persisted && content) gsap && gsap.set(content, { clearProps: "all" }); });

  // --- Smooth main scroll (Lenis): desktop with a fine pointer only; never on touch or reduced motion --
  // Tables, chat, modals and scrollable panels scroll natively: mark them with data-lenis-prevent.
  let lenis = null;
  function wantsLenis() {
    const touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
    return !!window.Lenis && !touch && !reduceQuery.matches &&
      window.matchMedia("(min-width: 768px) and (hover: hover) and (pointer: fine)").matches;
  }
  function syncLenis() {
    if (wantsLenis() && !lenis) {
      lenis = new window.Lenis({
        autoRaf: true,
        lerp: 0.14,
        smoothWheel: true,
        prevent: (node) => !!(node.closest && node.closest("table, dialog, [role=dialog], .chat, .scroll-panel")),
      });
    } else if (!wantsLenis() && lenis) {
      lenis.destroy();
      lenis = null;
    }
  }
  reduceQuery.addEventListener("change", syncLenis);

  // On phones the menu starts closed so the page is visible first.
  const menu = document.querySelector(".menu");
  if (menu && window.matchMedia("(max-width: 767px)").matches) menu.removeAttribute("open");

  syncLenis();
  enter();
  tick();
  ping();
  setInterval(tick, 15000);
  setInterval(ping, 10000);
})();
