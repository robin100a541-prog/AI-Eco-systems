// Hämtar data från API:t. Samma form i Cloudflare (functions/api/) och i den lokala servern (D1).
// Inga hemligheter här: inloggningen sköts av Cloudflare Access eller den lokala sessionen.

async function getJson(path) {
  const res = await fetch(path, { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } });
  if (res.status === 401 || res.status === 403 || (res.type === "opaqueredirect")) throw Object.assign(new Error("Not signed in"), { status: 401 });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).error || msg; } catch { /* inget JSON */ }
    throw Object.assign(new Error(msg), { status: res.status });
  }
  return res.json();
}

export const fetchSnapshot = () => getJson("/api/snapshot");
export const fetchGithub = () => getJson("/api/github");
export const fetchHealth = () => getJson("/api/health");
export const fetchMe = () => getJson("/api/me");

// Den lokala servern kräver dessutom sessionens CSRF-token (från /api/me). I molnet finns ingen sådan.
let csrf = null;
export function setCsrf(token) { csrf = token || null; }
const postHeaders = () => ({ "Content-Type": "application/json", "X-Command-Center": "1", ...(csrf ? { "X-CSRF-Token": csrf } : {}) });

// Knapptryck: läggs i kön (Del 4). Kräver same-origin och en egen header.
export async function postAction(body) {
  const res = await fetch("/api/action", {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: postHeaders(),
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* tomt */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { status: res.status });
  return data;
}

export async function postChat(body) {
  const res = await fetch("/api/chat", {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: postHeaders(),
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* tomt */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { status: res.status, data });
  return data;
}
