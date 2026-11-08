"""Åtkomstkoder och sessioner för kommandocentralen (dashboard D1, FR-28, D-073).

- En åtkomstkod per grundare. Bara en hash sparas, i `.env` (gitignorerad), som
  `AIE_DASHBOARD_CODE_<GRUNDARE>=pbkdf2_sha256$<varv>$<salt>$<hash>`. Koden skrivs aldrig ut eller loggas.
- Sessioner finns bara i minnet: en omstart loggar ut alla. Varje session har en egen CSRF-token.
- Fem felaktiga försök från samma adress ger 60 sekunders spärr.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ITERATIONS = 240_000
MIN_LENGTH = 8
SESSION_SECONDS = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
PREFIX = "AIE_DASHBOARD_CODE_"


class AuthError(Exception):
    pass


def env_key(founder: str) -> str:
    return PREFIX + founder.strip().upper()


def hash_code(code: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_code(code: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def read_env(path: Path) -> dict[str, str]:
    """Läser `NAMN=värde`-rader. Kommentarer och tomma rader hoppas över."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def set_code(env_path: Path, founder: str, code: str, founders: tuple[str, ...]) -> None:
    """Sparar hashen för grundarens kod i `.env`. Andra rader i filen lämnas orörda."""
    name = founder.strip().lower()
    if name not in {f.lower() for f in founders}:
        raise AuthError(f"okänd grundare {founder!r}; välj en av {', '.join(founders)}")
    if len(code) < MIN_LENGTH:
        raise AuthError(f"koden måste ha minst {MIN_LENGTH} tecken")
    key = env_key(name)
    line = f"{key}={hash_code(code)}"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    kept = [l for l in lines if l.split("=", 1)[0].strip() != key]
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join([*kept, line]) + "\n", encoding="utf-8")


@dataclass
class Session:
    founder: str | None
    csrf: str
    expires: float


@dataclass
class Authenticator:
    """Kontrollerar koder mot hasharna i `.env` och håller sessionerna i minnet."""

    env_path: Path
    founders: tuple[str, ...]
    clock: callable = time.monotonic
    _sessions: dict[str, Session] = field(default_factory=dict)
    _failures: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def configured(self) -> tuple[str, ...]:
        env = read_env(self.env_path)
        return tuple(f for f in self.founders if env_key(f) in env)

    def new_session(self, founder: str | None = None) -> tuple[str, Session]:
        sid = secrets.token_urlsafe(32)
        session = Session(founder, secrets.token_urlsafe(32), self.clock() + SESSION_SECONDS)
        with self._lock:
            self._sessions[sid] = session
        return sid, session

    def session(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is not None and session.expires < self.clock():
                del self._sessions[sid]
                return None
            return session

    def end(self, sid: str | None) -> None:
        with self._lock:
            self._sessions.pop(sid or "", None)

    def locked(self, address: str) -> bool:
        now = self.clock()
        with self._lock:
            recent = [t for t in self._failures.get(address, []) if now - t < LOCKOUT_SECONDS]
            self._failures[address] = recent
            return len(recent) >= MAX_FAILURES

    def login(self, address: str, founder: str, code: str) -> str | None:
        """Returnerar grundarens namn om koden stämmer, annars None. Räknar misslyckade försök per adress."""
        if self.locked(address):
            return None
        name = founder.strip().lower()
        stored = read_env(self.env_path).get(env_key(name)) if name in {f.lower() for f in self.founders} else None
        if stored and verify_code(code, stored):
            with self._lock:
                self._failures.pop(address, None)
            return name
        with self._lock:
            self._failures.setdefault(address, []).append(self.clock())
        return None
