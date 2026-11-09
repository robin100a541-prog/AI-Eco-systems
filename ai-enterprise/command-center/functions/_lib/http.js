// Gemensamma svar för API:t. Allt är no-store: data cachas aldrig i webbläsaren eller i mellanled.

export const NO_STORE = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};

export function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...NO_STORE, ...extra } });
}

export function error(status, message) {
  return json({ error: message }, status);
}

// Snapshotens ålder i sekunder, eller null om den saknas.
export function ageSeconds(snapshot, now = Date.now()) {
  if (!snapshot || !snapshot.generated_at) return null;
  const at = Date.parse(snapshot.generated_at);
  return Number.isFinite(at) ? Math.max(0, Math.round((now - at) / 1000)) : null;
}
