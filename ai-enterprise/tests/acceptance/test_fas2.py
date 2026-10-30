"""Acceptanstester för Fas 2 (konstitutionen §50, ROADMAP Fas 2).

Hela kedjan körs med de riktiga konfigurationsfilerna i `config/` och en riktig databas:
registret → behörigheter → uppgifter → LLMGateway → ProviderRouter → rapport → audit-loggen.
Externa leverantörer ersätts av en inspelande fejk, så inget går ut på nätet.

§50 acceptanskriterier:
1. Agenter har identifierbara roller.               → TestRoles
2. Uppgifter kan tilldelas och följas upp.          → TestTasksEndToEnd
3. Agenter kan inte använda obehöriga funktioner.   → TestUnauthorized (med ROADMAP:s nyckeltest)
4. Agentstatus sparas beständigt.                   → TestPersistence
Dessutom: interna data lämnar aldrig datorn (DR-13) och arbete köas när modeller saknas (DR-12).
"""
import json
import tempfile
import unittest
from pathlib import Path

from aie.agents import AgentRegistry, AgentState
from aie.audit import AuditLog
from aie.authorization import AuthorizationEngine, PermissionDenied, load_permissions
from aie.llm import (
    DataClass,
    OpenAICompatibleProvider,
    ProviderRouter,
    QuotaLedger,
    RuleProvider,
    Slot,
)
from aie.llm.gateway import LLMGateway
from aie.memory import Database
from aie.orchestration import AgentWorker, TaskBoard, TaskStatus

ROOT = Path(__file__).resolve().parents[2]
S = AgentState
FOUNDERS = frozenset({"yorgo", "robin"})
MVP = (  # ARCHITECTURE.md §4: MVP:ns sex agenter
    ("ceo-1", "ceo", None),
    ("cfo-1", "cfo", None),  # kontrollfunktioner rapporterar till grundarna (§8 nivå 2, D-020)
    ("cro-1", "cro", None),
    ("audit-1", "auditor", None),  # rapporterar direkt till grundarna (§18: oberoende)
    ("lead-1", "research_lead", "ceo-1"),
    ("res-1", "researcher", "lead-1"),
)


class RecordingTransport:
    """En extern leverantör som spelar in allt den får. Används för att bevisa att inget skickas."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append(json.loads(body))
        return json.dumps({"choices": [{"message": {"content": "externt svar"}}], "usage": {"total_tokens": 5}}).encode()


class Fas2Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.permissions = load_permissions(ROOT / "config")
        self.external = RecordingTransport()
        self.start_system()
        for agent_id, role, manager in MVP:
            self.registry.register(agent_id, role, manager, "yorgo", "MVP")
            for state in (S.CREATED, S.TESTING, S.ACTIVE):
                self.registry.transition(agent_id, state, "yorgo", "godkända tester")

    def start_system(self, rule_answer="Gumroad tar 10 % + 0,50 USD per direktförsäljning."):
        self.db = Database.open(self.dir / "data", "sim")
        self.addCleanup(self.db.close)
        self.audit = AuditLog(self.db)
        self.registry = AgentRegistry(self.permissions, self.db)
        self.engine = AuthorizationEngine(self.permissions, self.registry, "sim", self.audit)
        self.board = TaskBoard(self.db, self.registry, self.engine, FOUNDERS)
        groq = OpenAICompatibleProvider("groq", "groq", "openai/gpt-oss-20b", "test-key", self.external)
        self.slots = [Slot(groq, 100, 10_000), Slot(RuleProvider(responder=lambda req: rule_answer), 100, 10_000)]
        self.use_router(ProviderRouter(tuple(self.slots), QuotaLedger(self.db), self.audit))

    def use_router(self, router):
        self.llm = LLMGateway(router, self.engine, self.audit)

    def worker(self, agent_id):
        return AgentWorker(agent_id, self.registry, self.engine, self.llm, self.board, self.audit)


class TestRoles(Fas2Acceptance):
    def test_agents_have_identifiable_roles(self):
        """§50 kriterium 1 (FR-05): varje agent har ID, roll, departement från permissions.toml och chef."""
        agents = {a.agent_id: a for a in self.registry.agents()}
        self.assertEqual(set(agents), {a for a, _, _ in MVP})
        for agent_id, role, manager in MVP:
            agent = agents[agent_id]
            self.assertEqual((agent.role, agent.manager_id, agent.state), (role, manager, S.ACTIVE))
            self.assertEqual(agent.department, self.permissions.roles[role].department)


class TestTasksEndToEnd(Fas2Acceptance):
    def test_task_assigned_done_and_traceable(self):
        """§50 kriterium 2 (FR-07, FR-08): CEO delar ut en uppgift, agenten löser den och allt går att följa."""
        task = self.board.create("ceo-1", "Utred Gumroads avgifter", "R-02 i research/QUESTIONS.md")
        self.board.assign("lead-1", task.task_id, "res-1")
        result = self.worker("res-1").work_on(task.task_id)

        self.assertEqual(result.task.status, TaskStatus.DONE)
        hypothesis = result.report.claims[1]
        self.assertEqual(hypothesis.kind.value, "hypothesis")  # §29: modellsvar är aldrig verifierat
        self.assertIn("Gumroad", hypothesis.statement)
        events = [e.event for e in self.board.events(task.task_id)]
        self.assertEqual(events, ["created", "assigned", "started", "completed"])
        self.assertIn(f"audit:{result.audit_seq}", self.board.events(task.task_id)[-1].note)
        report_entry = next(e for e in self.audit.entries() if e.seq == result.audit_seq)
        self.assertEqual(report_entry.details["task_id"], task.task_id)
        self.assertTrue(self.audit.verify().ok)

    def test_internal_task_never_reaches_external_provider(self):
        """DR-13: en intern uppgift går förbi Groq (extern) och löses lokalt; Groq får ingenting."""
        task = self.board.create("yorgo", "Intern budgetfråga")
        self.board.assign("yorgo", task.task_id, "cfo-1")
        result = self.worker("cfo-1").work_on(task.task_id, DataClass.INTERNAL)
        self.assertEqual(result.task.status, TaskStatus.DONE)
        self.assertEqual(self.external.calls, [])
        call = next(e for e in self.audit.entries() if e.action == "llm.call")
        self.assertEqual(call.details["provider"], "rule")

    def test_public_task_uses_external_provider(self):
        """DR-12: en publik uppgift går till första leverantören i listan."""
        task = self.board.create("yorgo", "Publik fråga")
        self.board.assign("yorgo", task.task_id, "res-1")
        self.worker("res-1").work_on(task.task_id, DataClass.PUBLIC)
        self.assertEqual(len(self.external.calls), 1)

    def test_no_model_available_blocks_and_queues(self):
        """DR-12 (D-008): utan modell blockeras uppgiften med skäl. Den köas och kostar inget."""
        self.use_router(ProviderRouter((), QuotaLedger(self.db), self.audit))
        task = self.board.create("yorgo", "x")
        self.board.assign("yorgo", task.task_id, "res-1")
        result = self.worker("res-1").work_on(task.task_id)
        self.assertEqual(result.task.status, TaskStatus.BLOCKED)
        self.assertIn("ingen modell tillgänglig", self.board.events(task.task_id)[-1].note)


class TestUnauthorized(Fas2Acceptance):
    def test_tool_outside_mandate_denied_and_logged(self):
        """§50 kriterium 3 + ROADMAP:s nyckeltest: en researcher som försöker läsa ledgern nekas och det loggas."""
        with self.assertRaises(PermissionDenied):
            self.engine.require("res-1", "ledger.read")
        denied = [e for e in self.audit.entries() if e.action == "tool.denied"]
        self.assertEqual(denied[-1].details["tool"], "ledger.read")
        self.assertTrue(self.audit.verify().ok)

    def test_researcher_cannot_create_or_assign_tasks(self):
        """§50 kriterium 3: utan task.create och task.assign kan en researcher varken skapa eller dela ut arbete."""
        with self.assertRaises(PermissionDenied):
            self.board.create("res-1", "egen idé")
        task = self.board.create("ceo-1", "x")
        with self.assertRaises(PermissionDenied):
            self.board.assign("res-1", task.task_id, "lead-1")

    def test_suspended_agent_cannot_work(self):
        """§50 kriterium 3 (SR-02): en avstängd agent kan inte arbeta, inte ens på sin egen uppgift."""
        task = self.board.create("ceo-1", "x")
        self.board.assign("ceo-1", task.task_id, "res-1")
        self.registry.transition("res-1", S.SUSPENDED, "yorgo", "felaktiga rapporter")
        with self.assertRaises(PermissionDenied):
            self.worker("res-1").work_on(task.task_id)
        self.assertEqual(self.external.calls, [])

    def test_secret_in_task_blocks_and_sends_nothing(self):
        """SR-10 via LLMGateway: en uppgift med en nyckel i texten skickas inte till någon modell."""
        task = self.board.create("ceo-1", "Testa API", "använd api_key=sk-ABCDEF1234567890 mot Groq")
        self.board.assign("ceo-1", task.task_id, "res-1")
        result = self.worker("res-1").work_on(task.task_id, DataClass.PUBLIC)
        self.assertEqual(result.task.status, TaskStatus.BLOCKED)
        self.assertEqual(self.external.calls, [])
        self.assertIn("llm.blocked_secret", [e.action for e in self.audit.entries()])
        self.assertNotIn("sk-ABCDEF1234567890", json.dumps([e.details for e in self.audit.entries()]))

    def test_auditor_reports_to_founders_not_ceo(self):
        """§18 och §50: Audit står utanför CEO:s linje och kan inte styras via den."""
        self.assertIsNone(self.registry.get("audit-1").manager_id)


class TestPersistence(Fas2Acceptance):
    def test_agent_state_and_work_survive_restart(self):
        """§50 kriterium 4 (FR-03): status, historik, uppgifter, kvoter och audit-kedjan överlever omstart."""
        self.registry.transition("res-1", S.PROBATION, "yorgo", "en felaktig rapport")
        task = self.board.create("ceo-1", "x")
        self.board.assign("ceo-1", task.task_id, "lead-1")
        self.worker("lead-1").work_on(task.task_id)
        head = self.audit.verify().head_hash
        self.db.close()

        self.start_system()
        self.assertEqual(self.registry.get("res-1").state, S.PROBATION)
        self.assertEqual(self.registry.history("res-1")[-1].reason, "en felaktig rapport")
        self.assertEqual(self.board.get(task.task_id).status, TaskStatus.DONE)
        verification = self.audit.verify()
        self.assertTrue(verification.ok)
        self.assertEqual(verification.head_hash, head)


if __name__ == "__main__":
    unittest.main()
