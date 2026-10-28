"""Plattforms- och initiativregistret (PR 4, arbetsorder 02, D-056, D-011, D-054).

Inget plattformsnamn står i koden. Plattformar och initiativ är **data**: de läggs in som versioner i
`registry_versions` (migration 29) och, för de första, från `config/registry/*.toml`.

**Plattform** (`PLATFORM_FIELDS`): namn, URL, typ (product/service/both), avgifter, valuta,
betalningsvillkor, momsansvar, DAC7, AI-regler, regler för automatisering och API, krav på konto och
id, utbetalningsvillkor, kritiska beroenden (till exempel betalningsleverantör), risker och källor med
datum. Det som inte är verifierat anges som `"okänt"` eller `null`. Ingenting gissas.

**Initiativ** (`INITIATIVE_FIELDS`): plattform, departement, produkt eller tjänst, beskrivning, pris,
styckkostnad, efterfrågeantaganden (med källa eller märkta `"antagande"`), grundarnas tid per vecka
och bedömningar (PR 6). Pris och kostnad är heltal i minsta enhet (D-006).

**Status:** `idea` → `investigated` → `reviewed` → `approved` → `active` / `paused` / `retired`.

| Steg | Vem | Krav |
|---|---|---|
| idea | grundare eller agent på nivå 1–3, eller i research | – |
| investigated | samma | agent: ett ärende i "Utred möjlighet" med Researchs fynd (D-011) |
| reviewed | grundare, Compliance eller CFO | agent: ärendet har passerat Compliance och CFO |
| approved | **bara grundare** | ärendet är godkänt, om ett finns; ett initiativ kräver en godkänd eller aktiv plattform |
| active, paused, retired | grundare; `paused` även systemet (PR 6) | `active` kräver `approved` eller `paused` |

Grundarna får lägga in redan utredda kanaler direkt (D-011: fram till Fas 3 fyllde grundarna i mallen).
Agenter föreslår och utreder, men godkänner aldrig. Varje ändring är en ny version med motivering, och
historiken finns kvar (§30).

`spend_block_reason(department, initiative)` är initiativspärren i budgetmotorn (F6, D-054). Ett
initiativ som inte finns, inte är godkänt eller aktivt, eller hör till ett annat departement ger nej.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..agents import ACTING_STATES, LEVEL_HEAD, AgentRegistry
from ..audit import AuditLog
from ..memory import Database

SYSTEM = "system:registry"
KINDS = ("platform", "initiative")
STATUSES = ("idea", "investigated", "reviewed", "approved", "active", "paused", "retired")
SPENDABLE = frozenset({"approved", "active"})
PLATFORM_FIELDS = ("name", "url", "type", "fees", "currency", "payment_terms", "vat_responsibility", "dac7",
                   "ai_rules", "automation_rules", "account_requirements", "payout_terms", "dependencies", "risks",
                   "sources")
INITIATIVE_FIELDS = ("platform", "department", "offering", "description", "price_minor", "unit_cost_minor",
                     "currency", "demand", "founder_hours_per_week")
FEE_FIELDS = ("per_order_minor", "percent_bp", "per_listing_minor", "monthly_minor", "setup_minor", "payout_minor",
              "currency", "notes")
DEMAND_FIELDS = ("visitors_per_day", "conversion_bp", "refund_bp", "source")
_TYPES = ("product", "service", "both")
_NEXT = {
    None: {"idea", "investigated"},
    "idea": {"investigated", "retired"},
    "investigated": {"reviewed", "investigated", "retired"},
    "reviewed": {"approved", "investigated", "retired"},
    "approved": {"active", "paused", "retired", "approved"},
    "active": {"paused", "retired"},
    "paused": {"active", "retired", "approved"},
    "retired": set(),
}
_OPPORTUNITY_KINDS = {"platform": ("channel",), "initiative": ("revenue", "market", "channel")}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Entry:
    kind: str
    key: str
    version: int
    status: str
    data: dict[str, Any]
    actor: str
    note: str
    opportunity_id: int | None
    at: str


class Register:
    def __init__(self, db: Database, registry: AgentRegistry, permissions, audit: AuditLog,
                 founders: frozenset[str], opportunities=None, clock: Callable[[], str] = _now) -> None:
        """`opportunities`: `OpportunityRegister`, för agenternas utredningar enligt D-011."""
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._opportunities = opportunities
        self._clock = clock

    # --- Ändra -----------------------------------------------------------------------------

    def record(self, actor: str, kind: str, key: str, status: str, data: dict[str, Any], note: str,
               opportunity_id: int | None = None) -> Entry:
        """En ny version. `data` ersätter hela innehållet; tidigare versioner finns kvar."""
        if kind not in KINDS:
            raise RegistryError(f"okänd typ {kind!r} (platform eller initiative)")
        if status not in STATUSES:
            raise RegistryError(f"okänd status {status!r} ({' → '.join(STATUSES)})")
        if not isinstance(key, str) or not key.strip() or key != key.strip().lower() or " " in key:
            raise RegistryError("nyckeln ska vara gemener utan mellanslag, till exempel plattform-a")
        if not note.strip():
            raise RegistryError("motivera ändringen")
        current = self.get(kind, key)
        allowed = _NEXT[current.status if current else None]
        if status not in allowed:
            raise RegistryError(f"{kind} {key}: {current.status if current else 'ny'} → {status} är inte tillåtet")
        problems = (self._validate_platform if kind == "platform" else self._validate_initiative)(data)
        if problems:
            raise RegistryError("; ".join(problems))
        self._require(actor, kind, status, opportunity_id, data)
        version = current.version + 1 if current else 1
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO registry_versions (kind, key, version, status, data, actor, note, opportunity_id, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, key, version, status, json.dumps(data, ensure_ascii=False, sort_keys=True), actor, note,
                 opportunity_id, self._clock()),
            )
        self._audit.append(actor, "registry.recorded", {"kind": kind, "entry": key, "version": version,
                                                        "status": status, "note": note,
                                                        "opportunity_id": opportunity_id})
        return self.get(kind, key)

    def set_status(self, actor: str, kind: str, key: str, status: str, note: str,
                   opportunity_id: int | None = None) -> Entry:
        current = self.get(kind, key)
        if current is None:
            raise RegistryError(f"{kind} {key} finns inte")
        return self.record(actor, kind, key, status, current.data, note, opportunity_id or current.opportunity_id)

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, kind: str, key: str, version: int | None = None) -> Entry | None:
        sql = ("SELECT kind, key, version, status, data, actor, note, opportunity_id, at FROM registry_versions "
               "WHERE kind = ? AND key = ?")
        params: tuple = (kind, key)
        if version is None:
            sql += " ORDER BY version DESC LIMIT 1"
        else:
            sql += " AND version = ?"
            params += (version,)
        row = self._db.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        k, key_, v, status, data, actor, note, opp, at = row
        return Entry(k, key_, v, status, json.loads(data), actor, note, opp, at)

    def history(self, kind: str, key: str) -> tuple[Entry, ...]:
        versions = [r[0] for r in self._db.connection.execute(
            "SELECT version FROM registry_versions WHERE kind = ? AND key = ? ORDER BY version", (kind, key))]
        return tuple(self.get(kind, key, v) for v in versions)

    def all(self, kind: str, status: str | None = None) -> tuple[Entry, ...]:
        keys = [r[0] for r in self._db.connection.execute(
            "SELECT DISTINCT key FROM registry_versions WHERE kind = ? ORDER BY key", (kind,))]
        entries = tuple(self.get(kind, k) for k in keys)
        return entries if status is None else tuple(e for e in entries if e.status == status)

    def spend_block_reason(self, department: str, initiative: str) -> str | None:
        """Initiativspärren i budgetmotorn (F6, D-054)."""
        entry = self.get("initiative", initiative)
        if entry is None:
            return f"initiativet {initiative!r} finns inte i initiativregistret (D-054)"
        if entry.status not in SPENDABLE:
            return f"initiativet {initiative!r} är {entry.status}, inte godkänt eller aktivt (D-054)"
        if entry.data.get("department") != department:
            return f"initiativet {initiative!r} hör till departementet {entry.data.get('department')!r} (D-054)"
        platform = self.get("platform", entry.data.get("platform", ""))
        if platform is None or platform.status not in SPENDABLE:
            return f"plattformen för {initiative!r} är inte godkänd eller aktiv (D-054)"
        return None

    # --- Internt ---------------------------------------------------------------------------

    def _require(self, actor: str, kind: str, status: str, opportunity_id, data) -> None:
        founder = actor in self._founders
        if status == "approved" or status in ("active", "retired") or (status == "paused" and actor != SYSTEM):
            if not founder:
                raise RegistryError(f"bara en grundare sätter {status} (D-011, D-049)")
        if status == "paused" and actor == SYSTEM:
            return
        if kind == "initiative" and status in ("approved", "active"):
            platform = self.get("platform", data.get("platform", ""))
            if platform is None or platform.status not in SPENDABLE:
                raise RegistryError("ett initiativ godkänns bara på en godkänd eller aktiv plattform")
        if founder:
            if opportunity_id is not None:
                self._opportunity(kind, opportunity_id)
            return
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise RegistryError(f"{actor!r} finns inte eller får inte agera just nu")
        mandate = self._permissions.roles[agent.role]
        if status in ("idea", "investigated") and mandate.level > LEVEL_HEAD and mandate.department != "research":
            raise RegistryError("förslag görs av research eller nivå 1–3")
        if status == "reviewed" and agent.role not in ("compliance", "cfo"):
            raise RegistryError("granskning görs av Compliance eller CFO (D-011)")
        if status == "idea":
            return
        opp = self._opportunity(kind, opportunity_id)
        steps = {step.stage for step in opp.steps}
        if status == "investigated" and "research" not in steps:
            raise RegistryError("ärendet saknar Researchs fynd (D-011)")
        if status == "reviewed" and not {"compliance", "cfo"} <= steps:
            raise RegistryError("ärendet har inte passerat både Compliance och CFO (D-011)")

    def _opportunity(self, kind: str, opportunity_id):
        if self._opportunities is None or opportunity_id is None:
            raise RegistryError("ange ärendet i \"Utred möjlighet\" (opportunity_id, D-011)")
        opp = self._opportunities.get(opportunity_id)
        if opp is None:
            raise RegistryError(f"ärende {opportunity_id} finns inte")
        if opp.kind not in _OPPORTUNITY_KINDS[kind]:
            raise RegistryError(f"ärende {opportunity_id} är {opp.kind}, inte {' eller '.join(_OPPORTUNITY_KINDS[kind])}")
        if opp.status == "rejected":
            raise RegistryError(f"ärende {opportunity_id} är avvisat")
        return opp

    @staticmethod
    def _validate_platform(data: dict) -> list[str]:
        problems = [f"plattformen saknar {k}" for k in PLATFORM_FIELDS if k not in data]
        unknown = [k for k in data if k not in PLATFORM_FIELDS]
        if unknown:
            problems.append(f"okända fält: {', '.join(unknown)}")
        if problems:
            return problems
        if data["type"] not in _TYPES:
            problems.append(f"type ska vara {', '.join(_TYPES)}")
        fees = data["fees"]
        if not isinstance(fees, dict) or set(fees) != set(FEE_FIELDS):
            problems.append(f"fees ska ha exakt {', '.join(FEE_FIELDS)}; okänt anges som null")
        else:
            for k in FEE_FIELDS[:-2]:
                v = fees[k]
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                    problems.append(f"fees.{k} ska vara ett heltal ≥ 0 i minsta enhet, eller null om okänt (D-006)")
        sources = data["sources"]
        if not isinstance(sources, list) or not sources or not all(
                isinstance(s, dict) and str(s.get("url", "")).startswith(("http://", "https://", "file:"))
                and isinstance(s.get("read_on"), str) for s in sources):
            problems.append("sources ska vara en lista med {url, read_on} (källa och datum)")
        if not isinstance(data["risks"], list) or not isinstance(data["dependencies"], list):
            problems.append("risks och dependencies ska vara listor")
        return problems

    @staticmethod
    def _validate_initiative(data: dict) -> list[str]:
        problems = [f"initiativet saknar {k}" for k in INITIATIVE_FIELDS if k not in data]
        unknown = [k for k in data if k not in (*INITIATIVE_FIELDS, "assessment")]
        if unknown:
            problems.append(f"okända fält: {', '.join(unknown)}")
        if problems:
            return problems
        if data["offering"] not in ("product", "service"):
            problems.append("offering ska vara product eller service")
        for k in ("price_minor", "unit_cost_minor"):
            v = data[k]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                problems.append(f"{k} ska vara ett heltal ≥ 0 i minsta enhet (D-006)")
        demand = data["demand"]
        if not isinstance(demand, dict) or set(demand) != set(DEMAND_FIELDS):
            problems.append(f"demand ska ha exakt {', '.join(DEMAND_FIELDS)}")
        elif not (isinstance(demand["source"], str) and demand["source"].strip()):
            problems.append('demand.source ska vara en källa eller "antagande"')
        hours = data["founder_hours_per_week"]
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours < 0:
            problems.append("founder_hours_per_week ska vara ett tal ≥ 0 (grundarnas tid är också en kostnad)")
        return problems
