"""Versionerade strategier och agentversioner (Fas 5e, FR-18, konstitutionen §30 och §53, D-039).

En strategi (till exempel `etsy-prissättning`) eller en agentversion (`agent:<id>`: roll, modell,
instruktioner) sparas som numrerade versioner med innehåll (JSON-objekt), motivering och vilka
lärdomar ändringen bygger på. Den senaste versionen gäller.

Regler:
- **Inget skrivs om** (migration 24). `restore()` återställer en tidigare version genom att skapa en ny
  version med samma innehåll som pekar på den återställda (`restores`). Historiken finns alltid kvar (§53).
- **Obligatoriska ändringar** (`mandatory=True`) ändrar gemensamma operativa regler. De kräver minst en
  lärdom, och alla lärdomar som anges måste vara godkända operativa regler (`LessonRegistry.require_rule`,
  FR-17). De görs av en grundare.
- Andra ändringar görs av grundarna eller agenter på nivå 1–3. De får hänvisa till lärdomar med lägre
  status, och sådana lärdomar markeras som ej verifierade i versionen (`unverified_lessons`).
- En agentversion kräver att agenten finns i registret.
- `diff()` visar vilka nycklar som ändrades mellan två versioner.
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
from .lessons import LessonError

_COLUMNS = "id, name, kind, version, content, reason, lessons, mandatory, restores, author, at"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StrategyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Version:
    version_id: int
    name: str
    kind: str
    version: int
    content: dict[str, Any]
    reason: str
    lessons: dict[str, str]  # lärdom-ID → status när versionen sparades
    mandatory: bool
    restores: int | None
    author: str
    at: str

    @property
    def unverified_lessons(self) -> tuple[int, ...]:
        return tuple(int(i) for i, status in self.lessons.items() if status != "operational_rule")


class StrategyRegistry:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        permissions,
        audit: AuditLog,
        founders: frozenset[str],
        lessons=None,
        clock: Callable[[], str] = _now,
    ) -> None:
        """`lessons`: en `LessonRegistry`; krävs för att hänvisa till lärdomar och för obligatoriska ändringar."""
        self._db = db
        self._registry = registry
        self._permissions = permissions
        self._audit = audit
        self._founders = frozenset(founders)
        self._lessons = lessons
        self._clock = clock

    # --- Ändra -----------------------------------------------------------------------------

    def save(self, author: str, name: str, content: dict[str, Any], reason: str, lessons: tuple[int, ...] = (),
             mandatory: bool = False) -> Version:
        kind = "agent" if name.startswith("agent:") else "strategy"
        return self._save(author, name, kind, content, reason, lessons, mandatory, None)

    def restore(self, author: str, name: str, version: int, reason: str) -> Version:
        """Återställer en tidigare version som en ny version (§53: strategiförändringar kan återställas)."""
        target = self.get(name, version)
        if target is None:
            raise StrategyError(f"{name} har ingen version {version}")
        current = self.active(name)
        if current.version == version:
            raise StrategyError(f"version {version} gäller redan")
        lesson_ids = tuple(int(i) for i in target.lessons)
        return self._save(author, name, target.kind, target.content, reason, lesson_ids, target.mandatory,
                          target.version_id, restoring=True)

    # --- Frågor ----------------------------------------------------------------------------

    def active(self, name: str) -> Version | None:
        rows = self._rows("WHERE name = ? ORDER BY version DESC LIMIT 1", (name,))
        return rows[0] if rows else None

    def get(self, name: str, version: int) -> Version | None:
        rows = self._rows("WHERE name = ? AND version = ?", (name, version))
        return rows[0] if rows else None

    def history(self, name: str) -> tuple[Version, ...]:
        return self._rows("WHERE name = ? ORDER BY version", (name,))

    def names(self) -> tuple[str, ...]:
        return tuple(r[0] for r in self._db.connection.execute("SELECT DISTINCT name FROM strategy_versions ORDER BY name"))

    def diff(self, name: str, old: int, new: int) -> dict[str, tuple[Any, Any]]:
        a, b = self.get(name, old), self.get(name, new)
        if a is None or b is None:
            raise StrategyError(f"{name}: versionerna {old} och {new} måste finnas")
        keys = sorted(set(a.content) | set(b.content))
        return {k: (a.content.get(k), b.content.get(k)) for k in keys if a.content.get(k) != b.content.get(k)}

    # --- Internt ---------------------------------------------------------------------------

    def _save(self, author, name, kind, content, reason, lessons, mandatory, restores, restoring=False) -> Version:
        self._require_author(author, mandatory)
        if not isinstance(name, str) or not name.strip():
            raise StrategyError("ange strategins namn")
        if not isinstance(content, dict) or not content:
            raise StrategyError("innehållet ska vara ett JSON-objekt som inte är tomt")
        if not isinstance(reason, str) or not reason.strip():
            raise StrategyError("motivera ändringen")
        if kind == "agent" and self._registry.get(name.split(":", 1)[1]) is None:
            raise StrategyError(f"agenten i {name} finns inte i registret")
        statuses = self._lesson_statuses(lessons, mandatory)
        current = self.active(name)
        if current is not None and current.kind != kind:
            raise StrategyError(f"{name} är redan en {current.kind}")
        if current is not None and current.content == content and not restoring:
            raise StrategyError("innehållet är samma som den gällande versionen")
        number = current.version + 1 if current else 1
        try:
            text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            raise StrategyError("innehållet går inte att spara som JSON") from None
        with self._db.transaction() as tx:
            version_id = tx.execute(
                f"INSERT INTO strategy_versions ({_COLUMNS.split(', ', 1)[1]}) VALUES ({', '.join('?' * 10)})",
                (name, kind, number, text, reason, json.dumps(statuses), int(mandatory), restores, author,
                 self._clock()),
            ).lastrowid
        self._audit.append(author, "strategy.restored" if restoring else "strategy.saved",
                           {"name": name, "version": number, "restores": restores, "mandatory": mandatory,
                            "lessons": statuses})
        return self.get(name, number)

    def _lesson_statuses(self, lessons, mandatory: bool) -> dict[str, str]:
        if mandatory and not lessons:
            raise StrategyError("en obligatorisk ändring måste bygga på minst en godkänd operativ regel (FR-17)")
        if lessons and self._lessons is None:
            raise StrategyError("lärdomsregistret är inte kopplat")
        statuses: dict[str, str] = {}
        for lesson_id in lessons:
            if mandatory:
                try:
                    lesson = self._lessons.require_rule(lesson_id)  # bara operativa regler
                except LessonError as exc:
                    raise StrategyError(str(exc)) from None
            else:
                lesson = self._lessons.get(lesson_id)
                if lesson is None:
                    raise StrategyError(f"lärdom {lesson_id} finns inte")
            statuses[str(lesson_id)] = lesson.status
        return statuses

    def _require_author(self, author: str, mandatory: bool) -> None:
        if author in self._founders:
            return
        if mandatory:
            raise StrategyError("obligatoriska ändringar av gemensamma regler görs av en grundare (FR-17, §29)")
        agent = self._registry.get(author)
        if agent is None or agent.state not in ACTING_STATES:
            raise StrategyError(f"{author!r} finns inte eller får inte agera just nu")
        if self._permissions.roles[agent.role].level > LEVEL_HEAD:
            raise StrategyError("strategier ändras av grundarna eller nivå 1–3")

    def _rows(self, where: str, params: tuple) -> tuple[Version, ...]:
        return tuple(
            Version(vid, name, kind, version, json.loads(content), reason, json.loads(lessons), bool(mandatory),
                    restores, author, at)
            for vid, name, kind, version, content, reason, lessons, mandatory, restores, author, at
            in self._db.connection.execute(f"SELECT {_COLUMNS} FROM strategy_versions {where}", params)
        )
