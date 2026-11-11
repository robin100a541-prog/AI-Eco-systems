// node --test: inloggning, snapshot, health och GitHub-flödet (Command Center Del 1, D-085).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { verifyAccess, resetCertsCache } from "../lib/access.js";
import { onRequest as middleware } from "../functions/_middleware.js";
import { onRequestGet as snapshotGet } from "../functions/api/snapshot.js";
import { onRequestGet as healthGet } from "../functions/api/health.js";
import { loadGithub } from "../functions/api/github.js";
import { ENV_BASE, ROBIN, YORGO, FakeKV, callApi, certsFetch, keyPair, request, sign } from "./helpers.mjs";

let pair, other;
beforeEach(async () => {
  resetCertsCache();
  pair = pair || (await keyPair("k1"));
  other = other || (await keyPair("k1"));  // samma kid, annan nyckel: en förfalskning
});

const verify = (token, env = ENV_BASE) => verifyAccess(request("/api/health", { token }), env, { fetchImpl: certsFetch(pair) });

test("FR-28: a valid Access JWT for an allowed founder passes", async () => {
  assert.deepEqual(await verify(await sign(pair)), { email: YORGO, founder: "yorgo" });
  assert.deepEqual(await verify(await sign(pair, { email: ROBIN.toUpperCase() })), { email: ROBIN, founder: "robin" });
});

test("FR-28: missing, forged, wrong audience, wrong issuer, expired and wrong email are all refused", async () => {
  const now = Math.floor(Date.now() / 1000);
  const cases = {
    "missing token": null,
    "bad signature": await sign(other),
    "bad audience": await sign(pair, { aud: ["someone-else"] }),
    "bad issuer": await sign(pair, { iss: "https://evil.cloudflareaccess.com" }),
    expired: await sign(pair, { exp: now - 5 }),
    "email not allowed": await sign(pair, { email: "mallory@example.com" }),
    "unknown key": await sign(pair, {}, { kid: "nope" }),
    "bad alg": await sign(pair, {}, { alg: "HS256" }),
    "malformed token": "abc.def",
  };
  for (const [reason, token] of Object.entries(cases)) {
    await assert.rejects(verify(token), (e) => e.message === reason, reason);
  }
});

test("D-086: ACCESS_AUD may list the production and preview applications, and nothing else", async () => {
  const env = { ...ENV_BASE, ACCESS_AUD: "aud-preview-app, aud-command-center-test" };
  assert.equal((await verify(await sign(pair), env)).email, YORGO);
  assert.equal((await verify(await sign(pair, { aud: ["aud-preview-app"] }), env)).email, YORGO);
  await assert.rejects(verify(await sign(pair, { aud: ["aud-other-app"] }), env), /bad audience/);
});

test("FR-28: API responses are never cached, whatever the handler sets", async () => {
  globalThis.fetch = certsFetch(pair);
  const handler = async () => new Response("{}", { headers: { "Cache-Control": "public, max-age=600" } });
  const res = await callApi(middleware, handler, request("/api/health", { token: await sign(pair) }), { ...ENV_BASE });
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  assert.equal(res.headers.get("X-Content-Type-Options"), "nosniff");
});

test("FR-28: without configuration nothing is allowed", async () => {
  await assert.rejects(verify(await sign(pair), { ...ENV_BASE, ALLOWED_EMAILS: "" }), /no allowed emails/);
  await assert.rejects(verify(await sign(pair), { ...ENV_BASE, ACCESS_AUD: "" }), /access not configured/);
});

test("FR-28: /api/health and /api/snapshot require login (401 without or with a forged token)", async () => {
  globalThis.fetch = certsFetch(pair);
  const env = { ...ENV_BASE, KV: new FakeKV({ "snapshot:latest": '{"generated_at":"2026-11-09T00:00:00+00:00"}' }) };
  for (const handler of [healthGet, snapshotGet]) {
    for (const token of [null, await sign(other)]) {
      const res = await callApi(middleware, handler, request("/api/health", { token }), env);
      assert.equal(res.status, 401);
      assert.equal((await res.json()).error, "unauthorized");
    }
  }
});

test("FR-29: both founders get byte-identical snapshot data, never cached", async () => {
  globalThis.fetch = certsFetch(pair);
  const raw = JSON.stringify({ schema: "aie.snapshot/1", generated_at: new Date().toISOString(), economy: { revenue_gross: { value: 507000 } } });
  const env = { ...ENV_BASE, KV: new FakeKV({ "snapshot:latest": raw }) };
  const bodies = [];
  for (const email of [YORGO, ROBIN]) {
    const res = await callApi(middleware, snapshotGet, request("/api/snapshot", { token: await sign(pair, { email }) }), env);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("Cache-Control"), "no-store");
    bodies.push(await res.text());
  }
  assert.equal(bodies[0], raw);
  assert.equal(bodies[1], raw);
});

test("D-085: health reports age and stale status after 26 hours", async () => {
  globalThis.fetch = certsFetch(pair);
  const old = new Date(Date.now() - 27 * 3600 * 1000).toISOString();
  const env = { ...ENV_BASE, KV: new FakeKV({ "snapshot:latest": JSON.stringify({ generated_at: old }) }), CF_PAGES_COMMIT_SHA: "abcdef1234" };
  const res = await callApi(middleware, healthGet, request("/api/health", { token: await sign(pair) }), env);
  const body = await res.json();
  assert.equal(body.status, "stale");
  assert.equal(body.version, "abcdef1");
  assert.ok(body.snapshot_age_seconds >= 27 * 3600 - 5);
  const empty = await callApi(middleware, healthGet, request("/api/health", { token: await sign(pair) }), { ...ENV_BASE, KV: new FakeKV() });
  assert.equal((await empty.json()).status, "no-data");
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
  assert.equal(out.actions_month.minutes_estimate, 3);  // 2,5 minuter avrundat uppåt
});
