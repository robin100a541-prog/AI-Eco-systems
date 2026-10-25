"""`manual`-provider (D-005, ROADMAP Fas 3): en grundare kör prompten i Claude och klistrar in svaret.

Flödet:
1. `ManualProvider.complete()` skriver förfrågan till inkorgen (`<inkorg>/<id>.request.json`)
   och kastar `ManualPending`. Routern går då vidare till nästa leverantör, eller kastar
   `NoProviderAvailable` så att den som anropar köar arbetet.
2. En grundare läser förfrågan med `python -m aie manual show <id>`, kör den i Claude och
   lämnar svaret med `python -m aie manual answer <id> --as <grundare> --file svar.txt`.
3. Nästa gång samma förfrågan görs hittar providern svaret, returnerar det och flyttar båda
   filerna till `<inkorg>/done/`.

Samma förfrågan får alltid samma id (en hash av meddelandena), så att en köad uppgift som körs
om hittar sitt svar. Prompten lämnar datorn via en människa, så providern räknas som extern och
tar bara emot data som är klassad `public` (DR-13). Inget nätverk används här.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..monitoring import mask_secrets
from .providers import PUBLIC_ONLY, ChatRequest, ChatResponse, Provider, ProviderError

MAX_ANSWER_CHARS = 20_000
_ID_LENGTH = 16


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ManualPending(ProviderError):
    """Förfrågan väntar på en grundares svar. Routern behandlar det som ett misslyckat anrop."""

    def __init__(self, provider: str, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(
            f"{provider}: väntar på grundarens svar (python -m aie manual show {request_id})"
        )


class ManualError(ValueError):
    """Ett svar kunde inte lämnas, till exempel för att förfrågan inte finns."""


@dataclass(frozen=True, slots=True)
class ManualRequest:
    request_id: str
    created_at: str
    messages: tuple[tuple[str, str], ...]  # (roll, text)
    max_tokens: int
    answered: bool

    def prompt(self) -> str:
        """Texten som grundaren klistrar in i Claude."""
        return "\n\n".join(f"[{role}]\n{content}" for role, content in self.messages)


def manual_dir(data_dir: Path | str, environment: str) -> Path:
    """Inkorgen ligger bredvid databasen: `<data_dir>/manual/<miljö>/`."""
    return Path(data_dir) / "manual" / environment


def request_id(request: ChatRequest) -> str:
    canonical = json.dumps(
        {
            "messages": [[m.role, m.content] for m in request.messages],
            "max_tokens": request.max_tokens,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_ID_LENGTH]


class ManualInbox:
    """Filerna i inkorgen. Skrivningar är atomära (skriv till .tmp, sedan os.replace)."""

    def __init__(self, path: Path | str, clock: Callable[[], str] = _now) -> None:
        self.path = Path(path)
        self._clock = clock

    def _file(self, rid: str, kind: str) -> Path:
        if len(rid) != _ID_LENGTH or any(c not in "0123456789abcdef" for c in rid):
            raise ManualError(f"ogiltigt id {rid!r}")
        return self.path / f"{rid}.{kind}.json"

    def _write(self, target: Path, data: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def submit(self, request: ChatRequest) -> str:
        rid = request_id(request)
        target = self._file(rid, "request")
        if not target.exists():
            self._write(
                target,
                {
                    "id": rid,
                    "created_at": self._clock(),
                    "messages": [[m.role, m.content] for m in request.messages],
                    "max_tokens": request.max_tokens,
                },
            )
        return rid

    def get(self, rid: str) -> ManualRequest | None:
        target = self._file(rid, "request")
        if not target.exists():
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        return ManualRequest(
            data["id"],
            data["created_at"],
            tuple((role, content) for role, content in data["messages"]),
            data["max_tokens"],
            self._file(rid, "answer").exists(),
        )

    def pending(self) -> tuple[ManualRequest, ...]:
        if not self.path.is_dir():
            return ()
        found = (
            self.get(p.name.split(".")[0])
            for p in sorted(self.path.glob("*.request.json"))
        )
        return tuple(r for r in found if r is not None and not r.answered)

    def answer(self, rid: str, text: str, founder: str) -> None:
        if self.get(rid) is None:
            raise ManualError(f"förfrågan {rid} finns inte (eller är redan använd)")
        target = self._file(rid, "answer")
        if target.exists():
            raise ManualError(f"förfrågan {rid} har redan ett svar")
        text = text.strip()
        if not text:
            raise ManualError("svaret är tomt")
        if len(text) > MAX_ANSWER_CHARS:
            raise ManualError(f"svaret är längre än {MAX_ANSWER_CHARS} tecken")
        if mask_secrets(text) != text:
            raise ManualError(
                "svaret ser ut att innehålla en hemlighet; ta bort den först (SR-10)"
            )
        self._write(
            target,
            {"id": rid, "text": text, "founder": founder, "answered_at": self._clock()},
        )

    def take(self, rid: str) -> str | None:
        """Svaret om det finns, och då flyttas förfrågan och svaret till `done/`."""
        answer = self._file(rid, "answer")
        if not answer.exists():
            return None
        text = json.loads(answer.read_text(encoding="utf-8"))["text"]
        done = self.path / "done"
        done.mkdir(exist_ok=True)
        os.replace(answer, done / answer.name)
        request = self._file(rid, "request")
        if request.exists():
            os.replace(request, done / request.name)
        return text


class ManualProvider(Provider):
    external = True  # prompten lämnar datorn via grundaren

    def __init__(self, name: str, inbox: ManualInbox) -> None:
        self.name = name
        self.model = "manual"
        self.allowed_classes = PUBLIC_ONLY
        self.inbox = inbox

    def complete(self, request: ChatRequest) -> ChatResponse:
        rid = request_id(request)
        text = self.inbox.take(rid)
        if text is None:
            self.inbox.submit(request)
            raise ManualPending(self.name, rid)
        return ChatResponse(self.name, self.model, text, tokens=0)
