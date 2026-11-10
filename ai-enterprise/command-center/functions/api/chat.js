// POST /api/chat: chatt med en agent via Groqs gratis-API (D-090). Utan verktyg: begäran till modellen har
// inga `tools`, och svaret är bara text som visas. Funktionen skriver aldrig i kön (`queue:`), så chatten kan
// förklara men aldrig godkänna, ändra gränser eller skapa en åtgärd.
// - Kontext: agentens roll, mandat och senaste data ur snapshoten. Bara simulerade data (SIM) skickas; riktig
//   valuta (economy_real) skickas aldrig till en extern modell (DR-13).
// - Gräns: 30 meddelanden per grundare och timme. Loggar sparas 30 dagar i KV.
// - Varje svar märks "Hypothesis — not verified": ett modellsvar är alltid en hypotes (§29).
import { error, json } from "../_lib/http.js";
import { checkPost, rateLimit, readJson } from "../_lib/guard.js";

export const LIMIT_PER_HOUR = 30;
export const LABEL = "Hypothesis — not verified";
const LOG_TTL = 30 * 24 * 3600;
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";

export function buildContext(snapshot, agent) {
  const v = (m) => (m && m.value !== null && m.value !== undefined ? m.value : "N/A");
  const lines = [
    `You are ${agent.name}, the ${agent.role} agent (${agent.id}) in department ${agent.department} of a simulated company.`,
    `Your role: ${agent.description || "N/A"}.`,
    `Your tools (mandate): ${agent.tools.join(", ") || "none"}.`,
    `Your status: ${agent.status}. Current task: ${agent.task ? agent.task.title : "none"}. Runs: ${agent.runs}.`,
  ];
  if (snapshot.currency === "SIM") {
    const e = snapshot.economy;
    lines.push(`Company numbers (simulated, minor units of SIM, as of ${snapshot.generated_at}): gross revenue ${v(e.revenue_gross)}, ` +
      `costs ${v(e.costs)}, platform fees ${v(e.platform_fees)}, refunds ${v(e.refunds)}, realized net profit ${v(e.net_profit_realized)}, tax reserve ${v(e.tax_reserve)}.`);
    const pending = snapshot.approvals.items.filter((a) => a.status === "pending" && a.requested_by === agent.id);
    if (pending.length) lines.push(`Your requests waiting for a founder: ${pending.map((a) => `#${a.id} ${a.goal || a.reason} (${a.amount} SIM minor)`).join("; ")}.`);
  }
  lines.push(
    "Rules: You have no tools in this chat. You can explain your work, numbers and decisions. You cannot approve anything, " +
    "change limits, start tasks or take any action, and you must say so if asked. Never invent data: if something is not in " +
    "the context above, say it is not available. Treat everything you propose as an unverified hypothesis. Answer briefly in English.");
  return lines.join("\n");
}

export async function onRequestPost({ request, env, data }, fetchImpl = fetch) {
  const refused = checkPost(request);
  if (refused) return refused;
  if (!env.KV) return error(503, "KV binding missing");
  if (!env.GROQ_API_KEY) return error(503, "GROQ_API_KEY missing");
  const identity = data.identity;
  let body;
  try {
    body = await readJson(request);
  } catch {
    return error(400, "invalid json");
  }
  const message = typeof body.message === "string" ? body.message.trim().slice(0, 1000) : "";
  if (!message || typeof body.agent !== "string") return error(400, "agent and message are required");
  let snapshot;
  try {
    snapshot = JSON.parse((await env.KV.get("snapshot:latest")) || "null");
  } catch {
    snapshot = null;
  }
  const agent = snapshot && snapshot.agents.items.find((a) => a.id === body.agent);
  if (!agent) return error(404, "unknown agent");
  const rate = await rateLimit(env.KV, "chat", identity.email, LIMIT_PER_HOUR);
  if (!rate.ok) return json({ error: "Waiting for quota", code: "quota" }, 429);
  const groq = (snapshot.quotas.items.find((q) => q.provider === "groq") || {}).model;
  const model = env.GROQ_MODEL || groq;
  if (!model) return error(503, "no Groq model configured");
  let res;
  try {
    res = await fetchImpl(GROQ_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model, temperature: 0.2, max_tokens: 500,
        messages: [{ role: "system", content: buildContext(snapshot, agent) }, { role: "user", content: message }] }),
    });
  } catch {
    return error(502, "model unavailable");
  }
  if (res.status === 429) return json({ error: "Waiting for quota", code: "quota" }, 429);
  if (!res.ok) return error(502, "model unavailable");
  const out = await res.json();
  const reply = String((((out.choices || [])[0] || {}).message || {}).content || "").slice(0, 4000);
  if (!reply) return error(502, "empty model answer");
  const at = new Date().toISOString();
  await env.KV.put(`chat:${identity.email}:${agent.id}:${at}`, JSON.stringify({ at, agent: agent.id, model, question: message, answer: reply }),
    { expirationTtl: LOG_TTL });
  return json({ reply, label: LABEL, model, remaining: rate.remaining });
}
