"""Scoutens dygnscykel (`aie scout run`, `.github/workflows/scout.yml`).

1. **Grundarnas beslut:** förslag som en grundare godkänt eller avvisat i godkännandekön blir `approved` eller
   `stopped`.
2. **Ny research:** samma kod som 7a (`pilot.discovery`). WebReader på tillåtna värdar och, om nycklarna finns,
   API:erna i `[[scout.apis]]` i `config/pilot.toml` när deras nycklar finns. Saknas en nyckel hoppas källan
   över, och det står i rapporten. Bara signaler vars citat finns ordagrant i källan sparas.
3. **Idéer och poäng:** modellen ger idéer med pris och uppskattad försäljning; koden räknar allt och
   poängsätter med 7a-mallen.
4. **Fördjupning:** de bästa idéerna får egna sökningar. Nya signaler kopplas i kod, när de handlar om
   samma sak som idén.
5. **Rensning:** svaga idéer och idéer som inte setts på `stale_days` dagar stoppas, med ett skäl.
6. **Förslag:** de starkaste som klarar minimikraven går till CEO via den vanliga beslutsprocessen (CFO och
   risk bedömer, tvist vid oenighet). Ett beslut blir en förfrågan i godkännandekön. Scouten skapar aldrig
   konton, godkänner aldrig villkor, betalar aldrig och publicerar aldrig (D-011, §6). Det gör en grundare.
7. **Rapporter:** `docs/opportunities/REGISTER.md`, på måndagar `weekly-ÅÅÅÅ-VV.md`, och en notis i
   `QUESTIONS-FOR-FOUNDERS.md` när något väntar på grundarna.

Ingen reserv: misslyckas researchen eller modellen sparas inget påhittat, och rapporten säger varför.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
import urllib.parse
from datetime import UTC, date, datetime
from pathlib import Path

from ..agents import AgentState
from ..pilot.discovery import (
    Opportunity,
    Signal,
    _words,
    ideate,
    load_settings,
    research,
    score,
)
from ..pilot.product import AgentStopped, Idea
from .register import TERMINAL, ScoutRegister, kind_to_type

SCOUT = "scout-1"
NOTICE_START, NOTICE_END = "<!-- scout:start -->", "<!-- scout:end -->"


class ScoutIdea(Idea):
    """En idé för beslutscykeln med scoutens egna, plattformsriktiga belopp (räknade i kod)."""

    __slots__ = ("_ev", "_fee", "_net")

    @property
    def fee_cents(self) -> int:
        return self._fee

    @property
    def net_per_sale_cents(self) -> int:
        return self._net

    @property
    def expected_net_90d_cents(self) -> int:
        return self._ev


def to_idea(o: Opportunity) -> ScoutIdea:
    idea = ScoutIdea(
        o.id,
        o.title,
        o.kind,
        o.market or "–",
        o.reasoning or o.title,
        o.signal_ids,
        "unverified",
        o.price_cents,
        o.upfront_cents,
        o.est_sales_90d,
        o.time_to_first_sale_days,
        "minst 3 försäljningar inom 60 dagar",
        "ingen försäljning på 60 dagar",
    )
    for name, value in (
        ("_fee", o.fee_cents),
        ("_net", o.net_cents),
        ("_ev", o.expected_value_cents),
    ):
        object.__setattr__(idea, name, value)
    return idea


def load_scout(config_dir: Path) -> dict:
    return tomllib.loads((Path(config_dir) / "pilot.toml").read_text(encoding="utf-8"))[
        "scout"
    ]


def ensure_scout(registry, founder: str) -> None:
    if registry.get(SCOUT) is not None:
        return
    registry.register(
        SCOUT, "scout", "lead-1", founder, "Opportunity Scout (Robin 2026-10-30)"
    )
    for state in (AgentState.CREATED, AgentState.TESTING, AgentState.ACTIVE):
        registry.transition(
            SCOUT, state, founder, "Opportunity Scout (Robin 2026-10-30)"
        )


def api_sources(cfg: dict, terms, environ) -> tuple[list[str], dict, list[str]]:
    urls, headers, notes = [], {}, []
    for api in cfg.get("apis", []):  # namn, nyckel och adress står i config/pilot.toml (D-056)
        name, env, template, header = api["name"], api["env"], api["url"], api["header"]
        key = environ.get(env)
        if not key:
            notes.append(f"{name}: {env} saknas, källan hoppades över")
            continue
        urls += [template.format(q=urllib.parse.quote_plus(t)) for t in terms[:3]]
        headers[urllib.parse.urlsplit(template).hostname] = {header: key}
    return urls, headers, notes


def _data(o: Opportunity, signals: dict[str, Signal], seen: str) -> dict:
    return {
        "kind": o.kind,
        "platform": o.platform,
        "language": o.language,
        "market": o.market,
        "price_cents": o.price_cents,
        "fee_cents": o.fee_cents,
        "net_cents": o.net_cents,
        "est_sales_90d": o.est_sales_90d,
        "expected_value_cents": o.expected_value_cents,
        "upfront_cents": o.upfront_cents,
        "hours_to_make": o.hours_to_make,
        "time_to_first_sale_days": o.time_to_first_sale_days,
        "scores": o.scores,
        "total": o.total,
        "qualified": o.qualified,
        "why_not": o.why_not,
        "reasoning": o.reasoning,
        "last_seen": seen,
        "sources": [
            {
                "id": i,
                "url": signals[i].url,
                "quote": signals[i].quote,
                "kind": signals[i].kind,
                "price_cents": signals[i].price_cents,
                "count": signals[i].count,
                "fetch_id": signals[i].fetch_id,
            }
            for i in o.signal_ids
            if i in signals
        ],
    }


def run_cycle(
    gov, reader, gateway, config_dir: Path, founder: str, today: date, environ=None
) -> dict:
    """Kör en cykel. Returnerar en sammanfattning för rapporterna."""
    environ = os.environ if environ is None else environ
    settings, cfg = load_settings(config_dir), load_scout(config_dir)
    reg = ScoutRegister(
        gov.registry._db if hasattr(gov.registry, "_db") else gov.audit._db, gov.audit
    )
    ensure_scout(gov.registry, founder)
    out = {
        "log": [],
        "notes": [],
        "new": [],
        "stopped": [],
        "proposed": [],
        "failed": None,
        "decided": [],
    }
    seen = today.isoformat()

    for e in reg.current():  # 1. grundarnas beslut i godkännandekön
        rid = e.data.get("request_id")
        if e.status == "proposed" and rid is not None:
            req = gov.queue.get(rid)
            if req is not None and req.status.value == "approved":
                reg.move(
                    founder,
                    e.key,
                    "approved",
                    f"godkänd av en grundare i godkännandekön (#{rid})",
                )
                out["decided"].append(e.key)
            elif req is not None and req.status.value == "rejected":
                reg.move(
                    founder,
                    e.key,
                    "stopped",
                    f"avvisad av en grundare i godkännandekön (#{rid})",
                )
                out["decided"].append(e.key)

    s = dataclasses.replace(settings, max_fetches=int(cfg["max_fetches"]))
    api_urls, headers, notes = api_sources(cfg, list(settings.search_terms), environ)
    out["notes"] += notes
    try:  # 2–3. research och idéer; ingen reserv
        signals = research(reader, gateway, s, out["log"], agent=SCOUT)
        signals += research(
            reader,
            gateway,
            dataclasses.replace(s, max_fetches=len(api_urls)),
            out["log"],
            agent=SCOUT,
            urls=api_urls,
            secret_headers=headers,
            start=len(signals) + 1,
        )
        if len(signals) < settings.min_signals:
            raise AgentStopped(
                f"researchen gav {len(signals)} belagda signaler, minst {settings.min_signals} krävs"
            )
        by_id = {x.id: x for x in signals}
        loss = gov.decisions._limits.max_single_experiment_loss.amount_minor // 10
        ideas = [
            score(i, by_id, settings, loss)
            for i in ideate(gateway, settings, signals, "", agent=SCOUT)
        ]
        ideas.sort(key=lambda i: (i.qualified, i.total), reverse=True)
        for o in ideas[: int(cfg["deepen_top"])]:  # 4. fördjupning, koppling i kod
            extra = research(
                reader,
                gateway,
                dataclasses.replace(s, max_fetches=int(cfg["deepen_fetches"])),
                out["log"],
                agent=SCOUT,
                start=len(by_id) + 1,
                urls=[
                    u.format(q=urllib.parse.quote_plus(o.title))
                    for u in settings.search_urls
                ],
            )
            words = _words(o.title)
            for x in extra:
                by_id[x.id] = x
                if words & _words(f"{x.title} {x.quote}"):
                    o.signal_ids = (*o.signal_ids, x.id)
            score(o, by_id, settings, loss)
        ideas.sort(key=lambda i: (i.qualified, i.total), reverse=True)
    except AgentStopped as exc:
        out["failed"] = str(exc)
        ideas, by_id = [], {}

    for o in ideas:  # register: nya, omräknade och svaga
        current = reg.get(o.id)
        data = _data(o, by_id, seen)
        if current is None:
            reg.record(
                SCOUT,
                o.id,
                kind_to_type(o.kind),
                o.market or o.kind,
                o.title,
                "new",
                data,
                "ny idé från scouten",
            )
            out["new"].append(o.id)
            current = reg.get(o.id)
        if current.status in TERMINAL or current.status in (
            "proposed",
            "approved",
            "testing",
        ):
            continue
        if o.qualified:
            reg.move(
                SCOUT,
                o.id,
                "scored",
                f"poäng {o.total}/100, klarar minimikraven",
                **data,
            )
        else:
            reg.move(SCOUT, o.id, "stopped", "svag: " + "; ".join(o.why_not), **data)
            out["stopped"].append(o.id)

    for e in reg.current():  # 5. inaktuella
        last = e.data.get("last_seen")
        if (
            e.status in ("new", "researching", "scored")
            and last
            and (today - date.fromisoformat(last)).days >= int(cfg["stale_days"])
        ):
            reg.move(SCOUT, e.key, "stopped", f"inaktuell: inte sedd sedan {last}")
            out["stopped"].append(e.key)

    ranked = sorted(
        (e for e in reg.current() if e.status == "scored" and e.data.get("qualified")),
        key=lambda e: e.data.get("total", 0),
        reverse=True,
    )
    for e in ranked[: int(cfg["propose_max"])]:  # 6. förslag till CEO
        o = next((i for i in ideas if i.id == e.key), None)
        if o is None:
            continue
        try:
            from ..pilot.decide import run_cycle as decide

            result = decide(
                gov,
                gateway,
                (to_idea(o),),
                founder,
                gov.decisions._limits,
                settings_usd_sek(config_dir),
            )
            request = gov.queue.submit_governance(
                "ceo-1",
                result.task_id,
                f"Scout-förslag {e.key}: godkänn ett test. Konto, villkor, pengar och "
                f"publicering görs bara av en grundare (D-011, §6).",
            )
            reg.move(
                SCOUT,
                e.key,
                "proposed",
                f"CEO-beslut efter CFO och risk; väntar på grundare (#{request.request_id})",
                request_id=request.request_id,
                decision_id=getattr(result.decision, "decision_id", None),
            )
            out["proposed"].append(e.key)
        except AgentStopped as exc:
            out["log"].append(
                f"{e.key}: beslutscykeln stoppade ({exc}); förslaget väntar till nästa körning"
            )
    out["profile"] = reg.profile()
    out["entries"] = reg.current()
    return out


def settings_usd_sek(config_dir: Path) -> float:
    return float(
        tomllib.loads((Path(config_dir) / "pilot.toml").read_text(encoding="utf-8"))[
            "usd_sek"
        ]
    )


def render_register(out: dict, today: date) -> str:
    entries = sorted(
        out["entries"], key=lambda e: (e.status in TERMINAL, -e.data.get("total", 0))
    )
    lines = [
        f"# Möjlighetsregistret (Opportunity Scout) {today.isoformat()}",
        "",
        ("Uppdateras varje dygn av `scout.yml`. Scouten skapar aldrig konton, godkänner aldrig villkor, "
        "betalar aldrig och publicerar aldrig; det gör en grundare (D-011, §6)."),
        "",
    ]
    if out["failed"]:
        lines += [
            f"**Researchen misslyckades i dag:** {out['failed']}. Inget påhittat sparades.",
            "",
        ]
    lines += [
        f"- Källor som hoppades över: {'; '.join(out['notes']) or 'inga'}",
        f"- Scoutens profil: {out['profile']}",
        "",
        "| Nyckel | Typ | Titel | Status | Poäng | Förv. värde USD | Källor | Senaste skäl |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| {e.key} | {e.type} | {e.title} | {e.status} | {e.data.get('total', '–')} | "
            f"{e.data.get('expected_value_cents', 0) / 100:.2f} | {len(e.data.get('sources', []))} | "
            f"{e.reason.replace('|', '/')} |"
        )
    lines += ["", "## Källor per möjlighet", ""]
    for e in entries:
        for src in e.data.get("sources", []):
            lines.append(
                f'- {e.key} {src["id"]} ({src["kind"]}): "{src["quote"]}" — {src["url"]}'
            )
    return "\n".join(lines) + "\n"


def render_weekly(out: dict, today: date) -> str:
    year, week, _ = today.isocalendar()
    live = [e for e in out["entries"] if e.status not in TERMINAL]
    top = sorted(live, key=lambda e: -e.data.get("total", 0))[:5]
    lines = [f"# Scouten vecka {year}-{week:02d}", "", "## Topp 5"]
    lines += [
        f"- {e.title} ({e.type}, {e.status}, poäng {e.data.get('total', '–')})"
        for e in top
    ] or ["- inga"]
    lines += [
        "",
        "## Nya",
        *([f"- {k}" for k in out["new"]] or ["- inga"]),
        "",
        "## Stoppade",
        *([f"- {k}" for k in out["stopped"]] or ["- inga"]),
        "",
        "## Behöver från grundarna",
        *[f"- {n}" for n in founder_items(out)],
    ]
    return "\n".join(lines) + "\n"


def founder_items(out: dict) -> list[str]:
    items = [
        f"godkänn eller avvisa förslaget {e.key} (godkännandekön #{e.data.get('request_id')})"
        for e in out["entries"]
        if e.status == "proposed"
    ]
    items += [n for n in out["notes"]]
    if out["failed"]:
        items.append(f"researchen misslyckades: {out['failed'][:200]}")
    return items or ["inget"]


def update_questions(path: Path, items: list[str], today: str) -> None:
    text = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else "# Frågor till grundarna\n"
    )
    block = (
        (
            f"{NOTICE_START}\n## Scouten väntar på grundarna ({today})\n"
            + "".join(f"- {i}\n" for i in items)
            + f"{NOTICE_END}\n"
        )
        if items and items != ["inget"]
        else ""
    )
    if NOTICE_START in text:
        head, rest = text.split(NOTICE_START, 1)
        text = head + block + rest.split(NOTICE_END, 1)[1].lstrip("\n")
    elif block:
        text = text.rstrip("\n") + "\n\n" + block
    path.write_text(text, encoding="utf-8")


def main(
    config_dir: Path,
    founder: str,
    mode: str,
    out_dir: Path,
    questions: Path,
    weekly: bool,
    today: date | None = None,
) -> int:
    from .. import runtime
    from ..governance.cli import build
    from ..pilot.cli import gateway_for
    from ..research.web import WebReader, load_limits
    from ..simulation.agents import ensure_org

    today = today or datetime.now(UTC).date()
    config = runtime._load(config_dir, console=False)
    with runtime._open(config) as db:
        gov = build(config, db, config_dir)
        ensure_org(gov.registry, founder)
        ensure_scout(gov.registry, founder)
        gateway = gateway_for(gov, db, mode, config_dir)
        reader = WebReader(db, gov.engine, gov.audit, load_limits(config_dir))
        out = run_cycle(gov, reader, gateway, config_dir, founder, today)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "REGISTER.md").write_text(render_register(out, today), encoding="utf-8")
    if weekly or today.weekday() == 0:
        year, week, _ = today.isocalendar()
        (out_dir / f"weekly-{year}-{week:02d}.md").write_text(
            render_weekly(out, today), encoding="utf-8"
        )
    update_questions(questions, founder_items(out), today.isoformat())
    print(render_register(out, today))
    return 3 if out["failed"] else 0
