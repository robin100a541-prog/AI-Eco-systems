"""Publicering från LISTA.md (testläget, LANSERING-Q4.md). Nätverket är mockat."""
import unittest

from aie.pod import lista
from aie.pod.printify import PrintifyClient

from .pod_helpers import FakeTransport

IDS = [f"{n:024x}" for n in range(1, 26)]
TEXT = "\n".join(["| Produkt | Bild |", "|---|---|"] + [f"| design-{n} `{pid}` | bild |" for n, pid in enumerate(IDS)])


def publisher():
    fake = FakeTransport({("POST", f"/v1/shops/5/products/{pid}/publish.json"): [(200, {}, None)] for pid in IDS})
    client = PrintifyClient("tok", transport=fake, min_interval=0)
    return fake, lambda pid: client._http.post(f"/v1/shops/5/products/{pid}/publish.json", {})


class TestPublish(unittest.TestCase):
    def test_publishes_nothing_without_godkand(self):
        """Utan raden GODKÄND publiceras inget, och inget anrop görs."""
        fake, publish = publisher()
        done, errors = lista.publish(TEXT + "\n\nGodkänn genom att skriva GODKÄND – namn\n", publish)
        self.assertEqual((done, fake.calls), ([], []))
        self.assertIn("GODKÄND", errors[0])

    def test_publishes_at_most_20(self):
        """Högst 20 publiceras, överstrukna rader hoppas över, och resten anges som fel."""
        fake, publish = publisher()
        text = TEXT.replace(f"| design-0 `{IDS[0]}` | bild |", f"~~| design-0 `{IDS[0]}` | bild |~~") + "\nGODKÄND – Yorgo\n"
        done, errors = lista.publish(text, publish)
        self.assertEqual(done, IDS[1:21])
        self.assertEqual(len(fake.calls), 20)
        self.assertEqual(len(errors), 4)
        self.assertNotIn(IDS[0], done)


class TestIdempotentPublish(unittest.TestCase):
    def test_already_published_are_skipped_and_do_not_use_up_the_limit(self):
        """Verifies D-070: redan publicerade produkter hoppas över utan anrop och räknas inte mot gränsen."""
        fake, publish = publisher()
        text = TEXT + "\nGodkänn\n\nGODKÄND – Yorgo\n"
        done, errors = lista.publish(text, publish, limit=20, skip=frozenset(IDS[:20]))
        self.assertEqual(done, IDS[20:25])
        self.assertEqual(errors, [])
        self.assertEqual(len(fake.calls), 5)
        self.assertFalse(any(IDS[0] in c["path"] for c in fake.calls))
