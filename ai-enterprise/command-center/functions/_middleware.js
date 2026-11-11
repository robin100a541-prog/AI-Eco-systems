// Körs före varje funktion under /api/: ingen begäran når data eller åtgärder utan en giltig Access-identitet
// (Command Center, D-085). Statiska filer skyddas av Cloudflare Access i kanten.
import { verifyAccess } from "../lib/access.js";
import { error } from "../lib/http.js";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  if (!url.pathname.startsWith("/api/")) return context.next();
  try {
    context.data.identity = await verifyAccess(context.request, context.env);
  } catch (e) {
    return error(401, "unauthorized");
  }
  // API-svar cachas aldrig, varken i webbläsaren eller i mellanled (Del 6).
  const res = await context.next();
  const out = new Response(res.body, res);
  out.headers.set("Cache-Control", "no-store");
  out.headers.set("X-Content-Type-Options", "nosniff");
  return out;
}
