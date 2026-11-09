// GET /api/me: vem som är inloggad, enligt den verifierade Access-JWT:n (middleware). Aldrig något annat.
import { json } from "../_lib/http.js";

export async function onRequestGet({ data }) {
  return json({ email: data.identity ? data.identity.email : null, mode: "cloudflare" });
}
