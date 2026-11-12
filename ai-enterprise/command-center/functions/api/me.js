// GET /api/me: vem som är inloggad, enligt sessionen (middleware, D-094). Aldrig något annat.
import { json } from "../../lib/http.js";

export async function onRequestGet({ data }) {
  return json({ founder: data.identity ? data.identity.founder : null, mode: "cloudflare" });
}
