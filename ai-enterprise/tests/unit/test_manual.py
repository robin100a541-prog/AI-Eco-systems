"""Tester för `manual`-providern och `python -m aie manual` (Fas 3, D-005). Verifierar DR-12, DR-13 och SR-10.

Inget nätverk: providern skriver bara filer i en temporär inkorg.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aie.audit import AuditLog
from aie.llm import (
    ChatRequest,
    DataClass,
    ManualInbox,
    ManualProvider,
    Message,
    NoProviderAvailable,
    ProviderRouter,
    QuotaLedger,
    Slot,
    load_providers,
    manual_dir,
)
from aie.llm.manual import MAX_ANSWER_CHARS, ManualError, request_id
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]


def ask(
    text="Sammanfatta marknaden för begagnade cyklar.", data_class=DataClass.PUBLIC
):
    return ChatRequest(
        (Message("system", "Du är Research."), Message("user", text)), data_class
    )


class ManualCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.inbox = ManualInbox(
            self.dir / "inbox", clock=lambda: "2026-10-25T10:00:00+00:00"
        )
        self.router = self.make_router()

    def make_router(self, calls=100):
        slot = Slot(ManualProvider("manual", self.inbox), calls, 1_000_000)
        return ProviderRouter(
            (slot,), QuotaLedger(self.db, day=lambda: "2026-10-25"), self.audit
        )

    def actions(self):
        return [e.action for e in self.audit.entries()]


class TestProvider(ManualCase):
    def test_first_call_is_queued_then_founders_answer_is_returned(self):
        """Verifies D-005: förfrågan hamnar i inkorgen, grundaren svarar och nästa körning får svaret."""
        with self.assertRaises(NoProviderAvailable) as caught:
            self.router.complete(ask(), caller="res-1")
        rid = request_id(ask())
        self.assertIn(
            f"väntar på grundarens svar (python -m aie manual show {rid})",
            str(caught.exception),
        )
        self.assertEqual([r.request_id for r in self.inbox.pending()], [rid])
        self.assertIn("[user]\nSammanfatta marknaden", self.inbox.get(rid).prompt())

        self.inbox.answer(rid, "  Marknaden växer.  ", "robin")
        self.assertEqual(self.inbox.pending(), ())
        response = self.router.complete(ask(), caller="res-1")
        self.assertEqual(
            (response.provider, response.model, response.text),
            ("manual", "manual", "Marknaden växer."),
        )
        self.assertIn("llm.call", self.actions())
        self.assertIsNone(self.inbox.get(rid), "använda filer flyttas till done/")
        self.assertTrue((self.inbox.path / "done" / f"{rid}.answer.json").exists())

    def test_same_request_same_id_and_no_duplicates(self):
        """Verifies D-005: en köad uppgift som körs om hittar sin egen förfrågan."""
        for _ in range(3):
            with self.assertRaises(NoProviderAvailable):
                self.router.complete(ask(), caller="res-1")
        self.assertEqual(len(list(self.inbox.path.glob("*.request.json"))), 1)
        self.assertNotEqual(request_id(ask()), request_id(ask("En annan fråga")))

    def test_internal_data_never_reaches_the_inbox(self):
        """Verifies DR-13: prompten lämnar datorn via grundaren, så bara public-data får komma hit."""
        for data_class in (DataClass.INTERNAL, DataClass.PERSONAL, DataClass.SECRET):
            with self.assertRaises(NoProviderAvailable) as caught:
                self.router.complete(ask("Kundlista: ...", data_class), caller="res-1")
            self.assertIn(
                f"tar inte emot {data_class.value}-data", str(caught.exception)
            )
        self.assertEqual(self.inbox.pending(), ())
        self.assertFalse(self.inbox.path.exists())

    def test_waiting_calls_count_against_the_daily_quota(self):
        """Verifies DR-12, ER-02: även manual har en dagsgräns; varje försök räknas."""
        router = self.make_router(calls=1)
        with self.assertRaises(NoProviderAvailable):
            router.complete(ask(), caller="res-1")
        with self.assertRaises(NoProviderAvailable) as caught:
            router.complete(ask(), caller="res-1")
        self.assertIn("dagens kvot är slut", str(caught.exception))

    def test_bad_answers_are_refused(self):
        """Verifies SR-10: tomma, för långa, dubbla och hemliga svar avvisas; okända id går inte att besvara."""
        rid = self.inbox.submit(ask())
        for text in (
            "",
            "   ",
            "x" * (MAX_ANSWER_CHARS + 1),
            "Här är nyckeln api_key=abc123def456",
        ):
            with self.assertRaises(ManualError):
                self.inbox.answer(rid, text, "robin")
        with self.assertRaises(ManualError):
            self.inbox.answer("0" * 16, "svar", "robin")
        for bad_id in ("../../etc/passwd", "ABCDEF0123456789", "123"):
            with self.assertRaisesRegex(ManualError, "ogiltigt id"):
                self.inbox.answer(bad_id, "svar", "robin")
        self.inbox.answer(rid, "Första svaret", "robin")
        with self.assertRaises(ManualError):
            self.inbox.answer(rid, "Andra svaret", "yorgo")

    def test_provider_code_has_no_network(self):
        """Verifies D-005, D-009: manual-providern anropar aldrig något API själv."""
        text = (ROOT / "src" / "aie" / "llm" / "manual.py").read_text(encoding="utf-8")
        for forbidden in ("urllib", "http", "socket", "Transport"):
            self.assertNotIn(forbidden, text)


class TestConfig(unittest.TestCase):
    def write(self, directory, body):
        (directory / "providers.toml").write_text(
            "config_version = 1\n" + body, encoding="utf-8"
        )

    def test_manual_kind_needs_an_inbox_and_a_limit(self):
        """Verifies ER-02: manual läses från providers.toml, hoppas över utan inkorg och kräver gränser."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.write(
                d,
                '[[providers]]\nname = "manual"\nkind = "manual"\ndaily_calls = 20\ndaily_tokens = 100000\n',
            )
            slots, skipped = load_providers(d, environ={})
            self.assertEqual((slots, len(skipped)), ((), 1))
            self.assertIn("ingen inkorg", skipped[0])
            slots, skipped = load_providers(d, environ={}, manual_dir=d / "inbox")
            self.assertEqual((len(slots), skipped), (1, ()))
            self.assertIsInstance(slots[0].provider, ManualProvider)
            self.assertEqual(slots[0].daily_calls, 20)
            self.write(d, '[[providers]]\nname = "manual"\nkind = "manual"\n')
            with self.assertRaises(Exception) as caught:
                load_providers(d, environ={}, manual_dir=d / "inbox")
            self.assertIn(
                "daily_calls måste vara ett positivt heltal", str(caught.exception)
            )

    def test_repo_providers_toml_still_loads(self):
        slots, _ = load_providers(
            ROOT / "config", environ={}, manual_dir=Path(tempfile.gettempdir())
        )
        self.assertIn("rule", [s.provider.name for s in slots])


class TestCli(unittest.TestCase):
    """`python -m aie manual` i en egen process mot en riktig databas."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        system = (ROOT / "config" / "system.toml").read_text(encoding="utf-8")
        system = system.replace(
            'data_dir = "data"', f"data_dir = {json.dumps(str(self.dir / 'data'))}"
        )
        system = system.replace(
            'log_dir = "logs"', f"log_dir = {json.dumps(str(self.dir / 'logs'))}"
        )
        self.config_dir = self.dir / "config"
        self.config_dir.mkdir()
        (self.config_dir / "system.toml").write_text(system, encoding="utf-8")
        for name in ("risk_limits.toml", "permissions.toml"):
            (self.config_dir / name).write_text(
                (ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        self.inbox = ManualInbox(manual_dir(self.dir / "data", "sim"))
        self.rid = self.inbox.submit(ask())

    def cli(self, *args, stdin=None):
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "aie",
                "manual",
                *args,
                "--config-dir",
                str(self.config_dir),
            ],
            cwd=self.dir,
            env=env,
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def audit_actions(self):
        db = Database.open(self.dir / "data", "sim")
        try:
            return [(e.actor, e.action, e.details) for e in AuditLog(db).entries()]
        finally:
            db.close()

    def test_list_show_answer_and_audit(self):
        """Verifies D-005, FR-04: grundaren listar, läser och besvarar; svaret revideras men inte texten."""
        listed = self.cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(self.rid, listed.stdout)
        shown = self.cli("show", self.rid)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Sammanfatta marknaden för begagnade cyklar.", shown.stdout)
        answer = self.dir / "svar.txt"
        answer.write_text("HEMLIGT-INNEHÅLL-SOM-INTE-SKA-LOGGAS", encoding="utf-8")
        answered = self.cli("answer", self.rid, "--as", "yorgo", "--file", str(answer))
        self.assertEqual(answered.returncode, 0, answered.stderr)
        self.assertIn("Inga förfrågningar", self.cli("list").stdout)
        entries = self.audit_actions()
        self.assertIn(
            ("yorgo", "manual.answered", {"request_id": self.rid, "chars": 36}), entries
        )
        self.assertNotIn("HEMLIGT-INNEHÅLL", json.dumps(entries, ensure_ascii=False))
        self.assertNotIn(
            "HEMLIGT-INNEHÅLL",
            (self.dir / "logs" / "aie.log").read_text(encoding="utf-8"),
        )

    def test_answer_from_stdin(self):
        done = self.cli(
            "answer", self.rid, "--as", "robin", "--file", "-", stdin="Svar via stdin\n"
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_non_founder_and_bad_input_are_refused_and_audited(self):
        """Verifies D-021, SR-10: bara grundare får svara; fel ger kod 1 och revideras."""
        impostor = self.cli(
            "answer", self.rid, "--as", "ceo-1", "--file", "-", stdin="svar"
        )
        self.assertEqual(impostor.returncode, 1)
        self.assertIn("inte grundare", impostor.stderr)
        secret = self.cli(
            "answer",
            self.rid,
            "--as",
            "robin",
            "--file",
            "-",
            stdin="token=abcdef1234567890",
        )
        self.assertEqual(secret.returncode, 1)
        self.assertIn("hemlighet", secret.stderr)
        self.assertEqual(self.cli("show", "0" * 16).returncode, 1)
        self.assertEqual(self.cli("answer").returncode, 1)
        denied = [a for _, a, _ in self.audit_actions() if a == "manual.denied"]
        self.assertEqual(len(denied), 2)
        self.assertEqual([r.request_id for r in self.inbox.pending()], [self.rid])


if __name__ == "__main__":
    unittest.main()
