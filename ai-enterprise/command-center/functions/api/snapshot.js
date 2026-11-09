// GET /api/snapshot: den senaste snapshoten ur KV, exakt som `py -m aie publish` laddade upp den.
// Samma data för båda grundarna; inget räknas om här (FR-29, D-085).
import { error, json } from "../_lib/http.js";

export async function onRequestGet({ env }) {
  if (!env.KV) return error(503, "KV binding missing");
  const raw = await env.KV.get("snapshot:latest");
  if (raw === null) return error(404, "no snapshot yet");
  return new Response(raw, {
    status: 200,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}
