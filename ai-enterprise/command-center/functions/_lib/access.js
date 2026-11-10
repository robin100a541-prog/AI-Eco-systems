// Cloudflare Access: verifierar JWT:n som Access lägger på varje begäran (Command Center, D-085).
// Access skyddar redan hela sidan i kanten. Det här är ett andra lager i funktionerna:
// signaturen kontrolleras mot teamets publika nycklar, liksom audience, utfärdare, giltighetstid
// och att mejladressen står i vitlistan ALLOWED_EMAILS. Bara Web Crypto används, inga paket.

const CERTS_TTL_MS = 10 * 60 * 1000;
let certsCache = { url: null, at: 0, keys: [] };

function b64urlToBytes(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function decodePart(s) {
  return JSON.parse(new TextDecoder().decode(b64urlToBytes(s)));
}

// ALLOWED_EMAILS = "yorgo=a@x.se,robin=b@y.se". Namnet före "=" är grundarens namn i kärnan (config/system.toml)
// och krävs för knapparna. En adress utan namn släpps in men kan inte lägga beslut i kön.
export function founderEmails(env) {
  const out = new Map();
  for (const part of String(env.ALLOWED_EMAILS || "").split(",")) {
    const [a, b] = part.split("=").map((x) => x.trim().toLowerCase());
    if (b) out.set(b, a);
    else if (a) out.set(a, null);
  }
  return out;
}

export function allowedEmails(env) {
  return [...founderEmails(env).keys()];
}

async function certs(env, fetchImpl) {
  const url = `https://${env.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`;
  if (certsCache.url === url && Date.now() - certsCache.at < CERTS_TTL_MS) return certsCache.keys;
  const res = await fetchImpl(url);
  if (!res.ok) throw new Error(`certs ${res.status}`);
  const body = await res.json();
  certsCache = { url, at: Date.now(), keys: body.keys || [] };
  return certsCache.keys;
}

export function resetCertsCache() {
  certsCache = { url: null, at: 0, keys: [] };
}

function tokenFrom(request) {
  const header = request.headers.get("Cf-Access-Jwt-Assertion");
  if (header) return header;
  const cookie = request.headers.get("Cookie") || "";
  const m = cookie.match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  return m ? m[1] : null;
}

// Returnerar { email } eller kastar ett fel med en kort orsak (som aldrig innehåller token).
export async function verifyAccess(request, env, { fetchImpl = fetch, now = Date.now() } = {}) {
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) throw new Error("access not configured");
  const allowed = allowedEmails(env);
  if (allowed.length === 0) throw new Error("no allowed emails");
  const token = tokenFrom(request);
  if (!token) throw new Error("missing token");
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("malformed token");
  let header, payload;
  try {
    header = decodePart(parts[0]);
    payload = decodePart(parts[1]);
  } catch {
    throw new Error("malformed token");
  }
  if (header.alg !== "RS256") throw new Error("bad alg");
  const keys = await certs(env, fetchImpl);
  const jwk = keys.find((k) => k.kid === header.kid);
  if (!jwk) throw new Error("unknown key");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlToBytes(parts[2]),
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!ok) throw new Error("bad signature");
  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(env.ACCESS_AUD)) throw new Error("bad audience");
  if (payload.iss !== `https://${env.ACCESS_TEAM_DOMAIN}`) throw new Error("bad issuer");
  const seconds = Math.floor(now / 1000);
  if (typeof payload.exp !== "number" || payload.exp < seconds) throw new Error("expired");
  if (typeof payload.nbf === "number" && payload.nbf > seconds + 60) throw new Error("not yet valid");
  const email = String(payload.email || "").toLowerCase();
  if (!allowed.includes(email)) throw new Error("email not allowed");
  return { email, founder: founderEmails(env).get(email) || null };
}
