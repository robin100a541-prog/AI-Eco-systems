// Testhjälp: riktiga RSA-nycklar och signerade Access-JWT:er, en falsk KV och ett Pages-liknande context.
export const TEAM = "aie-test.cloudflareaccess.com";
export const AUD = "aud-command-center-test";
export const YORGO = "yorgo@example.com";
export const ROBIN = "robin@example.com";
export const ENV_BASE = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, ALLOWED_EMAILS: `${YORGO}, ${ROBIN}` };

const enc = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64url");

export async function keyPair(kid = "k1") {
  const pair = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  return { ...pair, jwk: { ...jwk, kid, alg: "RS256", use: "sig" }, kid };
}

export async function sign(pair, claims = {}, header = {}) {
  const now = Math.floor(Date.now() / 1000);
  const h = enc({ alg: "RS256", kid: pair.kid, typ: "JWT", ...header });
  const p = enc({ aud: [AUD], iss: `https://${TEAM}`, email: YORGO, exp: now + 600, iat: now, ...claims });
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", pair.privateKey, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${Buffer.from(sig).toString("base64url")}`;
}

export function certsFetch(...pairs) {
  return async (url) => {
    if (url === `https://${TEAM}/cdn-cgi/access/certs`) return new Response(JSON.stringify({ keys: pairs.map((p) => p.jwk) }));
    throw new Error(`unexpected fetch ${url}`);
  };
}

export class FakeKV {
  constructor(init = {}) { this.map = new Map(Object.entries(init)); this.puts = []; }
  async get(key) { return this.map.has(key) ? this.map.get(key) : null; }
  async put(key, value, opts) { this.map.set(key, value); this.puts.push({ key, value, opts }); }
  async delete(key) { this.map.delete(key); }
  async list({ prefix = "" } = {}) { return { keys: [...this.map.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }; }
}

export function request(path, { token, method = "GET", headers = {}, body } = {}) {
  const h = new Headers(headers);
  if (token) h.set("Cf-Access-Jwt-Assertion", token);
  return new Request(`https://command-center.pages.dev${path}`, { method, headers: h, body });
}

// Kör middleware och sedan handlern, som Pages gör.
export async function callApi(middleware, handler, req, env) {
  const context = { request: req, env, data: {}, next: async () => handler({ request: req, env, data: context.data }) };
  return middleware(context);
}
