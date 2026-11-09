// Runs in <head> before the first paint (no defer). Marks that entrance motion will play, so the content
// can start hidden instead of flashing. With prefers-reduced-motion nothing is hidden. app.css also has a
// fallback that shows the content after 1.2 s if the animation never starts (D-084).
"use strict";
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.documentElement.classList.add("motion");
}
