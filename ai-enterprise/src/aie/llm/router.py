"""ProviderRouter (DR-12, DR-13, D-008): väljer första leverantör som får ta emot datan och har kvot kvar.

Ordning för varje anrop:
1. **Dataklass:** `internal`, `personal` och `secret` går aldrig till externa leverantörer,
   bara till `ollama` eller `rule` (DR-13).
2. **Kvot:** anropet räknas i databasen *innan* det skickas. Är dagens gräns nådd hoppas
   leverantören över (migration 6, ER-02: en saknad gräns betyder blockera).
3. **Anrop:** varje leverantör provas högst en gång per förfrågan (§41: begränsade återförsök).
   Ett misslyckat anrop räknas ändå, eftersom leverantören kan ha räknat det.
4. **Allt slut:** `NoProviderAvailable` kastas. Den som anropar köar arbetet. Ingen betald
   reserv finns (D-008, D-009).

Ett misslyckat anrop loggas som `llm.provider_failed` med HTTP-status och kort skäl (aldrig nyckeln).
Varje lyckat anrop loggas i audit-loggen med leverantör, modell, tokens, dataklass och kostnad 0,
men aldrig med prompten eller svaret, eftersom de kan vara interna.
"""
from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..audit import AuditLog
from ..config import ConfigError
from ..config.loader import is_secret_key
from ..memory import Database
from .manual import ManualInbox, ManualProvider
from .providers import (
    KINDS,
    ChatRequest,
    ChatResponse,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
    RuleProvider,
    Transport,
    urllib_transport,
    validate_local_endpoint,
)

PROVIDERS_FILE = "providers.toml"
ALLOWED_KINDS = (*KINDS, "rule", "manual")
PROVIDER_KEYS = ("name", "kind", "model", "daily_calls", "daily_tokens", "base_url")
_NAME = re.compile(r"[a-z][a-z0-9_-]*")


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class NoProviderAvailable(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("ingen leverantör kan ta anropet; köa arbetet:\n" + "\n".join(f"  - {r}" for r in reasons))


@dataclass(frozen=True, slots=True)
class Slot:
    provider: Provider
    daily_calls: int
    daily_tokens: int


class QuotaLedger:
    def __init__(self, db: Database, day: Callable[[], str] = _utc_day) -> None:
        self._db = db
        self._day = day

    def reserve(self, slot: Slot) -> bool:
        """Räknar upp ett anrop om gränserna tillåter det. Atomärt, även vid samtidiga anrop."""
        name, day = slot.provider.name, self._day()
        with self._db.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO provider_usage (day, provider) VALUES (?, ?)", (day, name))
            calls, tokens = tx.execute(
                "SELECT calls, tokens FROM provider_usage WHERE day = ? AND provider = ?", (day, name)
            ).fetchone()
            if calls >= slot.daily_calls or tokens >= slot.daily_tokens:
                return False
            tx.execute(
                "UPDATE provider_usage SET calls = calls + 1 WHERE day = ? AND provider = ?", (day, name)
            )
        return True

    def add_tokens(self, provider: str, tokens: int) -> None:
        with self._db.transaction() as tx:
            tx.execute(
                "UPDATE provider_usage SET tokens = tokens + ? WHERE day = ? AND provider = ?",
                (max(0, tokens), self._day(), provider),
            )

    def usage(self, provider: str) -> tuple[int, int]:
        row = self._db.connection.execute(
            "SELECT calls, tokens FROM provider_usage WHERE day = ? AND provider = ?", (self._day(), provider)
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)


class ProviderRouter:
    def __init__(self, slots: tuple[Slot, ...], quotas: QuotaLedger, audit: AuditLog | None = None) -> None:
        self._slots = tuple(slots)
        self._quotas = quotas
        self._audit = audit

    def calls_left(self) -> int:
        """Hur många anrop som finns kvar i dag, summerat över leverantörerna (0 när token-kvoten är slut)."""
        left = 0
        for slot in self._slots:
            calls, tokens = self._quotas.usage(slot.provider.name)
            if tokens < slot.daily_tokens:
                left += max(0, slot.daily_calls - calls)
        return left

    def complete(self, request: ChatRequest, caller: str) -> ChatResponse:
        reasons: list[str] = []
        for slot in self._slots:
            p = slot.provider
            if request.data_class not in p.allowed_classes:
                reasons.append(f"{p.name}: tar inte emot {request.data_class.value}-data (DR-13)")
                continue
            if not self._quotas.reserve(slot):
                reasons.append(f"{p.name}: dagens kvot är slut")
                continue
            try:
                response = p.complete(request)
            except ProviderError as exc:
                reasons.append(str(exc))
                # Felet loggas även när en senare leverantör svarar; annars syns det aldrig.
                self._log("llm.provider_failed", caller, request, provider=p.name, status=exc.status,
                          code=exc.code, reason=str(exc))
                continue
            self._quotas.add_tokens(p.name, response.tokens)
            self._log("llm.call", caller, request, provider=p.name, model=response.model, tokens=response.tokens)
            return response
        self._log("llm.unavailable", caller, request, reasons=reasons)
        raise NoProviderAvailable(reasons)

    def _log(self, action: str, caller: str, request: ChatRequest, **fields: Any) -> None:
        if self._audit is not None:
            self._audit.append(
                "llm", action, {"caller": caller, "data_class": request.data_class.value, "cost_minor": 0, **fields}
            )


def load_providers(
    config_dir: Path | str = "config",
    environ: Mapping[str, str] = os.environ,
    transport: Transport = urllib_transport,
    manual_dir: Path | str | None = None,
) -> tuple[tuple[Slot, ...], tuple[str, ...]]:
    """Läser `providers.toml`. Returnerar (leverantörer i prioritetsordning, överhoppade med skäl).

    En leverantör vars nyckel saknas i miljön hoppas över (det är inget fel). Samma sak gäller
    `manual` när ingen inkorg (`manual_dir`) är angiven. Allt annat som
    är fel i filen samlas och kastas som `ConfigError`.
    """
    path = Path(config_dir) / PROVIDERS_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{PROVIDERS_FILE}: filen saknas i {config_dir}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{PROVIDERS_FILE}: kan inte tolkas som TOML: {exc}"]) from None

    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{PROVIDERS_FILE}: {message}")

    for key in data:
        if key not in ("config_version", "providers"):
            error(f"okänd nyckel {key!r}")
    if data.get("config_version") != 1 or isinstance(data.get("config_version"), bool):
        error(f"config_version = {data.get('config_version')!r} stöds inte (förväntat 1)")
    entries = data.get("providers")
    if not isinstance(entries, list) or not entries:
        error("[[providers]] saknas; minst en leverantör (t.ex. rule) krävs")
        entries = []

    slots: list[Slot] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries, start=1):
        where = f"providers[{i}]"
        if not isinstance(entry, dict):
            error(f"{where} måste vara en tabell")
            continue
        ok = True
        for key in entry:
            if is_secret_key(key):
                error(f"{where}.{key} ser ut som en hemlighet; nycklar läses från miljövariabler (SR-10)")
                ok = False
            elif key not in PROVIDER_KEYS:
                error(f"{where}: okänd nyckel {key!r} (tillåtna: {', '.join(PROVIDER_KEYS)})")
                ok = False
        name, kind, model = entry.get("name"), entry.get("kind"), entry.get("model")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            error(f"{where}: name = {name!r} är ogiltigt")
            ok = False
        elif name in seen:
            error(f"{where}: namnet {name!r} används redan")
            ok = False
        else:
            seen.add(name)
        if kind not in ALLOWED_KINDS:
            error(f"{where}: kind = {kind!r} är inte tillåten (tillåtna: {', '.join(ALLOWED_KINDS)}; "
                  "betalda API:er är spärrade enligt D-009)")
            ok = False
        if kind not in ("rule", "manual") and (not isinstance(model, str) or not model.strip()):
            error(f"{where}: model saknas")
            ok = False
        if kind == "openrouter" and isinstance(model, str) and not model.endswith(":free"):
            error(f"{where}: OpenRouter-modellen måste sluta på ':free' (§42)")
            ok = False
        limits = {}
        for key in ("daily_calls", "daily_tokens"):
            value = entry.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                error(f"{where}: {key} måste vara ett positivt heltal; en saknad gräns betyder blockera (ER-02)")
                ok = False
            limits[key] = value
        base_url = entry.get("base_url")
        if base_url is not None and (kind != "ollama" or not isinstance(base_url, str)):
            error(f"{where}: base_url får bara anges för ollama")
            ok = False
        if ok and kind == "ollama" and base_url is not None:
            try:
                validate_local_endpoint(base_url)
            except ValueError as exc:
                error(f"{where}: {exc}")
                ok = False
        if not ok:
            continue
        if kind == "rule":
            provider: Provider = RuleProvider(name)
        elif kind == "manual":
            if manual_dir is None:
                skipped.append(f"{name}: ingen inkorg för manual angiven; leverantören hoppas över")
                continue
            provider = ManualProvider(name, ManualInbox(manual_dir))
        else:
            key_env = KINDS[kind][1]
            api_key = environ.get(key_env) if key_env else None
            if key_env and not api_key:
                skipped.append(f"{name}: {key_env} är inte satt; leverantören hoppas över")
                continue
            provider = OpenAICompatibleProvider(name, kind, model, api_key, transport, base_url)
        slots.append(Slot(provider, limits["daily_calls"], limits["daily_tokens"]))

    if errors:
        raise ConfigError(errors)
    return tuple(slots), tuple(skipped)
