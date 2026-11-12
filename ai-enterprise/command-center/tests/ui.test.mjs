// node --test: gränssnittets moduler går att tolka, och komponenterna visar N/A i stället för påhittade värden.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { money, num, pct, pill, esc, segments, bar, NA } from "../public/js/ui.js";

function files(dir) {
  return readdirSync(dir).flatMap((f) => (statSync(join(dir, f)).isDirectory() ? files(join(dir, f)) : [join(dir, f)]));
}

test("D-087: every frontend and function module parses", () => {
  const all = [...files("public/js"), ...files("functions"), ...files("lib")].filter((f) => f.endsWith(".js"));
  assert.ok(all.length >= 20);
  for (const f of all) execFileSync(process.execPath, ["--experimental-default-type=module", "--check", f]);
});

test("FR-29: missing values are shown as N/A, never as 0", () => {
  for (const missing of [null, undefined]) {
    assert.equal(money(missing), NA);
    assert.equal(num(missing), NA);
    assert.equal(pct(missing), NA);
  }
  assert.match(money(0), /0\.00 SIM/);
  assert.match(money(123456, "SIM"), /1 234\.56 SIM/);
  assert.match(money(-2500, "SEK"), /−25\.00 SEK/);
});

test("FR-29: unknown statuses are not shown; known ones always have a dot and text", () => {
  assert.equal(pill("unknown"), "");
  const p = pill("working");
  assert.match(p, /class="dot"/);
  assert.match(p, />Working</);
});

test("SR-10: text is escaped before it reaches the page", () => {
  assert.equal(esc(`<img src=x onerror="a">'&`), "&lt;img src=x onerror=&quot;a&quot;&gt;&#39;&amp;");
});

test("D-087: progress that is not tracked shows empty segments, not a guess", () => {
  assert.doesNotMatch(segments(null), /class="on"/);
  assert.match(segments(null), /Progress not tracked/);
  assert.equal((segments(0.5).match(/class="on"/g) || []).length, 5);
  assert.match(bar(2), /data-w="100.00"/);
});
