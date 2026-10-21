#!/usr/bin/env python3
"""Fas 0: verifiera att en GRATIS språkmodell faktiskt svarar från er dator.

Alla tre leverantörer använder samma OpenAI-kompatibla format, så samma kod
fungerar för alla. Endast standardbiblioteket används (D-002).

Exempel:
  # Groq (gratisplan, kräver gratis nyckel från console.groq.com)
  export GROQ_API_KEY=...            # Windows PowerShell:  $env:GROQ_API_KEY="..."
  python3 scripts/llm_smoke_test.py --provider groq

  # OpenRouter (modeller som slutar på :free)
  export OPENROUTER_API_KEY=...
  python3 scripts/llm_smoke_test.py --provider openrouter --model <modell-id>:free

  # Ollama (lokalt, ingen nyckel, inga gränser utöver er hårdvara)
  python3 scripts/llm_smoke_test.py --provider ollama --model <modell du hämtat>

Skriptet skriver aldrig ut nyckeln. Det skickar bara en ofarlig testfråga.
Avsluta med kod 0 om modellen svarade, annars 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_env: str | None  # None = ingen nyckel behövs
    default_model: str | None
    cost_note: str


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-20b",
        "Gratisplan med dagliga gränser. Kontrollera era gränser på console.groq.com/settings/limits.",
    ),
    "openrouter": Provider(
        "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", None,
        "Endast modeller med ':free' är gratis (20 anrop/min, 50/dag utan köpta krediter).",
    ),
    "ollama": Provider(
        "ollama", "http://localhost:11434/v1", None, None,
        "Körs lokalt. Ingen avgift, men kräver tillräckligt RAM/GPU.",
    ),
}

PROMPT = "Svara med exakt ett ord: vilken färg har en klar himmel en solig dag?"
QUOTA_HEADER_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after")


class SmokeError(RuntimeError):
    pass


def build_request(p: Provider, model: str, api_key: str | None, base_url: str | None = None) -> urllib.request.Request:
    if p.name == "openrouter" and not model.endswith(":free"):
        # Kostnadspolicy §42: vägra tyst betalning.
        raise SmokeError("OpenRouter-modellen måste sluta på ':free' — annars kan anropet kosta pengar.")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 200,
        "temperature": 0,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(f"{base_url or p.base_url}/chat/completions", data=body, headers=headers, method="POST")


def parse_response(raw: bytes) -> tuple[str, dict]:
    try:
        data = json.loads(raw)
        text = data["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise SmokeError(f"Oväntat svarsformat: {raw[:200]!r}") from exc
    return text.strip(), data.get("usage") or {}


def run(provider: str, model: str | None, environ=os.environ, base_url: str | None = None, timeout: float = 60) -> dict:
    p = PROVIDERS[provider]
    model = model or p.default_model
    if not model:
        raise SmokeError(f"Ange --model för {provider}.")
    api_key = None
    if p.key_env:
        api_key = environ.get(p.key_env)
        if not api_key:
            raise SmokeError(f"Miljövariabeln {p.key_env} är inte satt.")
    req = build_request(p, model, api_key, base_url)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, headers = resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        if api_key:
            detail = detail.replace(api_key, "***")
        raise SmokeError(f"HTTP {exc.code} från {provider}: {detail}") from None
    except urllib.error.URLError as exc:
        raise SmokeError(f"Kunde inte nå {provider}: {exc.reason}") from None
    text, usage = parse_response(raw)
    quota = {k: v for k, v in headers.items() if k.lower().startswith(QUOTA_HEADER_PREFIXES)}
    return {
        "provider": provider, "model": model, "answer": text,
        "latency_s": round(time.monotonic() - started, 2),
        "usage": usage, "quota_headers": quota, "cost_note": p.cost_note,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    ap.add_argument("--model")
    args = ap.parse_args(argv)
    try:
        result = run(args.provider, args.model)
    except SmokeError as exc:
        print(f"FEL: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nOK — modellen svarade. Klistra in detta i docs/environment.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
