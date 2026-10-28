"""Bedömning före start: initiativ från registret körs i flera scenarier (PR 6, D-058, D-048).

`assess_initiative()` bygger scenarierna automatiskt från initiativets och plattformens data i registret:

| Scenario | Efterfrågan | Returer | Krav för "redo" |
|---|---|---|---|
| `normal` | som registrerat | som registrerat | D-048: alla körningar med vinst efter allt, även sista perioden, medianmarginal, inget nödstopp |
| `pessimistic` | × 0,25 | × 2 | varje körning har vinst efter alla kostnader, avgifter, skatt och grundarnas tid |
| `zero_sales` | 0 | – | förlusten i pengar (utan grundarnas tid) är högst `MAX_SINGLE_EXPERIMENT_LOSS`, och inget nödstopp |

Varje scenario körs `min_runs` gånger med olika seed, i egna tillfälliga databaser, med samma agenter
och spärrar som vanligt. Kostnader som inte finns i marknadsmodellen dras av efteråt och redovisas:
grundarnas tid (timmar per vecka × `founder_hour_value_minor`), plattformens månadsavgift och startavgift.

**Antaganden märks alltid.** Belopp i USD räknas om med `usd_cent_in_sim_minor`. Okända avgifter ersätts
med försiktiga antaganden (`unknown_percent_fee_bp`, `unknown_fixed_fee_minor`), och skattespåret antas
vara C (Q-05 är öppen). Rapporten säger uttryckligen att resultatet bara gäller dessa antaganden.

**Känslighetsanalys:** ett överslag av väntat netto per dag när pris, konvertering, besökare, returer,
procentavgift och styckkostnad ändras ±20 % var för sig. Parametrarna sorteras efter hur mycket de påverkar.

Bedömningen sparas (`AssessmentStore`) med exakt de parametrar den gällde. Den blir giltig först när en
grundare godkänner den, och bara om den är redo (D-058).
"""
from __future__ import annotations

import statistics
import tempfile
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..config import ConfigError
from ..memory import Database
from .agents import build_gateway, ensure_org
from .cycle import WorkCycle
from .market import SimClock
from .readiness import _judge, _measure, load_readiness_rules
from .run import Simulation, require_sim
from .scenario import Initiative, Scenario

DISCLAIMER = ("Resultatet gäller bara de angivna antagandena. En simulering bevisar inte att initiativet fungerar "
              "i verkligheten (arbetsorder 02, D-058).")


@dataclass(frozen=True, slots=True)
class AssessmentRules:
    usd_cent_in_sim_minor: int
    unknown_percent_fee_bp: int
    unknown_fixed_fee_minor: int
    founder_hour_value_minor: int
    pessimistic_demand_bp: int
    pessimistic_refund_factor: int
    pause_after_days: int


def load_assessment_rules(config_dir: Path | str) -> AssessmentRules:
    path = Path(config_dir) / "simulation.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("assessment")
    except FileNotFoundError:
        raise ConfigError([f"simulation.toml saknas i {config_dir}"]) from None
    if not isinstance(data, dict):
        raise ConfigError(["simulation.toml: [assessment] saknas (D-058)"])
    values = {}
    errors = []
    for field in AssessmentRules.__dataclass_fields__:
        v = data.get(field)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            errors.append(f"simulation.toml: assessment.{field} ska vara ett heltal ≥ 0")
        values[field] = v
    if errors:
        raise ConfigError(errors)
    return AssessmentRules(**values)


def scenario_inputs(initiative_key: str, initiative: dict, platform: dict, rules: AssessmentRules):
    """Initiativ och plattform i registret → marknadens parametrar i SIM, och listan med antaganden."""
    assumptions = ["skattespår C antas (Q-05 är öppen)"]
    fees = platform["fees"]
    fx = rules.usd_cent_in_sim_minor if fees.get("currency") == "USD" else 1
    if fees.get("currency") == "USD":
        assumptions.append(f"1 USD-cent = {fx} öre i SIM (antagande om växelkurs)")

    def amount(value, name, unknown):
        if value is None:
            assumptions.append(f"{name} är okänd; {unknown} antas")
            return unknown
        return value * fx

    percent = fees.get("percent_bp")
    if percent is None:
        assumptions.append(f"procentavgiften är okänd; {rules.unknown_percent_fee_bp} bp antas")
        percent = rules.unknown_percent_fee_bp
    per_order = amount(fees.get("per_order_minor"), "avgiften per order", rules.unknown_fixed_fee_minor)
    per_listing = fees.get("per_listing_minor")
    per_listing = 0 if per_listing is None else per_listing * fx  # en annonsavgift per försäljning, om den finns
    monthly = fees.get("monthly_minor")
    monthly = 0 if monthly is None else monthly * fx
    if fees.get("monthly_minor") is None:
        assumptions.append("månadsavgiften är okänd; 0 antas")
    setup = 0 if fees.get("setup_minor") is None else fees["setup_minor"] * fx
    price_fx = rules.usd_cent_in_sim_minor if initiative.get("currency") == "USD" else 1
    demand = initiative["demand"]
    if str(demand.get("source", "")).lower().startswith("antagande"):
        assumptions.append("efterfrågan är ett antagande, inte uppmätt")
    market = Initiative(initiative_key, initiative["department"], "partnership",
                        initiative["price_minor"] * price_fx, initiative["unit_cost_minor"] * price_fx,
                        per_order + per_listing, percent, demand["visitors_per_day"], demand["conversion_bp"],
                        demand["refund_bp"])
    time_cost_per_day = round(initiative["founder_hours_per_week"] * rules.founder_hour_value_minor / 7)
    fixed = {"monthly_minor": monthly, "setup_minor": setup, "founder_time_per_day_minor": time_cost_per_day}
    return market, fixed, assumptions


def _scenario(name: str, market: Initiative, days: int) -> Scenario:
    return Scenario(name, f"bedömning före start: {name}", f"bedömning-{market.key}-{name}", days, "2027-01-01",
                    (market,), ())


def _run(config, config_dir, scenario: Scenario, runs: int, agents: str, rules) -> list:
    founder = sorted(config.system.founders)[0]
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(1, runs + 1):
            sc = replace(scenario, seed=f"{scenario.seed}/{n}")
            with Database.open(Path(tmp) / f"run-{n}", "sim") as db:
                from ..system import build_system

                clock = SimClock(sc.start_date)
                system = build_system(config, db, config_dir, clock=clock)
                ensure_org(system.registry, founder)
                sim = Simulation.start(system, config, sc, founder, clock)
                WorkCycle(sim, system, build_gateway(system, agents, config_dir)).run()
                results.append(_measure(system, config, sc, rules))
    return results


def _adjusted(run, fixed: dict, days: int) -> int:
    """Netto efter skatt minus kostnader som marknadsmodellen inte har: grundarnas tid och fasta avgifter."""
    fixed_cost = fixed["founder_time_per_day_minor"] * days + fixed["monthly_minor"] * days // 30 + fixed["setup_minor"]
    return run.after_tax_minor - fixed_cost


def sensitivity(market: Initiative, fixed: dict) -> list[dict]:
    """Väntat netto per dag (före skatt) när varje parameter ändras ±20 %, sorterat efter påverkan."""
    def daily(m: Initiative) -> float:
        orders = m.visitors * m.conversion_bp / 10_000
        per_order = m.price - m.unit_cost - m.fee_fixed - m.price * m.fee_bp / 10_000
        refunds = orders * m.refund_bp / 10_000 * m.price
        return orders * per_order - refunds - fixed["founder_time_per_day_minor"] - fixed["monthly_minor"] / 30

    base = daily(market)
    out = []
    for field in ("price", "conversion_bp", "visitors", "refund_bp", "fee_bp", "unit_cost"):
        low = daily(replace(market, **{field: int(getattr(market, field) * 0.8)}))
        high = daily(replace(market, **{field: int(getattr(market, field) * 1.2)}))
        out.append({"parameter": field, "minus_20": round(low), "plus_20": round(high),
                    "spread": round(abs(high - low))})
    out.sort(key=lambda r: -r["spread"])
    return [{"base_daily_minor": round(base)}, *out]


def assess_initiative(config, config_dir: Path | str, register, initiative_key: str, actor: str,
                      runs: int | None = None, days: int | None = None, agents: str = "scripted"):
    """Kör bedömningen och sparar den. Returnerar den sparade `Assessment`. Godkänns separat av en grundare."""
    require_sim(config)
    entry = register.get("initiative", initiative_key)
    if entry is None:
        raise ValueError(f"initiativet {initiative_key!r} finns inte i registret")
    platform = register.get("platform", entry.data["platform"])
    if platform is None:
        raise ValueError(f"plattformen {entry.data['platform']!r} finns inte i registret")
    readiness_rules = load_readiness_rules(config_dir)
    rules = load_assessment_rules(config_dir)
    runs = runs or readiness_rules.min_runs
    days = days or readiness_rules.min_days
    market, fixed, assumptions = scenario_inputs(initiative_key, entry.data, platform.data, rules)
    pessimistic = replace(market, conversion_bp=market.conversion_bp * rules.pessimistic_demand_bp // 10_000,
                          refund_bp=min(10_000, market.refund_bp * rules.pessimistic_refund_factor))
    zero = replace(market, conversion_bp=0)
    scenarios = {}
    reasons = []
    for name, m in (("normal", market), ("pessimistic", pessimistic), ("zero_sales", zero)):
        results = _run(config, config_dir, _scenario(name, m, days), runs, agents, readiness_rules)
        adjusted = [_adjusted(r, fixed, days) for r in results]
        entry_ = {"runs": [asdict(r) | {"adjusted_after_tax_minor": a} for r, a in zip(results, adjusted)],
                  "median_adjusted_after_tax_minor": statistics.median(adjusted) if adjusted else 0,
                  "daily_net_minor": round(statistics.median(r.net_minor for r in results) / days) if results else 0}
        if name == "normal":
            judged = _judge(name, agents, tuple(replace(r, after_tax_minor=a) for r, a in zip(results, adjusted)),
                            readiness_rules, runs, days)
            entry_["reasons"] = list(judged.reasons)
            reasons += [f"normalt scenario: {r}" for r in judged.reasons]
        elif name == "pessimistic":
            losing = sum(1 for a in adjusted if a <= 0)
            if losing:
                reasons.append(f"pessimistiskt scenario: {losing} av {len(adjusted)} körningar saknar vinst efter "
                               "alla kostnader, avgifter, skatt och grundarnas tid")
        else:
            limit = config.risk.max_single_experiment_loss
            worst = min((r.net_minor for r in results), default=0)
            if limit is None or -worst > limit.amount_minor:
                reasons.append(f"noll försäljning: förlusten {-worst} är större än MAX_SINGLE_EXPERIMENT_LOSS")
            if any(r.company_stop or r.kill_switch for r in results):
                reasons.append("noll försäljning: nödbromsen för hela företaget löste ut")
        scenarios[name] = entry_
    ready = not reasons
    result = {"ready": ready, "reasons": reasons, "scenarios": scenarios, "assumptions": assumptions,
              "fixed_costs": fixed, "sensitivity": sensitivity(market, fixed), "disclaimer": DISCLAIMER,
              "runs": runs, "days": days, "agents": agents}
    return register.assessments.record(actor, initiative_key, platform.key, entry.data, platform.data, result, ready)
