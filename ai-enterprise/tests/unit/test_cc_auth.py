"""Command Centers egna inloggning (D-094): `py -m aie command-center make-code|make-secret`."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from aie.dashboard import cc_auth

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "command-center" / "tests" / "fixtures" / "code-hash.json").read_text(encoding="utf-8"))


class TestCodeHash(unittest.TestCase):
    def test_hash_is_pbkdf2_sha256_with_210000_iterations_and_matches_the_functions(self):
        """Verifies FR-28, D-094: hashen är PBKDF2-SHA256 med 210 000 iterationer och slumpat salt, och är exakt
        den som Cloudflare-funktionerna räknar (samma testvektorer som command-center/tests/api.test.mjs)."""
        for name in ("yorgo", "robin"):
            line = VECTORS[name]["line"]
            founder, rest = line.split("=", 1)
            scheme, iterations, salt, digest = rest.split("$")
            self.assertEqual((founder, scheme, int(iterations)), (name, "pbkdf2_sha256", 210_000))
            self.assertEqual(cc_auth.hash_line(name, VECTORS[name]["code"], bytes.fromhex(salt)), line)
            self.assertEqual(cc_auth.derive(VECTORS[name]["code"], bytes.fromhex(salt)), digest)
            self.assertNotEqual(cc_auth.derive(VECTORS[name]["code"] + "x", bytes.fromhex(salt)), digest)
        self.assertGreaterEqual(cc_auth.ITERATIONS, 210_000)
        self.assertLessEqual(cc_auth.ITERATIONS / 3, cc_auth.MAX_PER_CALL)  # Cloudflares tak per anrop
        a, b = cc_auth.hash_line("yorgo", "a-long-enough-code"), cc_auth.hash_line("yorgo", "a-long-enough-code")
        self.assertNotEqual(a, b)  # nytt salt varje gång

    def test_short_codes_and_unknown_founders_are_refused(self):
        """Verifies FR-28, D-094: koden måste ha minst 12 tecken, och bara Yorgo och Robin kan få en."""
        with self.assertRaises(ValueError):
            cc_auth.hash_line("yorgo", "elevenchars")
        with self.assertRaises(ValueError):
            cc_auth.hash_line("mallory", "a-long-enough-code")
        self.assertEqual(cc_auth.MIN_LENGTH, 12)

    def test_make_code_prints_only_the_hash_line_never_the_code(self):
        """Verifies SR-10, D-094: make-code frågar två gånger, skriver ut hash-raden och aldrig koden; olika koder
        nekas. make-secret skriver ut ett slumpat värde på minst 32 tecken."""
        code = "my-private-code-123"
        out, err = io.StringIO(), io.StringIO()
        answers = iter([code, code])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cc_auth.make_code("Yorgo", read=lambda _: next(answers)), 0)
        printed = out.getvalue() + err.getvalue()
        self.assertNotIn(code, printed)
        line = printed.strip().splitlines()[-1]
        self.assertRegex(line, r"^yorgo=pbkdf2_sha256\$210000\$[0-9a-f]{32}\$[0-9a-f]{64}$")
        salt = bytes.fromhex(line.split("$")[2])
        self.assertEqual(cc_auth.hash_line("yorgo", code, salt), line)
        answers = iter([code, code + "x"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cc_auth.make_code("Yorgo", read=lambda _: next(answers)), 1)
        answers = iter(["short", "short"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cc_auth.make_code("Robin", read=lambda _: next(answers)), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cc_auth.make_secret(), 0)
        first = out.getvalue().strip().splitlines()[-1]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc_auth.make_secret()
        self.assertGreaterEqual(len(first), 32)
        self.assertNotEqual(first, out.getvalue().strip().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
