// Egen inloggning för Command Center (D-094): en åtkomstkod per grundare och en signerad sessionscookie.
// Ersätter Cloudflare Access, som kräver betalkort. Bara Web Crypto används, inga paket.
//
// - FOUNDER_CODE_HASHES = "yorgo=pbkdf2_sha256$210000$<salt>$<hash>,robin=..." (skapas med
//   `py -m aie command-center make-code`). Koden finns aldrig i klartext någonstans.
// - PBKDF2-SHA256 med 210 000 iterationer. Cloudflare tillåter högst 100 000 per anrop, så beräkningen görs
//   i lika stora steg i kedja (3 x 70 000): utdata från ett steg är lösenordet till nästa, med samma salt.
//   `src/aie/dashboard/cc_auth.py` räknar exakt likadant.
// - Sessionen: "<payload>.<hmac>" signerad med SESSION_SECRET (HMAC-SHA256), giltig i 12 timmar,
//   i en cookie med HttpOnly, Secure och SameSite=Strict.
// - Låsning i KV: 5 felaktiga försök från samma IP eller mot samma grundare ger 15 minuters låsning.

export const COOKIE = "cc_session";
export const SESSION_SECONDS = 12 * 3600;
export const MIN_ITERATIONS = 210000;
export const MAX_PER_CALL = 100000;
export const MAX_FAILURES = 5;
export const LOCK_SECONDS = 15 * 60;
const LOG_TTL = 30 * 24 * 3600;
const enc = new TextEncoder();

const toHex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (hex) => new Uint8Array((hex.match(/../g) || []).map((h) => parseInt(h, 16)));
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
function fromB64url(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

export function configured(env) {
  return Boolean(env.FOUNDER_CODE_HASHES && env.SESSION_SECRET && String(env.SESSION_SECRET).length >= 32 &&
    Object.keys(parseHashes(env)).length > 0);
}

// "yorgo=pbkdf2_sha256$210000$salt$hash,robin=..." -> { yorgo: { iterations, salt, hash } }. Ogiltiga poster hoppas över.
export function parseHashes(env) {
  const out = {};
  for (const part of String(env.FOUNDER_CODE_HASHES || "").split(",")) {
    const i = part.indexOf("=");
    if (i < 1) continue;
    const name = part.slice(0, i).trim().toLowerCase();
    const [scheme, iterations, salt, hash] = part.slice(i + 1).trim().split("$");
    const n = parseInt(iterations, 10);
    if (scheme !== "pbkdf2_sha256" || !(n >= MIN_ITERATIONS) || !/^[0-9a-f]{32,}$/.test(salt || "") || !/^[0-9a-f]{64}$/.test(hash || "")) continue;
    out[name] = { iterations: n, salt, hash };
  }
  return out;
}

// PBKDF2-SHA256 i kedja, högst 100 000 iterationer per anrop. Returnerar hex (32 byte).
export async function deriveHash(code, saltHex, iterations) {
  const rounds = Math.ceil(iterations / MAX_PER_CALL);
  const per = iterations / rounds;
  if (!Number.isInteger(per)) throw new Error("iterations must divide evenly");
  const salt = fromHex(saltHex);
  let password = enc.encode(code);
  for (let r = 0; r < rounds; r++) {
    const key = await crypto.subtle.importKey("raw", password, "PBKDF2", false, ["deriveBits"]);
    password = new Uint8Array(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: per }, key, 256));
  }
  return toHex(password);
}

function sameText(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// true om koden stämmer för grundaren. En okänd grundare kostar lika mycket tid som en känd.
export async function checkCode(env, founder, code) {
  const stored = parseHashes(env)[String(founder || "").toLowerCase()];
  const target = stored || { iterations: MIN_ITERATIONS, salt: "00".repeat(16), hash: "0".repeat(64) };
  const got = await deriveHash(String(code || ""), target.salt, target.iterations);
  return Boolean(stored) && sameText(got, target.hash);
}

async function hmac(secret, text) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64url(await crypto.subtle.sign("HMAC", key, enc.encode(text)));
}

export async function createSession(env, founder, now = Date.now()) {
  const payload = b64url(enc.encode(JSON.stringify({ f: founder, exp: Math.floor(now / 1000) + SESSION_SECONDS })));
  return `${payload}.${await hmac(env.SESSION_SECRET, payload)}`;
}

// Returnerar { founder } eller null. Manipulerad, utgången eller okänd grundare ger null.
export async function readSession(env, request, now = Date.now()) {
  const m = (request.headers.get("Cookie") || "").match(new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`));
  if (!m) return null;
  const [payload, sig] = m[1].split(".");
  if (!payload || !sig || !sameText(sig, await hmac(env.SESSION_SECRET, payload))) return null;
  let data;
  try {
    data = JSON.parse(new TextDecoder().decode(fromB64url(payload)));
  } catch {
    return null;
  }
  if (typeof data.exp !== "number" || data.exp < Math.floor(now / 1000)) return null;
  if (!parseHashes(env)[data.f]) return null; // grundaren måste fortfarande finnas i FOUNDER_CODE_HASHES
  return { founder: data.f };
}

export const sessionCookie = (value) => `${COOKIE}=${value}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${SESSION_SECONDS}`;
export const clearCookie = () => `${COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0`;

export function clientIp(request) {
  return (request.headers.get("CF-Connecting-IP") || "unknown").slice(0, 64);
}

const lockKeys = (ip, founder) => [`lock:ip:${ip}`, `lock:founder:${String(founder || "").toLowerCase().slice(0, 40)}`];

export async function isLocked(kv, ip, founder, now = Date.now()) {
  for (const key of lockKeys(ip, founder)) {
    const state = JSON.parse((await kv.get(key)) || "null");
    if (state && state.until && state.until > now) return true;
  }
  return false;
}

// Räknar ett misslyckat försök för både IP och grundare. Vid det femte låses nyckeln i 15 minuter.
export async function recordFailure(kv, ip, founder, now = Date.now()) {
  for (const key of lockKeys(ip, founder)) {
    const state = JSON.parse((await kv.get(key)) || "null") || { count: 0 };
    const count = (state.until && state.until <= now ? 0 : state.count) + 1;
    const next = count >= MAX_FAILURES ? { count, until: now + LOCK_SECONDS * 1000 } : { count };
    await kv.put(key, JSON.stringify(next), { expirationTtl: LOCK_SECONDS });
  }
}

export async function clearFailures(kv, ip, founder) {
  for (const key of lockKeys(ip, founder)) await kv.delete(key);
}

// Varje inloggning och varje misslyckat försök loggas i KV i 30 dagar. Koden loggas aldrig.
export async function logAttempt(kv, { founder, ip, ok, reason }, now = Date.now()) {
  const at = new Date(now).toISOString();
  await kv.put(`authlog:${at}:${crypto.randomUUID().slice(0, 8)}`,
    JSON.stringify({ at, founder: String(founder || "").slice(0, 40), ip, ok, reason: reason || null }), { expirationTtl: LOG_TTL });
}
