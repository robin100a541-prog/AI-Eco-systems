// node --test: egen inloggning, sessioner, låsning, snapshot, health och GitHub-flödet (D-094, D-085).
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkCode, deriveHash, parseHashes, readSession, createSession, COOKIE, SESSION_SECONDS, MIN_ITERATIONS } from "../lib/session.js";
import { onRequest as middleware, isPublic } from "../functions/_middleware.js";
import { onRequestGet as loginGet, onRequestPost as loginPost } from "../functions/login.js";
import { onRequestPost as logoutPost } from "../functions/logout.js";
import { onRequestGet as snapshotGet } from "../functions/api/snapshot.js";
import { onRequestGet as healthGet } from "../functions/api/health.js";
import { onRequestGet as meGet } from "../functions/api/me.js";
import { loadGithub } from "../functions/api/github.js";
import { ENV_BASE, ORIGIN, VECTORS, FakeKV, callApi, cookieFor, loginForm, request } from "./helpers.mjs";

const page = async () => new Response("<html>secret page</html>", { headers: { "Content-Type": "text/html" } });
const login = (req, env) => callApi(middleware, (c) => (req.method === "POST" ? loginPost(c) : loginGet(c)), req, env);

test("D-094: the code hash is PBKDF2-SHA256 with 210 000 iterations and matches the Python command", async () => {
  const stored = parseHashes(ENV_BASE);
  assert.deepEqual(Object.keys(stored).sort(), ["robin", "yorgo"]);
  assert.equal(stored.yorgo.iterations, 210000);
  assert.equal(MIN_ITERATIONS, 210000);
  assert.equal(await deriveHash(VECTORS.yorgo.code, stored.yorgo.salt, stored.yorgo.iterations), stored.yorgo.hash);
  assert.equal(await checkCode(ENV_BASE, "Yorgo", VECTORS.yorgo.code), true);
  assert.equal(await checkCode(ENV_BASE, "robin", VECTORS.robin.code), true);
  // en hash med för få iterationer eller fel form godtas aldrig
  const weak = { ...ENV_BASE, FOUNDER_CODE_HASHES: VECTORS.yorgo.line.replace("$210000$", "$1000$") + ",robin=plaintext" };
  assert.deepEqual(parseHashes(weak), {});
});

test("FR-28, D-094: a wrong code, the other founder's code and an unknown founder are refused", async () => {
  const env = { ...ENV_BASE, KV: new FakeKV() };
  const cases = [["yorgo", "wrong-code-123"], ["yorgo", VECTORS.robin.code], ["mallory", VECTORS.yorgo.code], ["yorgo", ""]];
  for (const [founder, code] of cases) {
    const res = await login(loginForm(founder, code, { ip: `198.51.100.${cases.findIndex((c) => c[0] === founder && c[1] === code) + 1}` }), env);
    assert.equal(res.status, 401, `${founder}/${code}`);
    assert.equal(res.headers.get("Set-Cookie"), null);
    assert.ok(!(await res.text()).includes(VECTORS.yorgo.code));
  }
  assert.equal((await login(loginForm("yorgo", VECTORS.yorgo.code, { origin: "https://evil.example", ip: "198.51.100.9" }), env)).status, 403);
});

test("FR-28, D-094: the right code gives a signed session cookie for 12 hours, and every attempt is logged", async () => {
  const kv = new FakeKV();
  const env = { ...ENV_BASE, KV: kv };
  await login(loginForm("yorgo", "wrong-code-123"), env);
  const res = await login(loginForm("Yorgo", VECTORS.yorgo.code), env);
  assert.equal(res.status, 303);
  assert.equal(res.headers.get("Location"), "/");
  const cookie = res.headers.get("Set-Cookie");
  for (const flag of ["HttpOnly", "Secure", "SameSite=Strict", "Path=/", `Max-Age=${SESSION_SECONDS}`]) assert.ok(cookie.includes(flag), flag);
  assert.equal(SESSION_SECONDS, 12 * 3600);
  const value = cookie.split(";")[0];
  assert.deepEqual(await readSession(env, request("/", { cookie: value })), { founder: "yorgo" });
  const logs = kv.puts.filter((p) => p.key.startsWith("authlog:")).map((p) => JSON.parse(p.value));
  assert.deepEqual(logs.map((l) => [l.founder, l.ok]), [["yorgo", false], ["yorgo", true]]);
  assert.ok(!JSON.stringify(logs).includes(VECTORS.yorgo.code) && !JSON.stringify(logs).includes("wrong-code-123"));
  assert.ok(!cookie.includes(ENV_BASE.SESSION_SECRET));
});

test("FR-28, D-094: five wrong attempts lock the IP and the founder for 15 minutes, even for the right code", async () => {
  const kv = new FakeKV();
  const env = { ...ENV_BASE, KV: kv };
  for (let i = 0; i < 5; i++) assert.equal((await login(loginForm("yorgo", "wrong-code-123"), env)).status, 401);
  assert.equal((await login(loginForm("yorgo", VECTORS.yorgo.code), env)).status, 429); // samma IP, rätt kod
  assert.equal((await login(loginForm("yorgo", VECTORS.yorgo.code, { ip: "192.0.2.50" }), env)).status, 429); // annan IP, samma grundare
  assert.equal((await login(loginForm("robin", VECTORS.robin.code), env)).status, 429); // samma IP, annan grundare
  assert.equal((await login(loginForm("robin", VECTORS.robin.code, { ip: "192.0.2.51" }), env)).status, 303); // opåverkad
  const lock = kv.puts.filter((p) => p.key === "lock:founder:yorgo").pop();
  assert.equal(lock.opts.expirationTtl, 15 * 60);
  assert.ok(JSON.parse(lock.value).until > Date.now() + 14 * 60 * 1000);
});

test("FR-28, D-094: tampered, re-signed, expired and orphaned session cookies are refused", async () => {
  const good = await cookieFor("yorgo");
  assert.deepEqual(await readSession(ENV_BASE, request("/", { cookie: good })), { founder: "yorgo" });
  const [name, value] = good.split("=");
  const [payload, sig] = value.split(".");
  const asRobin = Buffer.from(JSON.stringify({ f: "robin", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
  const bad = [
    `${name}=${asRobin}.${sig}`,                                   // ändrat innehåll, gammal signatur
    `${name}=${payload}.${sig.slice(0, -2)}xx`,                    // ändrad signatur
    `${name}=${payload}`,                                          // ingen signatur
    await cookieFor("yorgo", { ...ENV_BASE, SESSION_SECRET: "another-secret-0123456789abcdef0123456789" }), // annan nyckel
    await cookieFor("yorgo", ENV_BASE, Date.now() - (SESSION_SECONDS + 5) * 1000), // utgången
    await cookieFor("mallory"),                                    // grundaren finns inte i FOUNDER_CODE_HASHES
  ];
  for (const cookie of bad) {
    assert.equal(await readSession(ENV_BASE, request("/", { cookie })), null, cookie.slice(0, 40));
    assert.equal((await callApi(middleware, page, request("/", { cookie }), ENV_BASE)).status, 302);
    assert.equal((await callApi(middleware, healthGet, request("/api/health", { cookie }), ENV_BASE)).status, 401);
  }
});

test("FR-27, D-094: every path needs a session, static files and /api/health included; only /login is open", async () => {
  for (const path of ["/", "/index.html", "/js/main.js", "/assets/css/app.css", "/vendor/gsap/3.15.1/gsap.min.js", "/logout", "/loginx", "/login.css"]) {
    const res = await callApi(middleware, page, request(path), ENV_BASE);
    assert.equal(res.status, 302, path);
    assert.equal(res.headers.get("Location"), "/login");
    assert.equal(await res.text(), "");
  }
  for (const path of ["/api/health", "/api/snapshot", "/api/me", "/api/github", "/api/action", "/api/chat"]) {
    const res = await callApi(middleware, page, request(path), ENV_BASE);
    assert.equal(res.status, 401, path);
    assert.ok(!(await res.text()).includes("secret page"));
  }
  assert.ok(isPublic("/login") && isPublic("/login/login.css") && !isPublic("/loginx") && !isPublic("/"));
  const open = await login(request("/login"), ENV_BASE);
  assert.equal(open.status, 200);
  assert.match(await open.text(), /<option value="robin">Robin<\/option><option value="yorgo">Yorgo<\/option>/);
  assert.equal((await callApi(middleware, page, request("/login/login.css"), ENV_BASE)).status, 200);
  const cookie = await cookieFor("robin");
  assert.equal(await (await callApi(middleware, page, request("/js/main.js", { cookie }), ENV_BASE)).text(), "<html>secret page</html>");
  assert.deepEqual(await (await callApi(middleware, meGet, request("/api/me", { cookie }), ENV_BASE)).json(), { founder: "robin", mode: "cloudflare" });
});

test("D-094: without FOUNDER_CODE_HASHES or SESSION_SECRET every path answers 503 and nothing is shown", async () => {
  const cookie = await cookieFor("yorgo");
  const broken = [{ ...ENV_BASE, SESSION_SECRET: "" }, { ...ENV_BASE, FOUNDER_CODE_HASHES: "" }, { ...ENV_BASE, SESSION_SECRET: "short" },
    { ...ENV_BASE, FOUNDER_CODE_HASHES: "yorgo=plaintext-code" }, {}];
  for (const env of broken) {
    for (const path of ["/", "/login", "/login/login.css", "/api/health", "/js/main.js"]) {
      const res = await callApi(middleware, page, request(path, { cookie }), env);
      assert.equal(res.status, 503, path);
      assert.equal(await res.text(), "Not configured");
    }
  }
});

test("FR-28: logout clears the cookie and needs the session, same origin and the header", async () => {
  const cookie = await cookieFor("yorgo");
  const post = (headers) => callApi(middleware, logoutPost, request("/logout", { cookie, method: "POST", headers, body: "{}" }), ENV_BASE);
  assert.equal((await post({ "Content-Type": "application/json", Origin: ORIGIN })).status, 403);
  assert.equal((await post({ "Content-Type": "application/json", Origin: "https://evil.example", "X-Command-Center": "1" })).status, 403);
  const res = await post({ "Content-Type": "application/json", Origin: ORIGIN, "X-Command-Center": "1" });
  assert.equal(res.status, 200);
  assert.match(res.headers.get("Set-Cookie"), new RegExp(`^${COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0$`));
});

test("FR-29: both founders get byte-identical snapshot data, never cached", async () => {
  const raw = JSON.stringify({ schema: "aie.snapshot/1", generated_at: new Date().toISOString(), economy: { revenue_gross: { value: 507000 } } });
  const env = { ...ENV_BASE, KV: new FakeKV({ "snapshot:latest": raw }) };
  for (const founder of ["yorgo", "robin"]) {
    const res = await callApi(middleware, snapshotGet, request("/api/snapshot", { cookie: await cookieFor(founder) }), env);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("Cache-Control"), "no-store");
    assert.equal(await res.text(), raw);
  }
});

test("D-085: health reports age and stale status after 26 hours, and API responses are never cached", async () => {
  const cookie = await cookieFor("yorgo");
  const old = new Date(Date.now() - 27 * 3600 * 1000).toISOString();
  const env = { ...ENV_BASE, KV: new FakeKV({ "snapshot:latest": JSON.stringify({ generated_at: old }) }), CF_PAGES_COMMIT_SHA: "abcdef1234" };
  const body = await (await callApi(middleware, healthGet, request("/api/health", { cookie }), env)).json();
  assert.equal(body.status, "stale");
  assert.equal(body.version, "abcdef1");
  assert.ok(body.snapshot_age_seconds >= 27 * 3600 - 5);
  const empty = await callApi(middleware, healthGet, request("/api/health", { cookie }), { ...ENV_BASE, KV: new FakeKV() });
  assert.equal((await empty.json()).status, "no-data");
  const cached = async () => new Response("{}", { headers: { "Cache-Control": "public, max-age=600" } });
  const res = await callApi(middleware, cached, request("/api/health", { cookie }), ENV_BASE);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  assert.equal(res.headers.get("X-Content-Type-Options"), "nosniff");
});

test("SR-10: the GitHub feed sends the token only to api.github.com and returns only whitelisted fields", async () => {
  const seen = [];
  const fake = async (url, init) => {
    seen.push({ url, auth: init.headers.Authorization });
    if (url.includes("/commits")) return Response.json([{ sha: "0123456789abcdef", html_url: "u", author: { login: "yorgo" }, commit: { message: "feat: x\n\nbody secret", author: { name: "Y", date: "2026-11-09T00:00:00Z" } } }]);
    if (url.includes("/pulls")) return Response.json([{ number: 7, title: "t", state: "closed", merged_at: "2026-11-09", user: { login: "robin" }, updated_at: "2026-11-09", html_url: "u", body: "private" }]);
    return Response.json({ total_count: 1, workflow_runs: [{ id: 1, name: "company-daily", status: "completed", conclusion: "success", head_branch: "main", event: "schedule", run_started_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:02:30Z", html_url: "u" }] });
  };
  const out = await loadGithub({ GITHUB_READ_TOKEN: "ghp_secret_test" }, fake);
  assert.ok(seen.every((s) => s.url.startsWith("https://api.github.com/") && s.auth === "Bearer ghp_secret_test"));
  const text = JSON.stringify(out);
  assert.ok(!text.includes("ghp_secret_test"));
  assert.ok(!text.includes("body secret") && !text.includes("private"));
  assert.equal(out.commits[0].id, "commit:0123456789abcdef");
  assert.equal(out.pulls[0].state, "merged");
  assert.equal(out.runs[0].id, "run:1");
  assert.equal(out.actions_month.minutes_estimate, 3);
});
