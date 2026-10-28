"""Tester för hierarkin (Fas 3a). Verifierar FR-09, SR-04 och D-020.

ROADMAP:s nyckeltest för Fas 3 ("CEO försöker höja sin egen gräns → nekas") är
`test_ceo_cannot_raise_own_limit_or_change_own_mandate`.
"""
import re
import tempfile
import unittest
from pathlib import Path

from aie.agents import LEVEL_CEO, LEVEL_CONTROL, LEVEL_HEAD, LEVEL_WORKER, AgentRegistry, AgentState, OrgChart, RegistryError
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.config import ConfigError
from aie.memory import Database

ROOT = Path(__file__).resolve().parents[2]
S = AgentState


class HierarchyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.permissions = load_permissions(ROOT / "config")
        self.registry = AgentRegistry(self.permissions, self.db)
        self.audit = AuditLog(self.db)
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.org = OrgChart(self.registry, self.permissions)

    def add(self, agent_id, role, manager=None):
        self.registry.register(agent_id, role, manager, "yorgo", "test")
        for state in (S.CREATED, S.TESTING, S.ACTIVE):
            self.registry.transition(agent_id, state, "yorgo", "test")

    def build_company(self):
        self.add("ceo-1", "ceo")
        for agent_id, role in (("cfo-1", "cfo"), ("cro-1", "cro"), ("comp-1", "compliance"), ("audit-1", "auditor")):
            self.add(agent_id, role)
        self.add("lead-1", "research_lead", "ceo-1")
        self.add("res-1", "researcher", "lead-1")
        self.add("res-2", "researcher", "lead-1")


class TestLevels(HierarchyCase):
    def test_repo_roles_have_constitution_levels(self):
        """Verifies FR-09: rollerna i permissions.toml ligger på rätt nivå i §8."""
        levels = {name: m.level for name, m in self.permissions.roles.items()}
        self.assertEqual(levels, {
            "ceo": LEVEL_CEO, "cfo": LEVEL_CONTROL, "cro": LEVEL_CONTROL, "compliance": LEVEL_CONTROL,
            "auditor": LEVEL_CONTROL, "research_lead": LEVEL_HEAD, "researcher": LEVEL_WORKER,
            "developer": LEVEL_HEAD,  # D-050: utvecklaragenten rapporterar till CEO
        })

    def test_level_is_required_and_bounded(self):
        """Verifies FR-09: en roll utan nivå, eller med nivå 0 eller 5, är ett konfigurationsfel."""
        base = '[tools]\n"report.write" = "x"\n[roles.r]\ndepartment = "research"\ntools = ["report.write"]\n'
        for extra in ("", "level = 0\n", "level = 5\n", "level = true\n"):
            with self.subTest(extra=extra):
                (self.dir / "permissions.toml").write_text("config_version = 1\n" + base + extra, encoding="utf-8")
                with self.assertRaises(ConfigError) as ctx:
                    load_permissions(self.dir)
                self.assertIn("level", "\n".join(ctx.exception.errors))


class TestReportingLines(HierarchyCase):
    def test_valid_company_registers(self):
        """Verifies FR-09: CEO och kontrollfunktioner under grundarna, chef under CEO, arbetare under chef."""
        self.build_company()
        self.assertEqual(self.org.chain_of_command("res-1"), ("res-1", "lead-1", "ceo-1"))
        self.assertEqual(self.org.chain_of_command("audit-1"), ("audit-1",))
        self.assertEqual(self.org.department_heads("research"), ("lead-1",))
        self.assertEqual(set(self.org.control_functions()), {"cfo-1", "cro-1", "comp-1", "audit-1"})
        self.assertEqual(self.org.subordinates("lead-1"), ("res-1", "res-2"))
        self.assertTrue(self.org.is_above("ceo-1", "res-1"))
        self.assertFalse(self.org.is_above("res-1", "ceo-1"))

    def test_control_functions_cannot_report_to_ceo(self):
        """Verifies FR-09 (§8 nivå 2): CFO, CRO, Compliance och Audit lyder inte under CEO."""
        self.add("ceo-1", "ceo")
        for role in ("cfo", "cro", "compliance", "auditor"):
            with self.subTest(role=role), self.assertRaises(RegistryError) as ctx:
                self.registry.register(f"{role}-x", role, "ceo-1", "yorgo", "test")
            self.assertIn("direkt till grundarna", str(ctx.exception))

    def test_head_must_report_to_ceo(self):
        """Verifies FR-09: en departementschef rapporterar till CEO, inte till grundarna eller en kontrollfunktion."""
        self.add("cfo-1", "cfo")
        for manager in (None, "cfo-1"):
            with self.subTest(manager=manager), self.assertRaises(RegistryError):
                self.registry.register("lead-x", "research_lead", manager, "yorgo", "test")

    def test_worker_needs_manager_in_same_department(self):
        """Verifies FR-09: en arbetsagent behöver en chef på nivå 2–3 i sitt eget departement."""
        self.build_company()
        for manager, fragment in ((None, "nivå 2 eller 3"), ("ceo-1", "nivå 2 eller 3"), ("cfo-1", "samma departement"),
                                  ("res-2", "nivå 2 eller 3")):
            with self.subTest(manager=manager), self.assertRaises(RegistryError) as ctx:
                self.registry.register("res-x", "researcher", manager, "yorgo", "test")
            self.assertIn(fragment, str(ctx.exception))


class TestGovernance(HierarchyCase):
    def setUp(self):
        super().setUp()
        self.build_company()

    def test_ceo_cannot_raise_own_limit_or_change_own_mandate(self):
        """Verifies SR-04 (ROADMAP Fas 3-nyckeltest): CEO som försöker ändra gränser, mandat eller konstitution nekas och loggas."""
        for tool in ("governance.change_limits", "governance.change_mandate", "governance.change_constitution"):
            with self.subTest(tool=tool):
                with self.assertRaises(PermissionDenied) as ctx:
                    self.engine.require("ceo-1", tool)
                self.assertIn("SR-04", str(ctx.exception))
                entry = list(self.audit.entries())[-1]
                self.assertEqual((entry.action, entry.details["tool"]), ("tool.denied", tool))
        self.assertTrue(self.audit.verify().ok)

    def test_no_agent_can_use_governance_tools(self):
        """Verifies SR-04: inte heller kontrollfunktioner eller Audit kan använda styrverktyg."""
        for agent_id in ("cfo-1", "audit-1", "comp-1", "lead-1"):
            with self.subTest(agent=agent_id):
                self.assertFalse(self.engine.check(agent_id, "governance.change_limits").allowed)

    def test_governance_tool_cannot_be_granted_in_config(self):
        """Verifies SR-04: permissions.toml som ger en roll ett styrverktyg stoppar uppstart."""
        text = (ROOT / "config" / "permissions.toml").read_text(encoding="utf-8")
        # CEO:s verktygsrad, oavsett vilka verktyg den har i dag (första rollen i filen).
        text = re.sub(r"^tools = \[.*\]$", 'tools = ["report.read", "governance.change_limits"]', text, count=1, flags=re.M)
        (self.dir / "permissions.toml").write_text(text, encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            load_permissions(self.dir)
        self.assertIn("styrverktyg som bara grundarna", "\n".join(ctx.exception.errors))


if __name__ == "__main__":
    unittest.main()
