"""Incidentrapporter (Fas 5a, FR-15, konstitutionen §28, D-035).

En incident har alla 16 fält i §28. Två fylls i automatiskt (ID och datum). Resten fylls i
efter hand av dem som utreder:

| # | Fält (§28) | Nyckel | Värde |
|---|---|---|---|
| 1 | Incident-ID | `incident_id` | automatiskt |
| 2 | Datum | `date` | automatiskt (när incidenten öppnades, UTC) |
| 3 | Ansvarigt departement | `department` | text |
| 4 | Involverade agenter | `agents` | lista med agent-ID |
| 5 | Ursprungligt mål | `goal` | text |
| 6 | Ursprunglig prognos | `forecast` | text |
| 7 | Genomförda åtgärder | `actions` | text |
| 8 | Faktiskt utfall | `outcome` | text |
| 9 | Ekonomisk påverkan | `economic_impact` | `{"amount_minor": heltal, "currency": "SIM"}` (D-006) |
| 10 | Avvikelse från prognosen | `deviation` | text |
| 11 | Identifierad grundorsak | `root_cause` | text |
| 12 | Bidragande faktorer | `contributing` | text |
| 13 | Korrigerande åtgärd | `corrective` | text |
| 14 | Föreslagen förebyggande åtgärd | `preventive` | text |
| 15 | Ansvarig för uppföljning | `follow_up_owner` | agent-ID, `role:<roll>` eller grundare |
| 16 | Resultat av efterföljande verifiering | `verification` | text |

Regler:
- **Inget raderas eller skrivs om.** Varje fält är en append-only post (migration 18). Att ändra ett
  ifyllt fält är en **rättelse**: en ny post som pekar på den gamla och har en motivering. Historiken finns kvar.
- **Varje stopp blir en incident.** `sync()` skapar en incident för varje stop-loss-utlösning,
  nödstopp och inträde i skyddat driftläge som saknar en. Stoppen anropar `sync()` själva
  när de har kopplats ihop (`incidents=`).
- **Den som hittar felet straffas inte** (§31, §33). `reported_by` hålls isär från `agents`.
  Rapportören räknas aldrig som involverad, och prestationsmätningen (5c) ser rapporten som ett bidrag.
- **Vem skriver:** grundarna, rapportören och aktiva agenter på nivå 1–3 (CEO, kontrollfunktioner,
  departementschefer). Alla aktiva agenter, även arbetsagenter, kan *öppna* en incident.
- **Oberoende verifiering:** fält 16 kan bara fyllas i när fält 3–15 finns, och inte av den som är
  ansvarig för uppföljningen (fält 15).
- Allt loggas i revisionsloggen.
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

SYSTEM = "system:incidents"
FIELDS: tuple[tuple[str, str], ...] = (
    ("incident_id", "Incident-ID"),
    ("date", "Datum"),
    ("department", "Ansvarigt departement"),
    ("agents", "Involverade agenter"),
    ("goal", "Ursprungligt mål"),
    ("forecast", "Ursprunglig prognos"),
    ("actions", "Genomförda åtgärder"),
    ("outcome", "Faktiskt utfall"),
    ("economic_impact", "Ekonomisk påverkan"),
    ("deviation", "Avvikelse från prognosen"),
    ("root_cause", "Identifierad grundorsak"),
    ("contributing", "Bidragande faktorer"),
    ("corrective", "Korrigerande åtgärd"),
    ("preventive", "Föreslagen förebyggande åtgärd"),
    ("follow_up_owner", "Ansvarig för uppföljning"),
    ("verification", "Resultat av efterföljande verifiering"),
)
AUTOMATIC = frozenset({"incident_id", "date"})
WRITABLE = tuple(k for k, _ in FIELDS if k not in AUTOMATIC)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class IncidentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FieldEntry:
    entry_id: int
    field: str
    value: Any
    note: str
    actor: str
    corrects: int | None
    at: str


@dataclass(frozen=True, slots=True)
class Incident:
    incident_id: int
    source: str
    title: str
    reported_by: str
    opened_at: str
    history: tuple[FieldEntry, ...] = ()

    @property
    def fields(self) -> dict[str, Any]:
        """Aktuellt värde per fält: den senaste posten, så att rättelser gäller."""
        values: dict[str, Any] = {"incident_id": self.incident_id, "date": self.opened_at[:10]}
        for entry in self.history:
            values[entry.field] = entry.value
        return values

    @property
    def missing(self) -> tuple[str, ...]:
        current = self.fields
        return tuple(k for k, _ in FIELDS if k not in current)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def involved(self) -> tuple[str, ...]:
        return tuple(self.fields.get("agents", ()))

    def as_report(self) -> list[tuple[str, Any]]:
        """De 16 fälten i §28:s ordning, med `None` för det som saknas."""
        current = self.fields
        return [(label, current.get(key)) for key, label in FIELDS]


class IncidentLog:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        clock: Callable[[], str] = _now,
    ) -> None:
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._clock = clock

    # --- Öppna och fylla i -----------------------------------------------------------------

    def open(self, actor: str, title: str, source: str | None = None, **initial: Any) -> Incident:
        if actor != SYSTEM:
            self._require_acting(actor)
        if not title.strip():
            raise IncidentError("en incident behöver en rubrik")
        if source is not None and self._by_source(source) is not None:
            raise IncidentError(f"det finns redan en incident för {source}")
        for key, value in initial.items():
            self._validate(key, value)
        now = self._clock()
        with self._db.transaction() as tx:
            if source is None:
                n = tx.execute("SELECT COALESCE(MAX(incident_id), 0) + 1 FROM incidents").fetchone()[0]
                source = f"manual:{n}"
            cursor = tx.execute(
                "INSERT INTO incidents (source, title, reported_by, opened_at) VALUES (?, ?, ?, ?)",
                (source, title, actor, now),
            )
            incident_id = cursor.lastrowid
            for key, value in initial.items():
                self._insert(tx, incident_id, key, value, "", actor, None, now)
        self._audit.append(actor, "incident.opened", {"incident_id": incident_id, "source": source, "title": title,
                                                      "fields": sorted(initial)})
        return self.get(incident_id)

    def record(self, actor: str, incident_id: int, field: str, value: Any, note: str = "") -> Incident:
        """Fyller i ett fält. Finns fältet redan blir det en rättelse, som kräver motivering."""
        incident = self._require(incident_id)
        self._require_writer(actor, incident)
        self._validate(field, value)
        previous = next((e for e in reversed(incident.history) if e.field == field), None)
        if previous is not None and not note.strip():
            raise IncidentError(f"{field} är redan ifyllt; en rättelse kräver en motivering")
        if field == "verification":
            others = [k for k in WRITABLE if k != "verification" and k not in incident.fields]
            if others:
                raise IncidentError(f"verifieringen görs sist; saknas: {', '.join(others)}")
            if actor == incident.fields.get("follow_up_owner"):
                raise IncidentError("den som ansvarar för uppföljningen kan inte själv verifiera den (§28)")
        with self._db.transaction() as tx:
            self._insert(tx, incident_id, field, value, note, actor, previous.entry_id if previous else None,
                         self._clock())
        self._audit.append(actor, "incident.corrected" if previous else "incident.recorded",
                           {"incident_id": incident_id, "field": field, "note": note})
        return self.get(incident_id)

    # --- Automatiskt från stoppen ----------------------------------------------------------

    def sync(self) -> tuple[Incident, ...]:
        """Skapar en incident för varje stopp som saknar en. Säkert att anropa hur ofta som helst."""
        created: list[Incident] = []
        for source, title, fields in self._stop_events():
            if self._by_source(source) is None:
                created.append(self.open(SYSTEM, title, source, **fields))
        return tuple(created)

    def _stop_events(self):
        execute = self._db.connection.execute
        for trip_id, kind, value, name, measured, limit, currency, exposure, notified, at in execute(
            "SELECT trip_id, scope_kind, scope_value, limit_name, measured, limit_value, currency, exposure, notified, "
            "tripped_at FROM stop_loss_trips ORDER BY trip_id"
        ):
            exp = json.loads(exposure)
            fields: dict[str, Any] = {
                "actions": "nya åtaganden blockerades automatiskt (ER-13, §26); förpliktelser listade: "
                           f"{exp['pending_entry_ids']}",
                "outcome": f"{name} nådd för {kind} {value}: {measured} ≥ {limit}",
                "economic_impact": {"amount_minor": exp["pending_outflow_minor"], "currency": currency},
                "follow_up_owner": "role:cro",
            }
            if kind == "department":
                fields["department"] = value
            yield f"stoploss:{trip_id}", f"Stop-loss: {name} ({kind} {value})", fields
        for event_id, actor, reason in execute(
            "SELECT id, actor, reason FROM kill_switch_events WHERE event = 'engaged' ORDER BY id"
        ):
            yield (f"kill:{event_id}", f"Nödstopp aktiverat av {actor}",
                   {"actions": f"nödstopp aktiverat av {actor} (SR-07): {reason}", "follow_up_owner": "founders"})
        for event_id, reasons in execute(
            "SELECT id, reasons FROM operating_mode_events WHERE event = 'entered' ORDER BY id"
        ):
            yield (f"mode:{event_id}", "Skyddat driftläge",
                   {"actions": "skyddat driftläge (SR-08): " + "; ".join(json.loads(reasons)),
                    "follow_up_owner": "founders"})

    # --- Frågor ----------------------------------------------------------------------------

    def get(self, incident_id: int) -> Incident | None:
        row = self._db.connection.execute(
            "SELECT incident_id, source, title, reported_by, opened_at FROM incidents WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        history = tuple(
            FieldEntry(eid, field, payload["v"], payload["note"], actor, corrects, at)
            for eid, field, value, actor, corrects, at in self._db.connection.execute(
                "SELECT id, field, value, actor, corrects, at FROM incident_entries WHERE incident_id = ? ORDER BY id",
                (incident_id,),
            )
            for payload in (json.loads(value),)
        )
        return Incident(*row, history=history)

    def all(self) -> tuple[Incident, ...]:
        ids = [r[0] for r in self._db.connection.execute("SELECT incident_id FROM incidents ORDER BY incident_id")]
        return tuple(self.get(i) for i in ids)

    def open_incidents(self) -> tuple[Incident, ...]:
        """Incidenter som ännu saknar något av de 16 fälten."""
        return tuple(i for i in self.all() if not i.complete)

    def reported_by(self, agent_id: str) -> tuple[Incident, ...]:
        return tuple(i for i in self.all() if i.reported_by == agent_id)

    def involving(self, agent_id: str) -> tuple[Incident, ...]:
        """Incidenter där agenten är involverad. Att bara ha rapporterat räknas inte (§31, §33)."""
        return tuple(i for i in self.all() if agent_id in i.involved)

    # --- Internt ---------------------------------------------------------------------------

    def _by_source(self, source: str) -> int | None:
        row = self._db.connection.execute("SELECT incident_id FROM incidents WHERE source = ?", (source,)).fetchone()
        return row[0] if row else None

    def _require(self, incident_id: int) -> Incident:
        incident = self.get(incident_id)
        if incident is None:
            raise IncidentError(f"incident {incident_id} finns inte")
        return incident

    def _require_acting(self, actor: str):
        if actor in self._founders:
            return None
        agent = self._registry.get(actor)
        if agent is None or agent.state not in ACTING_STATES:
            raise IncidentError(f"{actor!r} finns inte eller får inte agera just nu")
        return agent

    def _require_writer(self, actor: str, incident: Incident) -> None:
        if actor in self._founders or actor == SYSTEM:
            return
        agent = self._require_acting(actor)
        if actor == incident.reported_by:
            return
        if self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise IncidentError("bara grundare, rapportören och nivå 1–3 fyller i en incident")

    def _validate(self, field: str, value: Any) -> None:
        if field in AUTOMATIC:
            raise IncidentError(f"{field} fylls i automatiskt")
        if field not in WRITABLE:
            raise IncidentError(f"okänt fält {field!r} (fälten i §28: {', '.join(WRITABLE)})")
        if field == "agents":
            if not isinstance(value, (list, tuple)) or not value or not all(isinstance(a, str) and a for a in value):
                raise IncidentError("agents måste vara en lista med agent-ID")
            unknown = [a for a in value if self._registry.get(a) is None]
            if unknown:
                raise IncidentError(f"okända agenter: {unknown}")
        elif field == "economic_impact":
            ok = (isinstance(value, dict) and set(value) == {"amount_minor", "currency"}
                  and isinstance(value["amount_minor"], int) and not isinstance(value["amount_minor"], bool)
                  and isinstance(value["currency"], str) and len(value["currency"]) == 3)
            if not ok:
                raise IncidentError('economic_impact måste vara {"amount_minor": heltal, "currency": "SIM"} (D-006)')
        elif not isinstance(value, str) or not value.strip():
            raise IncidentError(f"{field} måste vara en icke-tom text")

    @staticmethod
    def _insert(tx, incident_id, field, value, note, actor, corrects, at) -> None:
        if isinstance(value, tuple):
            value = list(value)
        tx.execute(
            "INSERT INTO incident_entries (incident_id, field, value, actor, corrects, at) VALUES (?, ?, ?, ?, ?, ?)",
            (incident_id, field, json.dumps({"v": value, "note": note}, ensure_ascii=False), actor, corrects, at),
        )
