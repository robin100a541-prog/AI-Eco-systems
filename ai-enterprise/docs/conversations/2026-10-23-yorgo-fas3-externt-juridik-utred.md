# Session 2026-10-23 — Yorgo — Fas 3g–3i

Deltagare: Yorgo, Claude (Opus 5.5) i Claude Code.

## 1. Yorgo

> Ja, ta SR-06 (externt innehåll är opålitlig data), SR-16 (juridisk konflikt går till Compliance) och FR-25 (Utred möjlighet) enligt samma arbetssätt.

## 1. Claude (sammanfattning)

- **Nummerfördelning i `TODO.md`** (PR #28): Robin får migration 9–11 och D-021–D-024, och Yorgo får 12–13 och D-025. Det gjordes efter krocken mellan PR #25 och migration 7.
- **3g, SR-06:** `security/external.py` och kopplingen i `AgentWorker`. Behörighet kan aldrig komma från extern text. Den avgörs bara av registret, mandaten och stoppen. `Ran 261 tests ... OK (skipped=2)`.
