"""Command Center Del 1: snapshoten, publiceringen till KV och tillståndskopian (`aie.dashboard.snapshot`, `publish`)."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path

from aie import runtime
from aie.dashboard import publish as pub
from aie.dashboard.snapshot import build_snapshot, check_snapshot
from aie.ledger import EntryType, compute_result
from aie.ledger.ledger import Approval, DuplicateEntry, EntryDraft, Status
from aie.ledger.results import recompute
from aie.monitoring import shutdown_logging
from aie.simulation.market import SimClock
from aie.simulation.run import stored_run
from aie.simulation.seed import seed
from aie.simulation.cli import simulate
from aie.system import build_system

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SnapshotCase(unittest.TestCase):
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

    def open_system(self):
        config = runtime._load(self.config_dir, console=False)
        db = runtime._open(config)
        self.addCleanup(db.close)
        run = stored_run(db)
        system = build_system(config, db, self.config_dir, clock=SimClock(run["start_date"]) if run else None)
        return config, db, system

    def snapshot(self):
        config, db, system = self.open_system()
        return build_snapshot(system, config, self.config_dir, now="2026-11-09T12:00:00+00:00"), config, db, system


class TestNumbers(SnapshotCase):
    def test_snapshot_matches_the_audit_agents_recomputation(self):
        """Verifies ER-16, FR-29, D-085: snapshotens siffror är exakt de som revisionsagentens `recompute` räknar
        direkt ur tabellerna, totalt, per period och per bokförare."""
        seed(self.config_dir, days=12)
        snap, config, db, system = self.snapshot()
        entries = system.ledger.entries("SIM")
        reported = compute_result(entries, "SIM")
        self.assertEqual(recompute(db, system.engine, frozenset(config.system.founders), "audit-1", reported), ())
        econ = snap["economy"]
        self.assertEqual(econ["revenue_gross"]["value"], reported.revenue_minor)
        self.assertEqual(econ["refunds"]["value"], reported.refunds_minor)
        self.assertEqual(econ["costs"]["value"], reported.costs_minor)
        self.assertEqual(econ["platform_fees"]["value"], reported.fees_minor)
        self.assertEqual(econ["net_profit_realized"]["value"], reported.net_minor)
        self.assertGreater(econ["revenue_gross"]["value"], 0)
        # brutto och netto hålls isär: netto = brutto - återbetalningar - kostnader - avgifter
        self.assertEqual(econ["net_profit_realized"]["value"], econ["revenue_gross"]["value"] - econ["refunds"]["value"]
                         - econ["costs"]["value"] - econ["platform_fees"]["value"])
        sql = dict(db.connection.execute(
            "SELECT e.entry_type, SUM(e.amount_minor) FROM ledger_entries e WHERE e.currency = 'SIM' AND "
            "(SELECT status FROM ledger_status s WHERE s.entry_id = e.entry_id ORDER BY id DESC LIMIT 1) = 'settled' "
            "GROUP BY e.entry_type").fetchall())
        self.assertEqual(econ["revenue_gross"]["value"], sql.get("revenue", 0))
        for name in ("day", "week", "month"):
            items = snap["periods"][name]["items"]
            self.assertEqual(sum(i["revenue"] for i in items), reported.revenue_minor, name)
            self.assertEqual(sum(i["net"] for i in items), reported.net_minor, name)
        self.assertEqual(sum(i["net"] for i in snap["per_agent"]["items"]), reported.net_minor)
        self.assertEqual(econ["tax_reserve"]["value"], system.tax.reserved_minor("SIM"))

    def test_every_number_has_value_source_and_as_of_and_missing_is_null(self):
        """Verifies FR-29, D-085: varje siffra är {value, source, as_of}; utan data är värdet None (visas som N/A)."""
        snap, *_ = self.snapshot()
        for section in ("system", "economy"):
            for name, m in snap[section].items():
                if isinstance(m, dict) and "value" in m:
                    self.assertEqual(set(m), {"value", "source", "as_of"}, f"{section}.{name}")
                    self.assertTrue(m["source"])
        self.assertIsNone(snap["economy"]["revenue_gross"]["value"])
        self.assertIsNone(snap["economy"]["net_profit_realized"]["value"])
        self.assertIsNone(snap["system"]["last_run"]["value"])
        for section in ("periods", "per_agent", "ledger", "agents", "approvals", "events", "quotas"):
            container = snap[section]["day"] if section == "periods" else snap[section]
            self.assertIn("source", container)
            self.assertIn("as_of", container)
        self.assertTrue(snap["audit_chain"]["ok"])
        json.dumps(snap)  # helt JSON-bart

    def test_agents_come_from_the_registry_and_unknown_progress_is_null(self):
        """Verifies FR-29: agenterna är de registrerade, med departement ur config, och framsteg som inte
        registreras i kärnan är None i stället för en påhittad siffra."""
        seed(self.config_dir, days=3)
        snap, config, db, system = self.snapshot()
        ids = {a.agent_id for a in system.registry.agents()}
        self.assertEqual({a["id"] for a in snap["agents"]["items"]}, ids)
        deps = {d["id"] for d in snap["departments"]["items"]}
        self.assertEqual(deps, {"executive", "finance", "risk", "compliance", "audit", "research"})
        for a in snap["agents"]["items"]:
            self.assertIsNone(a["progress"])
            self.assertIn(a["status"], {"working", "waiting", "idle", "blocked", "offline", "unknown"})
        lead = next(a for a in snap["agents"]["items"] if a["id"] == "lead-1")
        self.assertEqual(lead["status"], "waiting")  # tre förslag väntar på grundarna (D0b)
        self.assertEqual(len([a for a in snap["approvals"]["items"] if a["status"] == "pending"]), 3)


class TestDuplicates(SnapshotCase):
    def test_duplicate_transactions_are_refused_and_counted_once(self):
        """Verifies ER-07, D-085: ett omförsök med samma idempotensnyckel ger samma post (räknas en gång), och en
        annan post med samma externa ID avvisas och loggas."""
        config, db, system = self.open_system()
        draft = EntryDraft("sale-0001", "research", 12_500, "SIM", EntryType.REVENUE, "test-initiative",
                           Approval.NOT_REQUIRED, ("report:test",), external_id="etsy:order:1", status=Status.SETTLED)
        first = system.ledger.record("system:simulation", draft)
        again = system.ledger.record("system:simulation", draft)
        self.assertEqual(again.entry_id, first.entry_id)
        with self.assertRaises(DuplicateEntry):
            system.ledger.record("system:simulation", EntryDraft(
                "sale-0002", "research", 12_500, "SIM", EntryType.REVENUE, "test-initiative", Approval.NOT_REQUIRED,
                ("report:test",), external_id="etsy:order:1", status=Status.SETTLED))
        snap = build_snapshot(system, config, self.config_dir)
        self.assertEqual(snap["economy"]["revenue_gross"]["value"], 12_500)
        self.assertEqual(snap["ledger"]["total"], 1)
        actions = [e.action for e in system.audit.entries()]
        self.assertEqual(actions.count("ledger.duplicate_refused"), 1)
        self.assertEqual(actions.count("ledger.recorded"), 1)

    def test_event_ids_are_unique(self):
        """Verifies D-085: varje händelse i snapshoten har ett unikt id, så inget visas eller räknas två gånger."""
        seed(self.config_dir, days=5)
        snap, *_ = self.snapshot()
        ids = [e["id"] for e in snap["events"]["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(ids)
        ledger_ids = [r["id"] for r in snap["ledger"]["items"]]
        self.assertEqual(len(ledger_ids), len(set(ledger_ids)))

    def test_secret_like_text_stops_the_snapshot(self):
        """Verifies SR-10, DR-13: ett värde som ser ut som en hemlighet stoppar snapshoten."""
        with self.assertRaises(ValueError):
            check_snapshot({"agents": {"items": [{"description": "api_key=" + "a" * 40}]}})


class TestPublish(SnapshotCase):
    def test_kv_put_uses_the_right_url_header_and_ttl(self):
        """Verifies D-085, SR-10: rätt Cloudflare-adress, token bara i Authorization, och TTL på historiken."""
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return FakeResponse(200)

        kv = pub.KV("cf-token-test", "acc123", "ns456", opener=opener)
        self.assertEqual(pub.publish_snapshot({"generated_at": "2026-11-09T12:00:00+00:00", "x": 1}, kv,
                                              self.dir / "pending"), "published")
        self.assertEqual([c.full_url.split("/values/")[1] for c in calls],
                         ["snapshot%3Alatest", f"snapshot%3A2026-11-09?expiration_ttl={pub.HISTORY_TTL}"])
        self.assertTrue(all(c.full_url.startswith("https://api.cloudflare.com/client/v4/accounts/acc123/storage/kv/"
                                                  "namespaces/ns456/values/") for c in calls))
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer cf-token-test")
        self.assertEqual(calls[0].get_method(), "PUT")

    def test_failed_upload_is_logged_kept_and_never_raises(self):
        """Verifies D-085: misslyckas uppladdningen sparas snapshoten lokalt för nästa försök, och inget fel kastas."""
        def opener(request, timeout):
            raise urllib.error.URLError("network down")

        pub.time.sleep, sleep = (lambda s: None), pub.time.sleep
        self.addCleanup(setattr, pub.time, "sleep", sleep)
        kv = pub.KV("t", "a", "n", opener=opener)
        result = pub.publish_snapshot({"generated_at": "2026-11-09T12:00:00+00:00"}, kv, self.dir / "pending")
        self.assertEqual(result, "failed")
        self.assertTrue((self.dir / "pending" / "snapshot.json").exists())
        self.assertEqual(pub.publish_snapshot({"generated_at": "x"}, None, self.dir / "pending"), "skipped")

    def test_agents_keep_working_when_reporting_fails(self):
        """Verifies D-085: när publiceringen fallerar avslutar `publish` med 0, och agenterna kör nästa dag som vanligt
        med intakt revisionskedja."""
        seed(self.config_dir, days=2)
        pub.time.sleep, sleep = (lambda s: None), pub.time.sleep
        self.addCleanup(setattr, pub.time, "sleep", sleep)
        broken = pub.KV("t", "a", "n", opener=lambda r, timeout: (_ for _ in ()).throw(urllib.error.URLError("down")))
        original = pub.KV.from_env
        pub.KV.from_env = classmethod(lambda cls, environ=None: broken)
        self.addCleanup(setattr, pub.KV, "from_env", original)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(pub.publish(self.config_dir, pilot_root=None), 0)
            code = simulate(self.config_dir, "resume", days=1)
        shutdown_logging()
        self.assertIn("failed", out.getvalue())
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("revisionslogg OK", out.getvalue())
        self.assertIn("Klar till dag 3", out.getvalue())

    def test_state_copy_round_trip_and_no_kv_is_not_an_error(self):
        """Verifies D-085: den krypterade databaskopian går till och från KV oförändrad; utan KV hoppas steget över."""
        store = {}

        def opener(request, timeout):
            key = request.full_url.split("/values/")[1].split("?")[0]
            if request.get_method() == "PUT":
                store[key] = request.data
                return FakeResponse(200)
            if key not in store:
                raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)
            return FakeResponse(200, store[key])

        kv = pub.KV("t", "a", "n", opener=opener)
        blob = self.dir / "company.enc"
        blob.write_bytes(b"Salted__" + bytes(range(256)))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pub.state("put", "company", blob, kv), 0)
            self.assertEqual(pub.state("get", "company", self.dir / "back.enc", kv), 0)
            self.assertEqual(pub.state("get", "pilot", self.dir / "none.enc", kv), 3)
            self.assertEqual(pub.state("put", "evil", blob, kv), 1)
        self.assertEqual((self.dir / "back.enc").read_bytes(), blob.read_bytes())
        original = pub.KV.from_env
        pub.KV.from_env = classmethod(lambda cls, environ=None: None)
        self.addCleanup(setattr, pub.KV, "from_env", original)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pub.state("put", "company", blob), 0)


if __name__ == "__main__":
    unittest.main()
