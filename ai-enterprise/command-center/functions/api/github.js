// GET /api/github: senaste commits, PR:er och Actions-körningar, via en finkornig token som bara kan läsa
// (GITHUB_READ_TOKEN). Svaret cachas 60 sekunder i Cloudflares cache, så GitHubs gräns nås aldrig.
// Bara vitlistade fält går vidare till webbläsaren; tokenen lämnar aldrig funktionen.
import { error, json } from "../_lib/http.js";

const CACHE_SECONDS = 60;

function pick(list, fields) {
  return (Array.isArray(list) ? list : []).map((item) => {
    const out = {};
    for (const [name, get] of Object.entries(fields)) out[name] = get(item);
    return out;
  });
}

export async function loadGithub(env, fetchImpl = fetch) {
  const repo = env.GITHUB_REPO || "robin100a541-prog/AI-Eco-systems";
  const headers = {
    Authorization: `Bearer ${env.GITHUB_READ_TOKEN}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "command-center",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  const get = async (path) => {
    const res = await fetchImpl(`https://api.github.com/repos/${repo}/${path}`, { headers });
    if (!res.ok) throw new Error(`github ${path.split("?")[0]} ${res.status}`);
    return res.json();
  };
  const [commits, pulls, runs] = await Promise.all([
    get("commits?per_page=15"),
    get("pulls?state=all&per_page=15&sort=updated&direction=desc"),
    get("actions/runs?per_page=20"),
  ]);
  return {
    generated_at: new Date().toISOString(),
    commits: pick(commits, {
      id: (c) => `commit:${c.sha}`, sha: (c) => c.sha.slice(0, 7), message: (c) => (c.commit.message || "").split("\n")[0].slice(0, 140),
      author: (c) => (c.author && c.author.login) || c.commit.author.name, at: (c) => c.commit.author.date, url: (c) => c.html_url,
    }),
    pulls: pick(pulls, {
      id: (p) => `pr:${p.number}`, number: (p) => p.number, title: (p) => p.title.slice(0, 140), state: (p) => (p.merged_at ? "merged" : p.state),
      author: (p) => p.user && p.user.login, at: (p) => p.updated_at, url: (p) => p.html_url,
    }),
    runs: pick(runs.workflow_runs, {
      id: (r) => `run:${r.id}`, name: (r) => r.name, status: (r) => r.status, conclusion: (r) => r.conclusion,
      branch: (r) => r.head_branch, event: (r) => r.event, at: (r) => r.updated_at, url: (r) => r.html_url,
    }),
  };
}

export async function onRequestGet({ env, request }) {
  if (!env.GITHUB_READ_TOKEN) return error(503, "GITHUB_READ_TOKEN missing");
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const key = new Request(new URL("/api/github#cache", request.url).toString());
  if (cache) {
    const hit = await cache.match(key);
    if (hit) return new Response(hit.body, { headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  }
  let body;
  try {
    body = await loadGithub(env);
  } catch (e) {
    return error(502, "github unavailable");
  }
  if (cache) {
    await cache.put(key, new Response(JSON.stringify(body), { headers: { "Cache-Control": `max-age=${CACHE_SECONDS}`, "Content-Type": "application/json" } }));
  }
  return json(body);
}
