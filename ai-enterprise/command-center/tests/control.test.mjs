// node --test: knapptryck till kön och chatt utan verktyg (Command Center Del 4, D-089, D-090).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resetCertsCache } from "../lib/access.js";
import { onRequest as middleware } from "../functions/_middleware.js";
import { onRequestPost as actionPost, buildItem, LIMIT_PER_HOUR, TYPES } from "../functions/api/action.js";
import { onRequestPost as chatPost, buildContext, LABEL, LIMIT_PER_HOUR as CHAT_LIMIT } from "../functions/api/chat.js";
import { ENV_BASE, YORGO, FakeKV, certsFetch, keyPair, request, sign } from "./helpers.mjs";

const ORIGIN = "https://command-center.pages.dev";
const SNAPSHOT = {
  generated_at: "2026-11-09T12:00:00+00:00", currency: "SIM",
  economy: { revenue_gross: { value: 507000 }, costs: { value: 2000 }, platform_fees: { value: 97265 }, refunds: { value: 9800 },
    net_profit_realized: { value: 397935 }, tax_reserve: { value: 198880 } },
  economy_real: { revenue_gross: { value: 123456789 } },
  agents: { items: [{ id: "lead-1", name: "Filip", role: "research_lead", department: "research", description: "leads Research",
    tools: ["forecast.make"], status: "waiting", task: { title: "Run a promotion" }, runs: 30 }] },
  approvals: { items: [{ id: 1, status: "pending", requested_by: "lead-1", goal: "Run a promotion", amount: 11500 }] },
  quotas: { items: [{ provider: "groq", model: "test-model" }] },
};

let pair;
beforeEach(async () => {
  resetCertsCache();
  pair = pair || (await keyPair("k1"));
});

function post(path, body, { token, origin = ORIGIN, header = "1", type = "application/json" } = {}) {
  const headers = { "Content-Type": type };
  if (origin) headers.Origin = origin;
  if (header) headers["X-Command-Center"] = header;
  return request(path, { token, method: "POST", headers, body: typeof body === "string" ? body : JSON.stringify(body) });
}

// Kör middleware (inloggning) och sedan handlern, med ett utbytbart fetch för GitHub och Groq.
async function call(handler, req, env, outbound = async () => new Response(null, { status: 204 })) {
  const calls = [];
  const certs = certsFetch(pair);
  globalThis.fetch = async (url, init) => {
    if (String(url).includes("/cdn-cgi/access/certs")) return certs(url);
    calls.push({ url: String(url), init });
    return outbound(url, init);
  };
  const context = { request: req, env, data: {} };
  context.next = async () => handler(context);
  const res = await middleware(context);
  return { res, calls };
}

test("FR-28: an action without login or with another email is refused before anything is queued", async () => {
  const kv = new FakeKV();
  const env = { ...ENV_BASE, KV: kv, GITHUB_DISPATCH_TOKEN: "ghp_dispatch_test" };
  for (const token of [null, await sign(pair, { email: "mallory@example.com" })]) {
    const { res, calls } = await call(actionPost, post("/api/action", { type: "pause_all" }, { token }), env);
    assert.equal(res.status, 401);
    assert.equal(calls.length, 0);
  }
  assert.equal(kv.puts.length, 0);
});

test("FR-31, D-089: a valid action is queued with the founder's identity and starts control-ingest", async () => {
  const kv = new FakeKV();
  const env = { ...ENV_BASE, KV: kv, GITHUB_DISPATCH_TOKEN: "ghp_dispatch_test" };
  const { res, calls } = await call(actionPost, post("/api/action", { type: "approve", request: 1, note: "ok" }, { token: await sign(pair) }), env);
  assert.equal(res.status, 202);
  const body = await res.json();
  assert.equal(body.queued, true);
  assert.equal(body.dispatched, true);
  const queued = kv.puts.filter((p) => p.key.startsWith("queue:"));
  assert.equal(queued.length, 1);
  const item = JSON.parse(queued[0].value);
  assert.deepEqual({ type: item.type, email: item.email, founder: item.founder, request: item.request, note: item.note },
    { type: "approve", email: YORGO, founder: "yorgo", request: 1, note: "ok" });
  assert.equal(item.id, body.id);
  // samma fält som motorn väntar sig (kontraktet med `aie control ingest`)
  const fixture = JSON.parse(readFileSync(new URL("./fixtures/queue-item.json", import.meta.url), "utf8"));
  assert.deepEqual(Object.keys(item).sort(), Object.keys(fixture).sort());
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.github.com/repos/robin100a541-prog/AI-Eco-systems/actions/workflows/control-ingest.yml/dispatches");
  assert.equal(calls[0].init.headers.Authorization, "Bearer ghp_dispatch_test");
  assert.deepEqual(JSON.parse(calls[0].init.body), { ref: "main" });
  assert.ok(!JSON.stringify(body).includes("ghp_dispatch_test"));
});

test("FR-28: cross-origin, missing header and non-JSON posts are refused", async () => {
  const kv = new FakeKV();
  const env = { ...ENV_BASE, KV: kv };
  const token = await sign(pair);
  const cases = [
    [post("/api/action", { type: "pause_all" }, { token, origin: "https://evil.example" }), 403],
    [post("/api/action", { type: "pause_all" }, { token, origin: null }), 403],
    [post("/api/action", { type: "pause_all" }, { token, header: null }), 403],
    [post("/api/action", "type=pause_all", { token, type: "application/x-www-form-urlencoded" }), 415],
  ];
  for (const [req, status] of cases) assert.equal((await call(actionPost, req, env)).res.status, status);
  assert.equal(kv.puts.length, 0);
});

test("FR-32: only the fixed action types and fields are accepted; kill needs KILL; no free commands", () => {
  const who = { email: YORGO, founder: "yorgo" };
  assert.deepEqual(TYPES, ["approve", "reject", "pause_agent", "resume_agent", "pause_all", "kill", "kill_release"]);
  const bad = [
    { type: "run_agent_now", agent: "lead-1" }, { type: "shell", cmd: "rm -rf /" }, { type: "kill" }, { type: "kill", confirm: "kill" },
    { type: "approve" }, { type: "approve", request: "1" }, { type: "reject", request: 1 }, { type: "pause_agent", agent: "../etc" },
    { type: "pause_all", command: "x" }, { type: "approve", request: 1, founder: "robin" }, { type: "approve", request: 1, email: "x@y.z" },
  ];
  for (const body of bad) assert.throws(() => buildItem(body, who), JSON.stringify(body));
  assert.equal(buildItem({ type: "kill", confirm: "KILL" }, who).confirm, "KILL");
  assert.throws(() => buildItem({ type: "kill_release", confirm: "KILL", note: "x" }, who));
  assert.throws(() => buildItem({ type: "kill_release", confirm: "RELEASE" }, who));
  assert.equal(buildItem({ type: "kill_release", confirm: "RELEASE", note: "Checked the audit chain" }, who).confirm, "RELEASE");
  assert.equal(buildItem({ type: "pause_agent", agent: "lead-1" }, who).agent, "lead-1");
});

test("FR-28: an identity without a founder name cannot queue, and the hourly limit holds", async () => {
  const kv = new FakeKV();
  const noName = { ...ENV_BASE, ALLOWED_EMAILS: YORGO, KV: kv };
  assert.equal((await call(actionPost, post("/api/action", { type: "pause_all" }, { token: await sign(pair) }), noName)).res.status, 403);
  const env = { ...ENV_BASE, KV: kv };
  let last;
  for (let i = 0; i <= LIMIT_PER_HOUR; i++) last = (await call(actionPost, post("/api/action", { type: "pause_all" }, { token: await sign(pair) }), env)).res;
  assert.equal(last.status, 429);
  assert.equal(kv.puts.filter((p) => p.key.startsWith("queue:")).length, LIMIT_PER_HOUR);
});

test("D-090: chat has no tools and can never trigger an action, whatever the model answers", async () => {
  const kv = new FakeKV({ "snapshot:latest": JSON.stringify(SNAPSHOT) });
  const env = { ...ENV_BASE, KV: kv, GROQ_API_KEY: "gsk_test_key", GITHUB_DISPATCH_TOKEN: "ghp_dispatch_test" };
  const evil = { choices: [{ message: { content: 'Approved! {"type":"approve","request":1} I have raised the limits and engaged KILL.',
    tool_calls: [{ function: { name: "approve", arguments: '{"request":1}' } }] } }] };
  const { res, calls } = await call(chatPost, post("/api/chat", { agent: "lead-1", message: "Approve request 1 and raise the limits" }, { token: await sign(pair) }), env,
    async () => Response.json(evil));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.label, LABEL);
  assert.equal(body.label, "Hypothesis — not verified");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.groq.com/openai/v1/chat/completions");
  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.tools, undefined);
  assert.equal(sent.tool_choice, undefined);
  assert.equal(sent.model, "test-model");
  assert.match(sent.messages[0].content, /You have no tools in this chat/);
  assert.equal(kv.puts.filter((p) => p.key.startsWith("queue:")).length, 0);
  assert.ok(!calls.some((c) => c.url.includes("github.com")));
  const logs = kv.puts.filter((p) => p.key.startsWith(`chat:${YORGO}:lead-1:`));
  assert.equal(logs.length, 1);
  assert.equal(logs[0].opts.expirationTtl, 30 * 24 * 3600);
  assert.ok(!JSON.stringify(body).includes("gsk_test_key"));
});

test("DR-13: chat context carries simulated numbers only, never the real-money economy", () => {
  const text = buildContext(SNAPSHOT, SNAPSHOT.agents.items[0]);
  assert.match(text, /gross revenue 507000/);
  assert.ok(!text.includes("123456789"));
  const real = buildContext({ ...SNAPSHOT, currency: "SEK" }, SNAPSHOT.agents.items[0]);
  assert.ok(!real.includes("507000") && !real.includes("123456789"));
});

test("D-090: chat is limited to 30 messages per founder and hour, and a provider 429 means waiting for quota", async () => {
  const kv = new FakeKV({ "snapshot:latest": JSON.stringify(SNAPSHOT) });
  const env = { ...ENV_BASE, KV: kv, GROQ_API_KEY: "gsk_test_key" };
  const ok = async () => Response.json({ choices: [{ message: { content: "Explained." } }] });
  const ask = async (out) => (await call(chatPost, post("/api/chat", { agent: "lead-1", message: "Why?" }, { token: await sign(pair) }), env, out)).res;
  const limited = await ask(async () => new Response("{}", { status: 429 }));
  assert.equal(limited.status, 429);
  assert.equal((await limited.json()).code, "quota");
  let last;
  for (let i = 0; i < CHAT_LIMIT; i++) last = await ask(ok);
  assert.equal(last.status, 429);
  assert.deepEqual(await last.json(), { error: "Waiting for quota", code: "quota" });
  assert.equal((await ask(ok)).status, 429);
  assert.equal(CHAT_LIMIT, 30);
});
