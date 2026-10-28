"""`python -m aie dev-agent run|open-pr` (D-050). Körs av `.github/workflows/dev-agent.yml`.

    python -m aie dev-agent run --branch claude/dev-agent-20261028-0900 --out result.json
    python -m aie dev-agent open-pr --result result.json      # kräver BOT_TOKEN och GITHUB_REPOSITORY

`run` gör ändringen och committar den lokalt på grenen. Den pushar inget och har ingen GitHub-token.
En körning utan ändring och utan nya grundarfrågor committar inget och öppnar ingen PR; rapporten
läggs i `.dev-agent-pending/` och följer med nästa PR som ändrar något.
`open-pr` öppnar PR:en och slår på automatisk merge. Kod 0 = lyckades, kod 1 = fel.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ..agents import AgentRegistry, AgentState
from ..audit import AuditLog
from ..authorization import AuthorizationEngine, load_permissions
from ..config import ConfigError, load_config
from ..llm import LLMGateway, ProviderRouter, QuotaLedger, load_providers
from ..memory import Database
from .agent import DevAgent, write_report
from .github import GitHub, GitHubError

AGENT_ID, CEO_ID = "dev-1", "dev-ceo"
# Rapporter från körningar utan ändring väntar här (sparas mellan körningar med actions/cache).
PENDING_DIR = ".dev-agent-pending"
_AUTHOR = [
    "-c",
    "user.name=aie-dev-agent",
    "-c",
    "user.email=dev-agent@users.noreply.github.com",
]


def bootstrap(
    config_dir: Path, project: Path, environ=os.environ, transport=None
) -> tuple[DevAgent, AuditLog]:
    """Bygger agenten i en egen databas (`<data_dir>/dev-agent/`), med gratisleverantörerna."""
    config = load_config(config_dir)
    permissions = load_permissions(config_dir)
    db = Database.open(project / config.system.data_dir / "dev-agent", "sim")
    audit = AuditLog(db)
    registry = AgentRegistry(permissions, db)
    founder = config.system.founders[0]
    for agent_id, role, manager in (
        (CEO_ID, "ceo", None),
        (AGENT_ID, "developer", CEO_ID),
    ):
        if registry.get(agent_id) is None:
            registry.register(
                agent_id, role, manager, founder, "utvecklaragenten (D-050)"
            )
            for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
                registry.transition(
                    agent_id, state, founder, "utvecklaragenten (D-050)"
                )
    engine = AuthorizationEngine(permissions, registry, "sim", audit)
    kwargs = {"transport": transport} if transport else {}
    slots, skipped = load_providers(config_dir, environ, **kwargs)
    # Bara namn, aldrig nycklar.
    print(
        "dev-agent: leverantörer på: "
        + (", ".join(slot.provider.name for slot in slots) or "inga")
        + "; avstängda: "
        + (", ".join(reason.split(":", 1)[0] for reason in skipped) or "inga")
    )
    gateway = LLMGateway(ProviderRouter(slots, QuotaLedger(db), audit), engine, audit)
    return DevAgent(project, AGENT_ID, gateway, engine, audit), audit


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def llm_summary(entries) -> str:
    """Vilken leverantör som svarade och HTTP-statusen för första Groq-anropet (ur audit-loggen)."""
    first_groq, used, failed = None, [], []
    for entry in entries:
        provider = entry.details.get("provider")
        if entry.action == "llm.call":
            used.append(provider)
            if provider == "groq" and first_groq is None:
                first_groq = "HTTP 200"
        elif entry.action == "llm.provider_failed":
            # Skälet är redan rensat från nycklar; prompten loggas aldrig.
            reason = entry.details.get("reason") or f"{provider}: HTTP {entry.details.get('status')}"
            failed.append(reason)
            if provider == "groq" and first_groq is None:
                first_groq = reason
    return (
        f"första Groq-anropet: {first_groq or 'inget'}; svarade: "
        + (", ".join(dict.fromkeys(used)) or "ingen")
        + (f"; fel: {', '.join(failed)}" if failed else "")
    )


def _step_summary(environ, text: str) -> None:
    """Rapporten syns i Actions-körningens sammanfattning när ingen PR öppnas."""
    path = environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def run(config_dir: Path, branch: str, out: Path, environ=os.environ) -> int:
    project = Path.cwd()
    try:
        agent, audit = bootstrap(config_dir, project, environ)
    except ConfigError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    result = agent.run()
    entries = list(audit.entries())
    report = write_report(project, result, [e.action for e in entries])
    llm = llm_summary(entries)
    print(f"dev-agent: {llm}")
    with report.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Språkmodell\n{llm}\n")
    repo = project.parent
    title = (
        f"dev-agent: {result.item.key}"
        if result.success and result.item
        else f"dev-agent: frågor {result.started_at[:16]}"
    )
    publish = result.success or bool(result.questions)
    pending = project / PENDING_DIR
    if not publish:
        # Ingen PR för en ren rapport: den sparas och följer med nästa PR som ändrar något.
        pending.mkdir(exist_ok=True)
        report.replace(pending / report.name)
        _step_summary(environ, (pending / report.name).read_text(encoding="utf-8"))
        out.write_text(
            json.dumps({"branch": branch, "committed": False, "success": False}),
            encoding="utf-8",
        )
        print(f"dev-agent: ingen ändring; {len(result.attempts)} försök; rapporten väntar på nästa PR")
        return 0
    earlier = sorted(pending.glob("dev-agent-*.md")) if pending.is_dir() else []
    for old in earlier:
        old.replace(report.parent / old.name)
    paths = [
        f"ai-enterprise/{p.removeprefix('ai-enterprise/')}"
        for p in result.changed_files
    ]
    paths += [str((report.parent / old.name).relative_to(repo)) for old in earlier]
    paths += [
        str(report.relative_to(repo)),
        "ai-enterprise/docs/bot-reports/dev-agent-state.json",
        "ai-enterprise/docs/QUESTIONS-FOR-FOUNDERS.md",
    ]
    _git(repo, "checkout", "-B", branch)
    _git(repo, "add", "--", *[p for p in paths if (repo / p).exists()])
    commit = _git(
        repo,
        *_AUTHOR,
        "commit",
        "-m",
        f"{title}\n\nUtvecklaragenten (D-050), gratismodell via LLMGateway.",
    )
    body = (
        report.read_text(encoding="utf-8")
        + (f"\n\nTidigare rapporter utan ändring följer med: {len(earlier)} st.\n" if earlier else "")
        + "\n\n_Skapad av utvecklaragenten (D-050). Mergas automatiskt när alla checkar är gröna._\n"
    )
    out.write_text(
        json.dumps(
            {
                "branch": branch,
                "committed": commit.returncode == 0,
                "success": result.success,
                "title": title,
                "body": body,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"{title}: {'ändring' if result.success else 'ingen ändring'}; {len(result.attempts)} försök"
    )
    return 0


def open_pr(result_file: Path, environ=os.environ, transport=None) -> int:
    data = json.loads(result_file.read_text(encoding="utf-8"))
    if not data.get("committed"):
        print("Inget att öppna en PR för.")
        return 0
    try:
        kwargs = {"transport": transport} if transport else {}
        gh = GitHub(
            environ.get("BOT_TOKEN", ""), environ.get("GITHUB_REPOSITORY", ""), **kwargs
        )
        pr = gh.open_pr(data["branch"], data["title"], data["body"])
    except (GitHubError, KeyError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    try:
        gh.enable_auto_merge(pr["node_id"])
    except (GitHubError, KeyError) as exc:
        # PR:en finns; den väntar då på en grundare i stället för att mergas automatiskt.
        print(f"VARNING: PR #{pr['number']} öppnad men automatisk merge gick inte att slå på: {exc}")
        return 0
    print(f"PR #{pr['number']} öppnad med automatisk merge: {pr.get('html_url', '')}")
    return 0
