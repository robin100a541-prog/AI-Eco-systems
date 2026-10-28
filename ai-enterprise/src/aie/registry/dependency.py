"""Skydd mot plattformsberoende (PR 7, D-059).

**Grupper.** Plattformar som delar ett kritiskt beroende räknas som en grupp och inte som oberoende,
till exempel samma betalningsleverantör. Beroendena står i plattformens `dependencies` i registret.
Två plattformar med `"stripe"` i listan hamnar i samma grupp, även om de har olika namn.

**Andel.** Varje grupps andel av intäkterna (realiserade intäkter minus återbetalningar) räknas de
senaste `WINDOW_DAYS` dagarna. Initiativet kopplas till plattformen via registret.

**Gränser** i `risk_limits.toml`:
- `MAX_PLATFORM_REVENUE_SHARE`: högsta andel för en grupp, i procent.
- `MIN_ACTIVE_PLATFORMS`: minsta antal oberoende grupper med godkända eller aktiva plattformar när
  företaget har intäkter.

När en grupp är på eller över gränsen gäller:
- **Varning** (`warnings()`, i revisionsloggen via `System.tick`).
- **Nya initiativ** på plattformar i gruppen kan inte godkännas eller aktiveras (`block_reason`).
- **Säkerhetsåtgärder** är alltid tillåtna: pausa, avveckla och sänka.
- **Rapport:** `report()` säger hur mycket som måste flyttas för att komma under gränsen.

Saknas en gräns när det finns intäkter stoppas nya initiativ (ER-02: en saknad gräns är aldrig
obegränsad). Utan intäkter finns ingen andel att mäta, och inget stoppas.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from ..ledger import EntryType, Status
from .registry import SPENDABLE

WINDOW_DAYS = 90
UNKNOWN = "okänd plattform"


def _today() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DependencyGuard:
    def __init__(self, register, ledger, limits, clock: Callable[[], str] = _today) -> None:
        self._register = register
        self._ledger = ledger
        self._limits = limits
        self._clock = clock

    def groups(self) -> dict[str, frozenset[str]]:
        """Plattform → gruppen den hör till (alla plattformar som delar ett beroende, direkt eller via andra)."""
        platforms = {e.key: {str(d).strip().lower() for d in e.data.get("dependencies", []) if str(d).strip()}
                     for e in self._register.all("platform")}
        parent = {k: k for k in platforms}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        owners: dict[str, str] = {}
        for key, deps in platforms.items():
            for dep in deps:
                if dep in owners:
                    parent[find(key)] = find(owners[dep])
                else:
                    owners[dep] = key
        members: dict[str, set[str]] = {}
        for key in platforms:
            members.setdefault(find(key), set()).add(key)
        return {key: frozenset(members[find(key)]) for key in platforms}

    def shares(self) -> dict[frozenset[str], int]:
        """Intäkt per grupp de senaste WINDOW_DAYS dagarna, i minsta enhet."""
        today = date.fromisoformat(self._clock()[:10])
        since = (today - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        groups = self.groups()
        out: dict[frozenset[str], int] = {}
        for e in self._ledger.entries(self._limits.currency):
            if e.status is not Status.SETTLED or e.entry_type not in (EntryType.REVENUE, EntryType.REFUND):
                continue
            if e.recorded_at[:10] < since:
                continue
            initiative = self._register.get("initiative", e.initiative)
            platform = initiative.data.get("platform") if initiative else None
            group = groups.get(platform, frozenset({UNKNOWN}))
            sign = -1 if e.entry_type is EntryType.REFUND else 1
            out[group] = out.get(group, 0) + sign * e.amount_minor
        return out

    def report(self) -> dict:
        shares = self.shares()
        total = sum(v for v in shares.values() if v > 0)
        limit = self._limits.max_platform_revenue_share
        rows = []
        for group, amount in sorted(shares.items(), key=lambda kv: -kv[1]):
            percent = round(amount * 100 / total, 1) if total > 0 else 0.0
            row = {"platforms": sorted(group), "revenue_minor": amount, "percent": percent}
            if limit is not None and total > 0 and percent >= float(limit):
                # hur mycket intäkt som måste komma från andra grupper för att andelen ska bli under gränsen
                needed = int(amount * 100 / float(limit)) - total + 1
                row["action"] = (f"över {limit} %: öka intäkten från andra, oberoende plattformar med minst {needed} "
                                 f"eller minska {', '.join(sorted(group))}; nya initiativ där stoppas (D-059)")
            rows.append(row)
        return {"total_revenue_minor": total, "groups": rows, "active_independent": self.active_independent(),
                "limits": {"MAX_PLATFORM_REVENUE_SHARE": None if limit is None else float(limit),
                           "MIN_ACTIVE_PLATFORMS": self._limits.min_active_platforms}}

    def active_independent(self) -> int:
        groups = self.groups()
        active = {groups[e.key] for e in self._register.all("platform") if e.status in SPENDABLE}
        return len(active)

    def warnings(self) -> list[str]:
        report = self.report()
        if report["total_revenue_minor"] <= 0:
            return []
        out = [f"plattformsberoende: {', '.join(r['platforms'])} står för {r['percent']} % av intäkterna. {r['action']}"
               for r in report["groups"] if "action" in r]
        minimum = self._limits.min_active_platforms
        if minimum is None:
            out.append("MIN_ACTIVE_PLATFORMS saknas i risk_limits.toml (ER-02, D-059)")
        elif report["active_independent"] < minimum:
            out.append(f"bara {report['active_independent']} oberoende aktiva plattformar; minst {minimum} krävs när "
                       "företaget har intäkter. Utred och godkänn en plattform utan gemensamt beroende (D-059)")
        if self._limits.max_platform_revenue_share is None:
            out.append("MAX_PLATFORM_REVENUE_SHARE saknas i risk_limits.toml (ER-02, D-059)")
        return out

    def block_reason(self, platform: str) -> str | None:
        """Skäl att inte godkänna eller aktivera ett nytt initiativ på plattformen, eller None."""
        shares = self.shares()
        total = sum(v for v in shares.values() if v > 0)
        if total <= 0:
            return None  # inga intäkter: ingen andel att mäta
        limit = self._limits.max_platform_revenue_share
        if limit is None:
            return "MAX_PLATFORM_REVENUE_SHARE saknas i risk_limits.toml; nya initiativ stoppas (ER-02, D-059)"
        group = self.groups().get(platform, frozenset({platform}))
        percent = shares.get(group, 0) * 100 / total
        if percent >= float(limit):
            return (f"{', '.join(sorted(group))} står för {percent:.1f} % av intäkterna, på eller över "
                    f"MAX_PLATFORM_REVENUE_SHARE {limit} %; inga nya initiativ där (D-059)")
        return None
