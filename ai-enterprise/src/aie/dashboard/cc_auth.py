"""`py -m aie command-center make-code|make-secret`: hemligheterna för Command Centers egna inloggning (D-094).

    py -m aie command-center make-code --founder Yorgo   -> raden som ska in i FOUNDER_CODE_HASHES
    py -m aie command-center make-secret                 -> ett slumpat SESSION_SECRET

Koden skrivs aldrig ut, sparas aldrig och lämnar aldrig datorn. Bara hashen skrivs ut.

Hashen är PBKDF2-SHA256 med 210 000 iterationer och 16 byte slumpat salt. Cloudflare tillåter högst 100 000
iterationer per anrop, så beräkningen görs i lika stora steg i kedja (3 x 70 000): utdata från ett steg är
lösenordet till nästa, med samma salt. `command-center/lib/session.js` räknar exakt likadant, och ett test
kontrollerar att båda ger samma hash.
"""
from __future__ import annotations

import getpass
import hashlib
import math
import secrets
import sys

ITERATIONS = 210_000
MAX_PER_CALL = 100_000
MIN_LENGTH = 12
FOUNDERS = ("yorgo", "robin")


def derive(code: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    rounds = math.ceil(iterations / MAX_PER_CALL)
    per, rest = divmod(iterations, rounds)
    if rest:
        raise ValueError("iterationerna måste gå jämnt upp i stegen")
    password = code.encode("utf-8")
    for _ in range(rounds):
        password = hashlib.pbkdf2_hmac("sha256", password, salt, per, dklen=32)
    return password.hex()


def hash_line(founder: str, code: str, salt: bytes | None = None) -> str:
    """Raden för en grundare: `namn=pbkdf2_sha256$210000$<salt>$<hash>`."""
    name = founder.strip().lower()
    if name not in FOUNDERS:
        raise ValueError(f"okänd grundare {founder!r}; välj en av {', '.join(FOUNDERS)}")
    if len(code) < MIN_LENGTH:
        raise ValueError(f"koden måste ha minst {MIN_LENGTH} tecken")
    salt = salt or secrets.token_bytes(16)
    return f"{name}=pbkdf2_sha256${ITERATIONS}${salt.hex()}${derive(code, salt)}"


def _read(prompt: str) -> str:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError, OSError):
            print("(den här terminalen kan inte dölja inmatningen; koden syns medan du skriver)", file=sys.stderr)
            return input(prompt)


def make_code(founder: str, read=_read) -> int:
    first = read(f"Ny åtkomstkod för {founder} (minst {MIN_LENGTH} tecken): ")
    if read("Skriv koden igen: ") != first:
        print("FEL: koderna är inte lika", file=sys.stderr)
        return 1
    try:
        line = hash_line(founder, first)
    except ValueError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    print("Lägg den här raden i hemligheten FOUNDER_CODE_HASHES (flera grundare skiljs med komma):")
    print(line)
    return 0


def make_secret() -> int:
    print("Lägg det här värdet i hemligheten SESSION_SECRET:")
    print(secrets.token_urlsafe(48))
    return 0
