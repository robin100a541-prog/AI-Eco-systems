// GET /api/me: vem som är inloggad, enligt den verifierade Access-JWT:n (middleware). Aldrig något annat.
import { json } from "../../lib/http.js";

export async function onRequestGet({ data }) {
  return json({ email: data.identity ? data.identity.email : null, founder: data.identity ? data.identity.founder : null, mode: "cloudflare" });
}
