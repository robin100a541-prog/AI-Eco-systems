// Testhjälp: hemligheter för testerna (inga riktiga), sessionscookies, en falsk KV och ett Pages-liknande context.
import { readFileSync } from "node:fs";
import { createSession, COOKIE } from "../lib/session.js";

export const VECTORS = JSON.parse(readFileSync(new URL("./fixtures/code-hash.json", import.meta.url), "utf8"));
export const ORIGIN = "https://aie-command-center.pages.dev";
export const ENV_BASE = {
  FOUNDER_CODE_HASHES: `${VECTORS.yorgo.line}, ${VECTORS.robin.line}`,
  SESSION_SECRET: "test-session-secret-0123456789abcdef0123456789abcdef",
};

export async function cookieFor(founder = "yorgo", env = ENV_BASE, now = Date.now()) {
  return `${COOKIE}=${await createSession(env, founder, now)}`;
}

export class FakeKV {
  constructor(init = {}) { this.map = new Map(Object.entries(init)); this.puts = []; }
  async get(key) { return this.map.has(key) ? this.map.get(key) : null; }
  async put(key, value, opts) { this.map.set(key, value); this.puts.push({ key, value, opts }); }
  async delete(key) { this.map.delete(key); }
  async list({ prefix = "" } = {}) { return { keys: [...this.map.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }; }
}

export function request(path, { cookie, method = "GET", headers = {}, body } = {}) {
  const h = new Headers(headers);
  if (cookie) h.set("Cookie", cookie);
  return new Request(`${ORIGIN}${path}`, { method, headers: h, body });
}

// Kör middleware och sedan handlern, som Pages gör. `handler` får samma context (med data.identity).
export async function callApi(middleware, handler, req, env) {
  const context = { request: req, env, data: {} };
  context.next = async () => handler(context);
  return middleware(context);
}

export function loginForm(founder, code, { origin = ORIGIN, ip = "203.0.113.7" } = {}) {
  const headers = { "Content-Type": "application/x-www-form-urlencoded", "CF-Connecting-IP": ip };
  if (origin) headers.Origin = origin;
  return request("/login", { method: "POST", headers, body: new URLSearchParams({ founder, code }).toString() });
}
