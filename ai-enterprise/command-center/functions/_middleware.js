// Körs före varje funktion under /api/: ingen begäran når data eller åtgärder utan en giltig Access-identitet
// (Command Center, D-085). Statiska filer skyddas av Cloudflare Access i kanten.
import { verifyAccess } from "./_lib/access.js";
import { error } from "./_lib/http.js";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  if (!url.pathname.startsWith("/api/")) return context.next();
  try {
    context.data.identity = await verifyAccess(context.request, context.env);
  } catch (e) {
    return error(401, "unauthorized");
  }
  return context.next();
}
