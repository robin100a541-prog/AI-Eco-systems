// /login: inloggningssidan (GET) och inloggningen (POST) med grundare och åtkomstkod (D-094).
// Sidan byggs här, så att den aldrig beror på en fil som kräver inloggning. Stilen ligger i /login/login.css.
import { checkCode, clearFailures, clientIp, createSession, isLocked, logAttempt, parseHashes, recordFailure, sessionCookie } from "../lib/session.js";

const HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function page(env, message = "", status = 200) {
  const options = Object.keys(parseHashes(env)).sort()
    .map((f) => `<option value="${esc(f)}">${esc(f.charAt(0).toUpperCase() + f.slice(1))}</option>`).join("");
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Sign in · Command center</title><link rel="stylesheet" href="/login/login.css"></head>
<body><main class="login">
<p class="label">Command center</p><h1>Sign in.</h1>
${message ? `<p class="notice" role="alert">${esc(message)}</p>` : ""}
<form method="post" action="/login">
<label for="founder">Founder</label><select id="founder" name="founder">${options}</select>
<label for="code">Access code</label><input id="code" name="code" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form></main></body></html>`;
  return new Response(html, { status, headers: HEADERS });
}

export async function onRequestGet({ env }) {
  return page(env);
}

export async function onRequestPost({ request, env }) {
  const url = new URL(request.url);
  if (request.headers.get("Origin") !== url.origin) return page(env, "The request was refused.", 403);
  if (!env.KV) return new Response("Not configured", { status: 503, headers: { ...HEADERS, "Content-Type": "text/plain; charset=utf-8" } });
  let founder = "", code = "";
  try {
    const form = await request.formData();
    founder = String(form.get("founder") || "").toLowerCase().slice(0, 40);
    code = String(form.get("code") || "").slice(0, 200);
  } catch {
    return page(env, "The request was refused.", 400);
  }
  const ip = clientIp(request);
  if (await isLocked(env.KV, ip, founder)) {
    await logAttempt(env.KV, { founder, ip, ok: false, reason: "locked" });
    return page(env, "Too many attempts. Try again in 15 minutes.", 429);
  }
  if (!(await checkCode(env, founder, code))) {
    await recordFailure(env.KV, ip, founder);
    await logAttempt(env.KV, { founder, ip, ok: false, reason: "wrong code" });
    return page(env, "Wrong founder or access code.", 401);
  }
  await clearFailures(env.KV, ip, founder);
  await logAttempt(env.KV, { founder, ip, ok: true });
  return new Response(null, { status: 303, headers: { Location: "/", "Set-Cookie": sessionCookie(await createSession(env, founder)), "Cache-Control": "no-store" } });
}
