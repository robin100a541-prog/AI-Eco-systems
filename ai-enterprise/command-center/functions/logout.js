// POST /logout: tar bort sessionscookien. Kräver session (middleware), samma ursprung och den egna headern.
import { clearCookie } from "../lib/session.js";
import { checkPost } from "../lib/guard.js";

export async function onRequestPost({ request }) {
  const refused = checkPost(request);
  if (refused) return refused;
  return new Response(JSON.stringify({ ok: true }), {
    status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Set-Cookie": clearCookie(), "Cache-Control": "no-store" } });
}
