"""Command Center Del 4: kön med grundarnas beslut och `aie control ingest` (`aie.dashboard.control`)."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aie import runtime
from aie.agents import AgentState
from aie.authorization import PermissionDenied
from aie.dashboard import control
from aie.dashboard import publish as pub
from aie.monitoring import shutdown_logging
from aie.simulation.cli import simulate
from aie.simulation.seed import seed

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
FIXTURE = ROOT / "command-center" / "tests" / "fixtures" / "queue-item.json"
EMAILS = {"yorgo@example.com": "yorgo", "robin@example.com": "robin"}


class Response:
    def __init__(self, body=b"", status=200):
        self._body, self.status = body, status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeCloudflare:
    """Cloudflare KV:s REST-API i minnet: PUT, GET, DELETE på /values/<key> och GET /keys?prefix=."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def __call__(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        if url.path.endswith("/keys"):
            prefix = urllib.parse.parse_qs(url.query).get("prefix", [""])[0]
            names = [{"name": k} for k in sorted(self.store) if k.startswith(prefix)]
            return Response(json.dumps({"result": names, "success": True}).encode())
        key = urllib.parse.unquote(url.path.split("/values/")[1])
        if request.get_method() == "PUT":
            self.store[key] = request.data
            return Response()
        if request.get_method() == "DELETE":
            self.store.pop(key, None)
            return Response()
        if key not in self.store:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
        return Response(self.store[key])


def item(kind="approve", **fields):
    base = {"id": f"test-{kind}-{len(fields)}-{fields.get('request', fields.get('agent', 'x'))}", "type": kind,
            "email": "yorgo@example.com", "founder": "yorgo", "at": datetime.now(UTC).isoformat(), "note": ""}
    base.update(fields)
    return base


class ControlCase(unittest.TestCase):
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
        seed(self.config_dir, days=3)
        shutdown_logging()
        self.cloud = FakeCloudflare()
        self.kv = pub.KV("cf-token", "acc", "ns", opener=self.cloud)

    def queue(self, *items):
        for n, it in enumerate(items):
            self.cloud.store[f"queue:{it.get('at', 'x') if isinstance(it, dict) else 'x'}:{n}"] = json.dumps(it).encode()

    def ingest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = control.ingest(self.config_dir, self.kv, EMAILS)
        shutdown_logging()
        return code, out.getvalue()

    def core(self):
        config = runtime._load(self.config_dir, console=False)
        db = runtime._open(config)
        self.addCleanup(db.close)
        system, gov = control.open_core(config, db, self.config_dir)
        return config, db, system, gov

    def audit(self, system, action):
        return [json.loads(json.dumps(e.details)) for e in system.audit.entries() if e.action == action]


class TestIngest(ControlCase):
    def test_approve_and_reject_go_through_the_core_queue_and_are_logged_with_the_email(self):
        """Verifies FR-31, D-089, D-081: godkännande och avslag utförs via ApprovalQueue, loggas med grundarens mejl,
        och kön töms. En grundare räcker i simuleringen."""
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["at"] = datetime.now(UTC).isoformat()  # samma form som functions/api/action.js skriver
        self.queue(fixture, item("reject", request=2, note="Too expensive now"))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn("2 utförda, 0 avvisade", out)
        self.assertEqual([k for k in self.cloud.store if k.startswith("queue:")], [])
        _, db, system, gov = self.core()
        self.assertEqual({r.request_id for r in gov.queue.pending()}, {3})
        self.assertEqual(gov.queue.get(1).status.value, "approved")
        self.assertEqual(gov.queue.get(2).status.value, "rejected")
        applied = self.audit(system, "control.applied")
        self.assertEqual([(a["type"], a["email"], a["target"]) for a in applied],
                         [("approve", "yorgo@example.com", 1), ("reject", "yorgo@example.com", 2)])
        self.assertTrue(system.audit.verify().ok)

    def test_invalid_items_are_rejected_logged_and_never_stop_the_valid_one(self):
        """Verifies FR-31, FR-32: ogiltiga poster avvisas och loggas var för sig; den giltiga posten utförs ändå."""
        old = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        bad = [
            item("shell", cmd="rm -rf /"),
            item("approve", request=1, founder="mallory"),
            item("approve", request=1, email="mallory@example.com"),
            item("approve", request=1, founder="robin"),  # mejlet hör till yorgo
            item("approve", request="1"),
            item("approve", request=1, at=old),
            item("approve", request=999),  # kärnan nekar: förfrågan finns inte
            item("reject", request=1),  # avslag utan motivering
            item("kill"),  # utan bekräftelsen KILL
            item("pause_agent", agent="no-such-agent"),
            item("approve", request=1, extra="x"),
            "not an object",
        ]
        for n, b in enumerate(bad):
            if isinstance(b, dict):
                b["id"] = f"bad-item-{n:02d}"
        self.queue(*bad, item("approve", request=3, id="good-item-01"))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn(f"1 utförda, {len(bad)} avvisade", out)
        _, db, system, gov = self.core()
        self.assertEqual({r.request_id for r in gov.queue.pending()}, {1, 2})
        self.assertEqual(len(self.audit(system, "control.rejected")), len(bad))
        self.assertEqual(len(self.audit(system, "control.applied")), 1)
        self.assertEqual(system.kill.state().engaged, False)
        self.assertEqual([k for k in self.cloud.store if k.startswith("queue:")], [])

    def test_the_same_item_is_never_applied_twice(self):
        """Verifies D-085, D-089: en post med ett id som redan är behandlat hoppas över (dubbletter avvisas)."""
        one = item("pause_agent", agent="res-1", id="same-item-0001")
        self.queue(one)
        self.ingest()
        self.queue(one, dict(one))
        code, out = self.ingest()
        self.assertIn("0 utförda, 0 avvisade, 2 dubbletter", out)
        _, db, system, _ = self.core()
        self.assertEqual(len(self.audit(system, "control.applied")), 1)
        self.assertEqual(len([s for s in system.stops.active() if s.scope_value == "res-1"]), 1)

    def test_pause_resume_and_pause_all(self):
        """Verifies FR-32, SR-05, SR-17, D-089: paus är ett kontrollstopp via kärnan som nekar agentens verktyg,
        återstart häver stoppet, och pause_all (ny kärnfunktion ControlStops.place_all) stoppar alla agenter.
        Livscykeln rörs inte och inget raderas."""
        self.queue(item("pause_agent", agent="res-1", id="pause-one-0001"))
        self.ingest()
        _, db, system, _ = self.core()
        self.assertIs(system.registry.get("res-1").state, AgentState.ACTIVE)  # SR-17: ingen avstängning utan ärende
        with self.assertRaises(PermissionDenied):
            system.engine.require("res-1", "research.search")
        system.engine.require("lead-1", "research.search")  # andra agenter påverkas inte
        db.close()
        self.queue(item("pause_agent", agent="res-1", id="pause-again-01"))
        _, out = self.ingest()
        self.assertIn("redan pausad", out)
        self.queue(item("resume_agent", agent="res-1", id="resume-one-001"))
        self.ingest()
        _, db, system, _ = self.core()
        system.engine.require("res-1", "research.search")
        db.close()
        self.queue(item("resume_agent", agent="res-1", id="resume-two-001"), item("pause_all", id="pause-all-0001"))
        code, out = self.ingest()
        self.assertIn("1 utförda, 1 avvisade", out)
        config, db, system, _ = self.core()
        agents = system.registry.agents()
        self.assertEqual(len(agents), 7)
        self.assertEqual({s.scope_value for s in system.stops.active()}, {a.agent_id for a in agents})
        for a in agents:
            with self.assertRaises(PermissionDenied):
                system.engine.require(a.agent_id, "report.read")
        self.assertTrue(all(a.state is AgentState.ACTIVE for a in agents))
        self.assertEqual(len(db.connection.execute("SELECT * FROM control_stops").fetchall()), 8)  # det hävda finns kvar
        from aie.dashboard.snapshot import build_snapshot
        snap = build_snapshot(system, config, self.config_dir)
        self.assertTrue(all(a["paused"] and a["status"] == "offline" for a in snap["agents"]["items"]))
        self.assertEqual(len(snap["stops"]["items"]), 7)

    def test_only_founders_can_pause_all(self):
        """Verifies FR-32, SR-05: place_all är bara för grundarna; en agent kan inte pausa alla."""
        from aie.authorization.stops import StopError

        _, db, system, _ = self.core()
        for actor in ("ceo-1", "cro-1", "mallory"):
            with self.assertRaises(StopError):
                system.stops.place_all(actor, "test")
        self.assertEqual(system.stops.active(), ())

    def test_kill_stops_new_transactions_and_deletes_nothing(self):
        """Verifies FR-32, SR-07, §38: nödstoppet från Command Center stoppar nya transaktioner och verktyg, och
        ingenting raderas: ledgern, revisionsloggen och godkännandena finns kvar."""
        _, db, system, _ = self.core()
        count = lambda table: db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: E731
        before = {t: count(t) for t in ("ledger_entries", "audit_log", "approval_requests", "agents", "tasks")}
        self.assertGreater(before["ledger_entries"], 0)
        db.close()
        self.queue(item("kill", confirm="KILL", id="kill-item-0001", note="test"))
        code, out = self.ingest()
        self.assertIn("1 utförda", out)
        _, db, system, _ = self.core()
        self.assertTrue(system.kill.state().engaged)
        self.assertEqual(system.kill.state().engaged_by, "yorgo")
        self.assertTrue(system.kill.spend_block_reasons(None))
        with self.assertRaises(PermissionDenied):
            system.engine.require("lead-1", "sim.spend")
        db.close()
        out2, err2 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
            simulate(self.config_dir, "resume", days=1)  # en dag till: agenterna försöker arbeta
        shutdown_logging()
        _, db, system, _ = self.core()
        count = lambda table: db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: E731
        after = {t: count(t) for t in before}
        costs = db.connection.execute(
            "SELECT COUNT(*) FROM ledger_entries WHERE entry_type = 'cost' AND entry_id > ?", (before["ledger_entries"],)).fetchone()[0]
        self.assertEqual(costs, 0)  # inga nya utgifter under nödstoppet
        for table in before:
            self.assertGreaterEqual(after[table], before[table], table)  # inget raderat
        self.assertTrue(system.audit.verify().ok)
        self.assertTrue(system.kill.state().engaged)  # ett nödstopp från en grundare släpps aldrig av sig självt


    def test_kill_release_goes_through_the_core_and_needs_confirmation_and_reason(self):
        """Verifies FR-32, D-030, D-049: återstart efter nödstopp sker via KillSwitch.vote_release, kräver RELEASE och
        ett skäl, och nekas när nödstoppet inte är aktivt."""
        self.queue(item("kill_release", confirm="RELEASE", note="not engaged", id="release-early-1"))
        _, out = self.ingest()
        self.assertIn("0 utförda, 1 avvisade", out)
        self.queue(item("kill", confirm="KILL", id="kill-item-0002"))
        self.ingest()
        self.queue(item("kill_release", confirm="KILL", note="x", id="release-bad-001"),
                   item("kill_release", confirm="RELEASE", id="release-bad-002"))
        _, out = self.ingest()
        self.assertIn("0 utförda, 2 avvisade", out)
        _, db, system, _ = self.core()
        self.assertTrue(system.kill.state().engaged)
        db.close()
        self.queue(item("kill_release", confirm="RELEASE", note="Checked, safe to restart", id="release-ok-0001",
                        email="robin@example.com", founder="robin"))
        _, out = self.ingest()
        self.assertIn("1 utförda", out)
        _, db, system, _ = self.core()
        self.assertFalse(system.kill.state().engaged)
        self.assertIn("kill.released", [e.action for e in system.audit.entries()])


class TestChain(ControlCase):
    def test_whole_chain_without_the_local_computer(self):
        """Verifies FR-27, FR-31, D-085, D-089: hela kedjan med bara KV emellan, som i GitHub Actions: snapshoten
        publiceras, ett beslut läggs i kön, motorn utför det, och nästa snapshot visar resultatet för båda grundarna."""
        original = pub.KV.from_env
        pub.KV.from_env = classmethod(lambda cls, environ=None: self.kv)
        self.addCleanup(setattr, pub.KV, "from_env", original)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pub.publish(self.config_dir, pilot_root=None), 0)
        shutdown_logging()
        first = json.loads(self.cloud.store["snapshot:latest"])
        self.assertEqual(len([a for a in first["approvals"]["items"] if a["status"] == "pending"]), 3)
        self.queue(item("approve", request=1, email="robin@example.com", founder="robin", id="chain-item-001"))
        code, _ = self.ingest()
        self.assertEqual(code, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pub.publish(self.config_dir, pilot_root=None), 0)
        shutdown_logging()
        second = json.loads(self.cloud.store["snapshot:latest"])
        by_id = {a["id"]: a for a in second["approvals"]["items"]}
        self.assertEqual(by_id[1]["status"], "approved")
        self.assertEqual(by_id[1]["votes"][0]["founder"], "robin")
        self.assertIn("founder control", {e["type"] for e in second["events"]["items"]})
        self.assertTrue(second["audit_chain"]["ok"])
        self.assertNotIn("robin@example.com", json.dumps(second))  # mejladresser går aldrig ut i snapshoten

    def test_state_copy_survives_a_lost_cache(self):
        """Verifies D-093: databasen går att hämta tillbaka ur KV när cachen är borta, med historiken kvar."""
        db_file = self.dir / "data" / "sim.db"
        blob = self.dir / "state.enc"
        blob.write_bytes(db_file.read_bytes())  # krypteringen görs av openssl i workflowen; här provas transporten
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pub.state("put", "company", blob, self.kv), 0)
            for f in (self.dir / "data").glob("sim.db*"):
                f.unlink()
            self.assertEqual(pub.state("get", "company", db_file, self.kv), 0)
        _, db, system, gov = self.core()
        self.assertEqual(len(gov.queue.pending()), 3)
        self.assertTrue(system.audit.verify().ok)


class TestParsing(unittest.TestCase):
    def test_allowed_emails_format(self):
        """Verifies FR-28: ALLOWED_EMAILS tolkas som namn=mejl; adresser utan namn ger ingen grundare."""
        self.assertEqual(control.parse_emails(" Yorgo = Y@X.se , robin=r@y.se, stray@z.se,"),
                         {"y@x.se": "yorgo", "r@y.se": "robin"})
        self.assertEqual(control.parse_emails(None), {})


if __name__ == "__main__":
    unittest.main()
