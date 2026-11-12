// Gemensamma kontroller för POST: samma ursprung, egen header, JSON och en gräns per grundare och timme i KV.
import { error } from "./http.js";

export const HEADER = "X-Command-Center";

// Returnerar ett felsvar, eller null när begäran får fortsätta.
export function checkPost(request) {
  const url = new URL(request.url);
  const origin = request.headers.get("Origin");
  if (!origin || origin !== url.origin) return error(403, "cross-origin request refused");
  const site = request.headers.get("Sec-Fetch-Site");
  if (site && site !== "same-origin") return error(403, "cross-origin request refused");
  if (request.headers.get(HEADER) !== "1") return error(403, "missing header");
  if (!(request.headers.get("Content-Type") || "").startsWith("application/json")) return error(415, "json required");
  return null;
}

export async function readJson(request, maxBytes = 4096) {
  const text = await request.text();
  if (text.length > maxBytes) throw new Error("too large");
  const body = JSON.parse(text);
  if (body === null || typeof body !== "object" || Array.isArray(body)) throw new Error("not an object");
  return body;
}

// Räknare per grundare och timme. KV är inte atomär, så gränsen är ungefärlig, vilket räcker för två personer.
export async function rateLimit(kv, scope, founder, limit, now = Date.now()) {
  const key = `rate:${scope}:${founder}:${new Date(now).toISOString().slice(0, 13)}`;
  const used = parseInt((await kv.get(key)) || "0", 10) || 0;
  if (used >= limit) return { ok: false, remaining: 0 };
  await kv.put(key, String(used + 1), { expirationTtl: 2 * 3600 });
  return { ok: true, remaining: limit - used - 1 };
}
