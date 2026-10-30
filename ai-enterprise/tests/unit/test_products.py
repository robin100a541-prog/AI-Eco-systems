"""Tester för produktutkasten (PR 11). Verifierar arbetsorder 02 PR 11, D-056, D-058 och §6."""
from pathlib import Path

from aie.registry import import_dir, import_file

from .test_registry import RegisterCase

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "products"
SECTIONS = (("## Produkt", "## Tjänst"), ("## Annonstext", "## Tjänstebeskrivning"), "## Pris", "## Valideringsplan", "## Mätbara kriterier och regel",
            "## Checklista för grundarna")


class TestProductDrafts(RegisterCase):
    def test_drafts_import_as_ideas_with_demand_marked_as_assumption(self):
        """Verifies D-056 och D-058: utkasten är giltiga initiativ, bara idéer, och efterfrågan är ett antagande."""
        import_dir(self.register, "yorgo", ROOT / "config")
        lines = import_file(self.register, "yorgo", PRODUCTS / "initiatives.toml")
        self.assertEqual(len(lines), 3)
        for entry in self.register.all("initiative"):
            self.assertEqual(entry.status, "idea")
            self.assertTrue(entry.data["demand"]["source"].startswith("antagande"))
            self.assertIsNotNone(self.register.get("platform", entry.data["platform"]))
            self.assertIsNone(self.register.assessments.valid(entry.key, entry.data,
                                                              self.register.get("platform", entry.data["platform"]).data))

    def test_every_draft_has_the_required_parts_and_says_it_is_not_published(self):
        """Verifies PR 11 och §6: annonstext med AI-märkning, regel och checklista; inget är publicerat."""
        drafts = sorted(p for p in PRODUCTS.glob("*/README.md"))
        self.assertEqual(len(drafts), 3)
        for path in drafts:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.parent.name):
                for section in SECTIONS:
                    options = section if isinstance(section, tuple) else (section,)
                    self.assertTrue(any(o in text for o in options), f"{path.parent.name} saknar {options}")
                self.assertIn("UTKAST", text)
                self.assertIn("INTE REDO", text)
                self.assertRegex(text, r"(?i)AI")
                self.assertIn("**Fortsätt", text)
                self.assertIn("**Ändra", text)
                self.assertIn("**Sluta", text)
                self.assertIn("results import", text)
        self.assertIn("Ingenting är publicerat", (PRODUCTS / "README.md").read_text(encoding="utf-8"))
