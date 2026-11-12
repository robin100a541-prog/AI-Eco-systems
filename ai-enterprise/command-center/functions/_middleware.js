// Körs före ALLT: varje sökväg kräver en giltig session, också statiska filer och /api/health (D-094).
// Undantag: /login (sidan och inloggningen) och /login/ (inloggningssidans egna resurser).
// Saknas FOUNDER_CODE_HASHES eller SESSION_SECRET svarar varje sökväg 503: sidan visas aldrig öppen.
import { configured, readSession } from "../lib/session.js";
import { error } from "../lib/http.js";

const SECURITY = {
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

export const isPublic = (pathname) => pathname === "/login" || pathname.startsWith("/login/");

function plain(status, text) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", ...SECURITY } });
}

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  if (!configured(env)) return plain(503, "Not configured");
  if (isPublic(url.pathname)) return context.next();
  const identity = await readSession(env, request);
  if (!identity) {
    if (url.pathname.startsWith("/api/")) return error(401, "unauthorized");
    return new Response(null, { status: 302, headers: { Location: "/login", "Cache-Control": "no-store", ...SECURITY } });
  }
  context.data.identity = identity;
  const res = await context.next();
  if (!url.pathname.startsWith("/api/") && url.pathname !== "/logout") return res;
  // API-svar cachas aldrig, varken i webbläsaren eller i mellanled.
  const out = new Response(res.body, res);
  out.headers.set("Cache-Control", "no-store");
  out.headers.set("X-Content-Type-Options", "nosniff");
  return out;
}
