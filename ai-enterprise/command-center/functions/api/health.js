// GET /api/health: status, version och snapshotens ålder. Kräver inloggning som resten av API:t.
import { ageSeconds, json } from "../../lib/http.js";

export const STALE_SECONDS = 26 * 3600;

export async function onRequestGet({ env }) {
  let snapshot = null;
  if (env.KV) {
    try {
      snapshot = JSON.parse((await env.KV.get("snapshot:latest")) || "null");
    } catch {
      snapshot = null;
    }
  }
  const age = ageSeconds(snapshot);
  return json({
    status: !env.KV ? "misconfigured" : snapshot === null ? "no-data" : age > STALE_SECONDS ? "stale" : "ok",
    version: env.CF_PAGES_COMMIT_SHA ? env.CF_PAGES_COMMIT_SHA.slice(0, 7) : null,
    snapshot_generated_at: snapshot ? snapshot.generated_at : null,
    snapshot_age_seconds: age,
  });
}
