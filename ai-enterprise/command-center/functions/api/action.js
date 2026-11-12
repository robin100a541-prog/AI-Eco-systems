// POST /api/action: tar emot ett knapptryck och lägger ett beslut i KV-kön (D-089). Ingenting ändras här.
// Motorn utför beslutet i workflowen control-ingest (`py -m aie control ingest`) via kärnans funktioner.
// Kontroller: verifierad Access-identitet (middleware), samma ursprung, egen header, gräns per timme och
// strikt validering. Inga skalkommandon, serveruppgifter eller fria körningar går att nå härifrån:
// bara åtgärdstyperna i TYPES, med fasta fält.
import { error, json } from "../../lib/http.js";
import { checkPost, rateLimit, readJson } from "../../lib/guard.js";

export const TYPES = ["approve", "reject", "pause_agent", "resume_agent", "pause_all", "kill", "kill_release"];
export const LIMIT_PER_HOUR = 20;
const QUEUE_TTL = 7 * 24 * 3600;
const AGENT_ID = /^[a-z][a-z0-9-]{1,39}$/;

// Returnerar den rensade posten eller kastar ett fel med en kort text.
export function buildItem(body, identity, now = new Date()) {
  const type = body.type;
  if (!TYPES.includes(type)) throw new Error("unknown action type");
  const allowed = { approve: ["request", "note"], reject: ["request", "note"], pause_agent: ["agent", "note"],
    resume_agent: ["agent", "note"], pause_all: ["note"], kill: ["confirm", "note"], kill_release: ["confirm", "note"] }[type];
  for (const key of Object.keys(body)) if (key !== "type" && !allowed.includes(key)) throw new Error(`unexpected field ${key}`);
  const item = { id: crypto.randomUUID(), type, email: identity.email, founder: identity.founder, at: now.toISOString(),
    note: typeof body.note === "string" ? body.note.slice(0, 300) : "" };
  if (type === "approve" || type === "reject") {
    if (!Number.isInteger(body.request) || body.request < 1) throw new Error("request must be a request number");
    if (type === "reject" && !item.note.trim()) throw new Error("a rejection needs a note");
    item.request = body.request;
  }
  if (type === "pause_agent" || type === "resume_agent") {
    if (typeof body.agent !== "string" || !AGENT_ID.test(body.agent)) throw new Error("agent must be an agent id");
    item.agent = body.agent;
  }
  if (type === "kill") {
    if (body.confirm !== "KILL") throw new Error("type KILL to confirm");
    item.confirm = "KILL";
  }
  if (type === "kill_release") {
    if (body.confirm !== "RELEASE") throw new Error("type RELEASE to confirm");
    if (!item.note.trim()) throw new Error("a release needs a reason");
    item.confirm = "RELEASE";
  }
  return item;
}

export async function dispatchIngest(env, fetchImpl = fetch) {
  if (!env.GITHUB_DISPATCH_TOKEN) return false;
  const repo = env.GITHUB_REPO || "robin100a541-prog/AI-Eco-systems";
  const res = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/control-ingest.yml/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json",
      "User-Agent": "command-center", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  return res.status === 204;
}

export async function onRequestPost({ request, env, data }) {
  const refused = checkPost(request);
  if (refused) return refused;
  if (!env.KV) return error(503, "KV binding missing");
  const identity = data.identity;
  if (!identity || !identity.founder) return error(403, "this identity has no founder name in ALLOWED_EMAILS");
  let item;
  try {
    item = buildItem(await readJson(request), identity);
  } catch (e) {
    return error(400, e.message);
  }
  const rate = await rateLimit(env.KV, "action", identity.email, LIMIT_PER_HOUR);
  if (!rate.ok) return error(429, "too many actions this hour");
  await env.KV.put(`queue:${item.at}:${item.id}`, JSON.stringify(item), { expirationTtl: QUEUE_TTL });
  let dispatched = false;
  try {
    dispatched = await dispatchIngest(env);
  } catch {
    dispatched = false; // beslutet ligger kvar i kön och tas vid nästa körning (control-ingest eller company-daily)
  }
  return json({ id: item.id, queued: true, dispatched }, 202);
}
