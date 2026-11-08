// Command center shell (D1): clock and live indicator. No data is computed here (FR-29).
"use strict";

(function () {
  const clock = document.getElementById("clock");
  const live = document.getElementById("live");

  function tick() {
    if (!clock) return;
    const now = new Date();
    clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    clock.setAttribute("datetime", now.toISOString());
  }

  function setLive(state) {
    if (!live) return;
    live.dataset.state = state;
    live.querySelector(".live-text").textContent = state === "live" ? "Live" : "Offline";
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

  // On phones the menu starts closed so the page is visible first.
  const menu = document.querySelector(".menu");
  if (menu && window.matchMedia("(max-width: 767px)").matches) menu.removeAttribute("open");

  tick();
  ping();
  setInterval(tick, 15000);
  setInterval(ping, 10000);
})();
