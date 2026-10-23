"""Tester för src/aie/agents och src/aie/authorization (förberedelse för Fas 2).

Verifierar FR-05, FR-06, SR-01, SR-02, SR-03, SR-13 och SR-14. Nyckeltestet från ROADMAP
("en agent försöker använda ett verktyg utanför mandatet → nekas och loggas") är
`test_tool_outside_mandate_denied_and_logged`.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aie.agents import TRANSITIONS, AgentRegistry, AgentState, IllegalTransition, RegistryError
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.config import ConfigError
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState

VALID = """
config_version = 1
[tools]
"report.write" = "skriva"
"ledger.read" = "läsa ledgern"
[roles.cfo]
department = "finance"
tools = ["report.write", "ledger.read"]
[roles.researcher]
department = "research"
tools = ["report.write"]
"""


def make_active(registry, agent_id, role, manager=None):
    registry.register(agent_id, role, manager, "yorgo", "test")
    for state in (S.CREATED, S.TESTING, S.ACTIVE):
        registry.transition(agent_id, state, "yorgo", "test")


class PermissionsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def load(self, text):
        (self.dir / "permissions.toml").write_text(text, encoding="utf-8")
        return load_permissions(self.dir)

    def assert_invalid(self, text, *fragments):
        with self.assertRaises(ConfigError) as ctx:
            self.load(text)
        joined = "\n".join(ctx.exception.errors)
        for fragment in fragments:
            self.assertIn(fragment, joined)
        return ctx.exception


class TestPermissionsFile(PermissionsCase):
    def test_default_permissions_in_repo_load(self):
        """Verifies SR-02: config/permissions.toml är giltig och har MVP:ns sex roller."""
        permissions = load_permissions(ROOT / "config")
        self.assertEqual(
            set(permissions.roles), {"ceo", "cfo", "cro", "auditor", "research_lead", "researcher"}
        )
        for mandate in permissions.roles.values():
            self.assertTrue(mandate.tools <= set(permissions.tools))

    def test_mandates_cannot_be_changed_at_runtime(self):
        """Verifies SR-03: varken roller eller mandat kan ändras efter laddning."""
        permissions = self.load(VALID)
        with self.assertRaises(TypeError):
            permissions.roles["cfo"] = permissions.roles["researcher"]
        with self.assertRaises(AttributeError):
            permissions.roles["cfo"].tools.add("report.read")

    def test_tool_not_in_catalog_is_error(self):
        """Verifies SR-02: ett stavfel i ett mandat stoppar uppstart i stället för att tyst saknas."""
        self.assert_invalid(
            VALID.replace('tools = ["report.write"]\n', 'tools = ["report.wirte"]\n'),
            "verktyget 'report.wirte' finns inte i [tools]",
        )

    def test_all_errors_collected(self):
        """Verifies SR-02: alla fel i filen listas på en gång."""
        broken = VALID.replace("config_version = 1", "config_version = 2").replace(
            'department = "research"', 'department = "magic"\nbudget = 5'
        )
        error = self.assert_invalid(
            broken, "config_version = 2 stöds inte", "department = 'magic' är okänt", "okänd nyckel 'budget'"
        )
        self.assertGreaterEqual(len(error.errors), 3)

    def test_secret_rejected(self):
        """Verifies SR-10: hemligheter avvisas även i permissions.toml."""
        self.assert_invalid(VALID + '[roles.cfo2]\ndepartment = "finance"\ntools = []\napi_key = "x"\n',
                            "api_key ser ut som en hemlighet")

    def test_invalid_names_and_duplicates(self):
        """Verifies SR-02: ogiltiga verktygsnamn och dubbletter avvisas."""
        self.assert_invalid(
            VALID.replace('"ledger.read" = "läsa ledgern"', '"Ledger" = "x"').replace(
                'tools = ["report.write"]\n', 'tools = ["report.write", "report.write"]\n'
            ),
            "verktygsnamnet 'Ledger' är ogiltigt",
            "samma verktyg står flera gånger",
        )

    def test_missing_file(self):
        """Verifies SR-02: utan permissions.toml finns inga mandat, och det är ett fel."""
        with self.assertRaises(ConfigError):
            load_permissions(self.dir)


class TestLifecycle(unittest.TestCase):
    def test_every_state_has_transition_rules(self):
        """Verifies FR-06: alla sju tillstånd finns och RETIRED är slutgiltigt."""
        self.assertEqual(set(TRANSITIONS), set(S))
        self.assertEqual(TRANSITIONS[S.RETIRED], frozenset())

    def test_every_non_retired_state_can_be_retired(self):
        """Verifies FR-06: en agent kan alltid avvecklas kontrollerat (§34)."""
        for state, targets in TRANSITIONS.items():
            if state is not S.RETIRED:
                self.assertIn(S.RETIRED, targets, state)

    def test_suspended_cannot_jump_to_active(self):
        """Verifies FR-06: en avstängd agent går tillbaka via PROBATION, aldrig direkt till ACTIVE."""
        self.assertNotIn(S.ACTIVE, TRANSITIONS[S.SUSPENDED])


class RegistryCase(PermissionsCase):
    def setUp(self):
        super().setUp()
        self.permissions = self.load(VALID)
        self.db = self.open_db()
        self.registry = AgentRegistry(self.permissions, self.db, clock=lambda: "2026-10-23T12:00:00+00:00")

    def open_db(self):
        db = Database.open(self.dir / "data", "sim")
        self.addCleanup(db.close)
        return db


class TestRegistry(RegistryCase):
    def test_register_records_role_department_manager_state(self):
        """Verifies FR-05: agenten får ID, roll, departement från rollen, chef och status PROPOSED."""
        make_active(self.registry, "cfo-1", "cfo")
        agent = self.registry.register("res-1", "researcher", "cfo-1", "yorgo", "behövs")
        self.assertEqual(
            (agent.role, agent.department, agent.manager_id, agent.state),
            ("researcher", "research", "cfo-1", S.PROPOSED),
        )

    def test_illegal_transition_rejected(self):
        """Verifies FR-06: PROPOSED kan inte bli ACTIVE direkt."""
        self.registry.register("res-1", "researcher", None, "yorgo", "test")
        with self.assertRaises(IllegalTransition):
            self.registry.transition("res-1", S.ACTIVE, "yorgo", "genväg")
        self.assertEqual(self.registry.get("res-1").state, S.PROPOSED)

    def test_agent_cannot_change_own_state(self):
        """Verifies SR-03: en agent kan inte flytta sig själv ur en avstängning."""
        make_active(self.registry, "res-1", "researcher")
        self.registry.transition("res-1", S.SUSPENDED, "yorgo", "felaktiga rapporter")
        with self.assertRaises(RegistryError):
            self.registry.transition("res-1", S.PROBATION, "res-1", "jag lovar")

    def test_reason_required_and_history_kept(self):
        """Verifies SR-14: varje ändring kräver motivering och sparas; historiken finns kvar efter avveckling."""
        make_active(self.registry, "res-1", "researcher")
        with self.assertRaises(RegistryError):
            self.registry.transition("res-1", S.RETIRED, "yorgo", " ")
        self.registry.transition("res-1", S.RETIRED, "yorgo", "rollen behövs inte")
        states = [c.new for c in self.registry.history("res-1")]
        self.assertEqual(states, [S.PROPOSED, S.CREATED, S.TESTING, S.ACTIVE, S.RETIRED])

    def test_invalid_registrations(self):
        """Verifies FR-05: okänd roll, dubblett, okänd chef och egen chef avvisas."""
        self.registry.register("res-1", "researcher", None, "yorgo", "test")
        for args in (
            ("res-2", "wizard", None),
            ("res-1", "researcher", None),
            ("res-3", "researcher", "ghost"),
            ("res-4", "researcher", "res-4"),
            ("Res 5", "researcher", None),
        ):
            with self.subTest(args=args), self.assertRaises(RegistryError):
                self.registry.register(*args, "yorgo", "test")
        self.assertEqual([a.agent_id for a in self.registry.agents()], ["res-1"])


class TestRegistryPersistence(RegistryCase):
    def test_registry_survives_restart(self):
        """Verifies FR-03 och FR-05: agenter, status och historik finns kvar efter omstart."""
        make_active(self.registry, "cfo-1", "cfo")
        self.registry.register("res-1", "researcher", "cfo-1", "yorgo", "behövs")
        self.db.close()
        registry = AgentRegistry(self.permissions, self.open_db())
        self.assertEqual(registry.get("cfo-1").state, S.ACTIVE)
        self.assertEqual(registry.get("res-1").manager_id, "cfo-1")
        self.assertEqual(len(registry.history("cfo-1")), 4)

    def test_database_blocks_delete_and_identity_change(self):
        """Verifies SR-14: databasen vägrar radera agenter och ändra roll eller chef."""
        make_active(self.registry, "res-1", "researcher")
        execute = self.db.connection.execute
        for sql in (
            "DELETE FROM agents WHERE agent_id = 'res-1'",
            "UPDATE agents SET role = 'cfo' WHERE agent_id = 'res-1'",
            "UPDATE agent_state_changes SET reason = 'omskriven'",
            "DELETE FROM agent_state_changes",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                execute(sql)
        self.assertEqual(self.registry.get("res-1").role, "researcher")

    def test_failed_transition_changes_nothing(self):
        """Verifies FR-06: en otillåten övergång lämnar varken ny status eller historikrad."""
        self.registry.register("res-1", "researcher", None, "yorgo", "test")
        with self.assertRaises(IllegalTransition):
            self.registry.transition("res-1", S.ACTIVE, "yorgo", "genväg")
        self.assertEqual(self.registry.get("res-1").state, S.PROPOSED)
        self.assertEqual(len(self.registry.history("res-1")), 1)

    def test_state_column_rejects_unknown_state(self):
        """Verifies FR-06: databasen godtar bara de sju tillstånden."""
        self.registry.register("res-1", "researcher", None, "yorgo", "test")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute("UPDATE agents SET state = 'GOD_MODE'")


class TestAuthorization(RegistryCase):
    def setUp(self):
        super().setUp()
        self.audit = AuditLog(self.db)
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        make_active(self.registry, "res-1", "researcher")

    def test_tool_in_mandate_allowed_and_logged(self):
        """Verifies SR-01: ett verktyg i mandatet tillåts, och beslutet loggas."""
        self.assertTrue(self.engine.check("res-1", "report.write").allowed)
        (entry,) = self.audit.entries()
        self.assertEqual((entry.action, entry.details["tool"]), ("tool.allowed", "report.write"))

    def test_tool_outside_mandate_denied_and_logged(self):
        """Verifies SR-02 (ROADMAP Fas 2-nyckeltest): verktyg utanför mandatet nekas och loggas."""
        with self.assertRaises(PermissionDenied) as ctx:
            self.engine.require("res-1", "ledger.read")
        self.assertIn("ingår inte i mandatet", str(ctx.exception))
        (entry,) = self.audit.entries()
        self.assertEqual(entry.action, "tool.denied")
        self.assertEqual(entry.details, {"agent_id": "res-1", "tool": "ledger.read",
                                         "reason": "verktyget ingår inte i mandatet för researcher"})
        self.assertTrue(self.audit.verify().ok)

    def test_default_deny_cases(self):
        """Verifies SR-02: okänt verktyg, okänd agent och agenter som inte får agera nekas."""
        self.registry.register("new-1", "researcher", None, "yorgo", "test")
        make_active(self.registry, "sus-1", "researcher")
        self.registry.transition("sus-1", S.SUSPENDED, "yorgo", "test")
        for agent_id, tool, reason in (
            ("res-1", "money.send", "finns inte i katalogen"),
            ("ghost", "report.write", "finns inte i registret"),
            ("new-1", "report.write", "PROPOSED"),
            ("sus-1", "report.write", "SUSPENDED"),
        ):
            with self.subTest(agent=agent_id, tool=tool):
                decision = self.engine.check(agent_id, tool)
                self.assertFalse(decision.allowed)
                self.assertIn(reason, decision.reason)

    def test_retired_agent_loses_all_tools(self):
        """Verifies SR-14: en avvecklad agent får inga verktyg alls."""
        self.registry.transition("res-1", S.RETIRED, "yorgo", "avvecklad")
        self.assertFalse(self.engine.check("res-1", "report.write").allowed)

    def test_testing_agent_only_in_sim(self):
        """Verifies SR-13: en agent som testas får agera i sim men aldrig i prod."""
        self.registry.register("t-1", "researcher", None, "yorgo", "test")
        self.registry.transition("t-1", S.CREATED, "yorgo", "test")
        self.registry.transition("t-1", S.TESTING, "yorgo", "test")
        prod = AuthorizationEngine(self.permissions, self.registry, "prod")
        self.assertTrue(self.engine.check("t-1", "report.write").allowed)
        decision = prod.check("t-1", "report.write")
        self.assertFalse(decision.allowed)
        self.assertIn("SR-13", decision.reason)

    def test_audit_failure_means_deny(self):
        """Verifies SR-01 (§59): kan beslutet inte loggas blir svaret nej."""
        audit_db = Database.open(self.dir / "audit", "sim")
        engine = AuthorizationEngine(self.permissions, self.registry, "sim", AuditLog(audit_db))
        audit_db.close()  # loggen kan inte längre skrivas, men registret fungerar
        decision = engine.check("res-1", "report.write")
        self.assertFalse(decision.allowed)
        self.assertIn("audit-loggen kunde inte skrivas", decision.reason)

    def test_unreadable_registry_means_deny(self):
        """Verifies SR-01 (§59): kan kontrollen inte genomföras blir svaret nej, ingen krasch."""
        engine = AuthorizationEngine(self.permissions, self.registry, "sim")
        self.db.close()
        decision = engine.check("res-1", "report.write")
        self.assertFalse(decision.allowed)
        self.assertIn("kunde inte avgöra", decision.reason)


if __name__ == "__main__":
    unittest.main()
