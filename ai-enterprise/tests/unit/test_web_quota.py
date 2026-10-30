"""Verifies M5/SR-12: failed requests and concurrent attempts share one atomic quota."""
import threading
from dataclasses import replace
from types import SimpleNamespace

from aie.audit import AuditLog
from aie.memory import Database
from aie.research import WebError, WebReader
from .test_web import WebCase


class AttemptQuota(WebCase):
    def test_failed_fetch_uses_quota_and_next_attempt_sends_nothing(self):
        reader = self.make(per_day=1)
        with self.assertRaises(WebError):
            reader.fetch("res-1", "https://gumroad.com/missing")
        self.assertEqual(reader.used_today(), 1)
        calls = tuple(self.net.calls)
        with self.assertRaisesRegex(WebError, "kvot"):
            reader.fetch("res-1", "https://gumroad.com/pricing")
        self.assertEqual(tuple(self.net.calls), calls)
        self.day = "2026-10-29"
        reader.fetch("res-1", "https://gumroad.com/pricing")
        self.assertEqual(reader.used_today(), 1)

    def test_invalid_addresses_consume_attempt_before_dns(self):
        reader = self.make(per_day=1)
        with self.assertRaises(WebError):
            reader.fetch("res-1", "ftp://gumroad.com/missing")
        self.assertEqual(reader.used_today(), 1)
        self.assertEqual(self.net.calls, [])

    def test_two_connections_cannot_reserve_the_last_attempt(self):
        barrier, outcomes, errors = threading.Barrier(2), [], []
        folder = self.db.path.parent
        def attempt():
            try:
                with Database.open(folder, "sim") as db:
                    reader = WebReader(db, SimpleNamespace(require=lambda *args: None), AuditLog(db),
                        replace(self.limits, per_day=1), self.net.get, self.net.resolve,
                        clock=lambda: "2026-10-28T12:00:00+00:00")
                    barrier.wait(timeout=10)
                    try:
                        reader.fetch("res-1", "https://gumroad.com/pricing")
                        outcomes.append(True)
                    except WebError:
                        outcomes.append(False)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=20)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(self.net.calls.count("https://gumroad.com/pricing"), 1)
