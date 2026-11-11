"""Command Center Del 5: notiser med ntfy och Gmail SMTP (`aie.notify`)."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aie import runtime
from aie.dashboard import control
from aie.monitoring import shutdown_logging
from aie.notify import GENERIC, Channels, collect
from aie.notify import cli as notify_cli
from aie.simulation.seed import seed

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSmtp:
    sent: list = []
    logins: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSmtp.logins.append((self.host, self.port, user, password))

    def send_message(self, message):
        FakeSmtp.sent.append(message)


class NotifyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(shutdown_logging)
        self.dir = Path(tmp.name)
        self.config_dir = self.dir / "config"
        shutil.copytree(CONFIG, self.config_dir)
        path = self.config_dir / "system.toml"
        text = path.read_text(encoding="utf-8")
        text = text.replace('data_dir = "data"', f'data_dir = "{(self.dir / "data").as_posix()}"')
        text = text.replace('log_dir = "logs"', f'log_dir = "{(self.dir / "logs").as_posix()}"')
        path.write_text(text, encoding="utf-8")
        seed(self.config_dir, days=2)
        shutdown_logging()
        self.pushes: list = []
        FakeSmtp.sent, FakeSmtp.logins = [], []

    def opener(self, request, timeout):
        self.pushes.append(request)
        return Response()

    def channels(self, **kw):
        base = dict(ntfy_topic="topic-secret-abc123", gmail_user="bot@example.com", gmail_password="app-password-xyz",
                    recipients=("yorgo@example.com", "robin@example.com"), opener=self.opener, smtp=FakeSmtp)
        base.update(kw)
        return Channels(**base)

    def core(self):
        config = runtime._load(self.config_dir, console=False)
        db = runtime._open(config)
        self.addCleanup(db.close)
        system, gov = control.open_core(config, db, self.config_dir)
        return db, system, gov

    def run_cli(self, fn, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = fn(self.config_dir, *args)
        shutdown_logging()
        return code, out.getvalue()


class TestTriggers(NotifyCase):
    def test_every_trigger_gives_its_alert(self):
        """Verifies FR-33: nödstopp, skyddat läge, nådd riskgräns, blockerad handling, beslut som väntat över en
        timme och slut gratiskvot ger var sitt larm, och inget annat gör det."""
        db, system, _ = self.core()
        later = datetime.now(UTC) + timedelta(hours=2)
        self.assertEqual({a.kind for a in collect(db, later)[0]}, {"waiting", "blocked"})  # 3 förslag och ett nekat verktyg
        self.assertNotIn("waiting", {a.kind for a in collect(db, datetime.now(UTC))[0]})  # inte en timme än
        system.kill.engage("yorgo", "test")
        for action in ("mode.protected_entered", "stoploss.tripped", "simulation.paused_quota", "ledger.recorded"):
            system.audit.append("system:test", action, {"reason": "test"})
        alerts, record = collect(db, later)
        self.assertEqual([a.kind for a in alerts], ["kill", "protected", "limit", "waiting", "quota", "blocked"])
        self.assertEqual(record["pending"], [1, 2, 3])

    def test_nothing_is_notified_twice_and_one_per_kind_per_15_minutes(self):
        """Verifies FR-33: det som är aviserat aviseras inte igen, och samma typ högst var 15:e minut."""
        _, out = self.run_cli(notify_cli.run, self.channels())
        self.assertIn("1 larm (blocked)", out)
        self.assertEqual(len(self.pushes), 1)
        _, out = self.run_cli(notify_cli.run, self.channels())
        self.assertIn("0 larm", out)
        self.assertEqual(len(self.pushes), 1)
        db, system, _ = self.core()
        system.audit.append("authorization", "tool.denied", {"agent_id": "res-1", "tool": "x"})
        db.close()
        _, out = self.run_cli(notify_cli.run, self.channels())
        self.assertIn("0 larm", out)  # samma typ inom 15 minuter
        db, system, _ = self.core()
        alerts, _ = collect(db, datetime.now(UTC) + timedelta(minutes=16))
        self.assertEqual([a.kind for a in alerts], ["blocked"])  # efter 15 minuter kommer den


class TestChannels(NotifyCase):
    def test_ntfy_gets_only_generic_text_and_email_gets_the_details(self):
        """Verifies FR-33, D-091: ntfy får bara de fasta texterna, aldrig belopp, namn eller ID:n; e-posten går via
        Gmail SMTP till grundarna. Hemligheter syns inte i utskriften."""
        db, system, _ = self.core()
        system.kill.engage("yorgo", "Budget 99999 SIM for lead-1 looks wrong")
        db.close()
        code, out = self.run_cli(notify_cli.run, self.channels())
        self.assertEqual(code, 0)
        self.assertIn("ntfy sent, e-post sent", out)
        self.assertNotIn("topic-secret-abc123", out)
        self.assertNotIn("app-password-xyz", out)
        self.assertEqual([p.full_url for p in self.pushes], ["https://ntfy.sh/topic-secret-abc123"] * 2)
        allowed = set(GENERIC.values())
        for push in self.pushes:
            text = push.data.decode("utf-8")
            self.assertIn(text, allowed)
            self.assertNotRegex(text, r"\d|lead-1|yorgo|SIM")
            self.assertEqual(push.get_header("Title"), "Command Center")
        self.assertEqual(FakeSmtp.logins, [("smtp.gmail.com", 465, "bot@example.com", "app-password-xyz")])
        message = FakeSmtp.sent[0]
        self.assertEqual(message["To"], "yorgo@example.com, robin@example.com")
        self.assertIn("kill.engaged", message.get_content())

    def test_missing_secrets_skip_the_channel_without_errors(self):
        """Verifies FR-33, D-091: saknas hemligheterna hoppas kanalen över, kommandot avslutar med 0, och larmet
        ligger kvar tills en kanal finns."""
        empty = Channels.from_env({})
        self.assertFalse(empty.has_ntfy or empty.has_email)
        code, out = self.run_cli(notify_cli.run, empty)
        self.assertEqual(code, 0)
        self.assertIn("ntfy skipped, e-post skipped", out)
        db, system, _ = self.core()
        self.assertNotIn("notify.sent", [e.action for e in system.audit.entries()])
        db.close()
        _, out = self.run_cli(notify_cli.run, self.channels(gmail_password=""))
        self.assertIn("ntfy sent, e-post skipped", out)
        self.assertEqual(FakeSmtp.sent, [])

    def test_a_failing_channel_never_raises(self):
        """Verifies D-085, FR-33: när ntfy eller SMTP fallerar loggas det och kommandot avslutar ändå med 0."""
        def broken(request, timeout):
            raise OSError("network down")

        class BrokenSmtp(FakeSmtp):
            def login(self, user, password):
                raise OSError("smtp down")

        code, out = self.run_cli(notify_cli.run, self.channels(opener=broken, smtp=BrokenSmtp))
        self.assertEqual(code, 0)
        self.assertIn("ntfy failed, e-post failed", out)

    def test_channels_from_env(self):
        """Verifies FR-33: kanalerna läses ur miljön; mottagarna är grundarnas adresser i ALLOWED_EMAILS."""
        c = Channels.from_env({"NTFY_TOPIC": "t", "GMAIL_USER": "bot@example.com", "GMAIL_APP_PASSWORD": "p",
                               "ALLOWED_EMAILS": "yorgo=y@example.com,robin=r@example.com"})
        self.assertTrue(c.has_ntfy and c.has_email)
        self.assertEqual(c.recipients, ("r@example.com", "y@example.com"))
        self.assertEqual(Channels.from_env({"GMAIL_USER": "bot@example.com", "GMAIL_APP_PASSWORD": "p"}).recipients,
                         ("bot@example.com",))


class TestDaily(NotifyCase):
    def test_daily_summary_comes_from_the_snapshot_and_goes_by_email_only(self):
        """Verifies FR-33, FR-29: sammanfattningen byggs ur snapshoten i KV (samma siffror som Command Center) och
        skickas bara med e-post; utan snapshot skickas ingenting."""
        from aie.dashboard.snapshot import build_snapshot

        db, system, _ = self.core()
        config = runtime._load(self.config_dir, console=False)
        snap = build_snapshot(system, config, self.config_dir)
        db.close()

        class Kv:
            def __init__(self, value):
                self.value = value

            def get(self, key):
                return self.value

        code, out = self.run_cli(notify_cli.daily, self.channels(), Kv(json.dumps(snap).encode()))
        self.assertEqual(code, 0)
        self.assertIn("e-post sent", out)
        self.assertEqual(self.pushes, [])
        body = FakeSmtp.sent[0].get_content()
        net = snap["economy"]["net_profit_realized"]["value"]
        self.assertIn(f"Net profit (realized): {net / 100:,.2f} SIM".replace(",", " "), body)
        self.assertIn("Waiting for a founder: 3", body)
        self.assertIn("Audit chain: verified", body)
        FakeSmtp.sent = []
        code, out = self.run_cli(notify_cli.daily, self.channels(), Kv(None))
        self.assertEqual(code, 0)
        self.assertEqual(FakeSmtp.sent, [])


if __name__ == "__main__":
    unittest.main()
