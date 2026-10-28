# AI Eco Systems — Project Brain

Both collaborators' Claude Code sessions read this file. Keep it current; edit it via PR like any other code.

## Goal
Ett självstyrande AI-företagssamhälle (`ai-enterprise/`) där specialiserade AI-agenter arbetar som ett företag med hierarki, budgetar och revision, under grundarnas kontroll. Agenterna ska hitta, jämföra, simulera och förbereda affärsmöjligheter på flera plattformar, med så lite manuellt arbete och så nära noll kronor i nya kostnader som möjligt. Det byggs för Robin och Yorgo enligt `ai-enterprise/CONSTITUTION.md`, och allt körs i simulering (`SIM`) tills Fas 7. Riktiga pengar kräver bevisad lönsamhet (D-048), en grundares uttryckliga godkännande och oberoende granskning av säkerhetskritisk kod (D-055, föreslaget).

## Team
| Person | GitHub | Roll |
|---|---|---|
| Robin | @robin100a541-prog | Grundare |
| Yorgo | @yorgo-jarjous | Grundare |

Grundarna agerar som en (D-049): en grundares godkännande räcker, och alla uppgifter tillhör båda. Anspråk i `TODO.md` finns bara för att två Claude-sessioner inte ska bygga samma sak samtidigt. Nattboten och utvecklaragenten (D-050) följer `ai-enterprise/docs/BOT.md`.

## Tech stack
Python ≥ 3.11 med bara standardbiblioteket, SQLite (STRICT-tabeller och append-only-triggers) och `unittest`. CI är GitHub Actions på Python 3.11 och 3.12. Lokala modeller körs via Ollama, och molnmodeller via Groq och OpenRouter bakom `ProviderRouter`. Det finns inget hosting; allt körs lokalt. Se `ai-enterprise/ARCHITECTURE.md`.

## Folder structure
```
/                     repots rot: CLAUDE.md, README.md, TODO.md (anspråk och nummerfördelning)
/.github/workflows    CI (tester, protected-files, dev-agent)
/.claude              delade Claude Code-inställningar
/docs                 gemensamma anteckningar
/ai-enterprise        projektet
  CONSTITUTION.md     konstitutionen (skyddad, ändras aldrig utan grundarna)
  DECISIONS.md        beslutsloggen (skyddad; nya förslag läggs först i docs/proposals/)
  REQUIREMENTS.md, ROADMAP.md, PROJECT_STATUS.md, ARCHITECTURE.md, CHANGELOG.md
  config/             system, riskgränser (skyddad), behörigheter (skyddad), budgetar, skatt, scenarier
  src/aie/            koden: agents, authorization, budget, ledger, tax, risk, evaluation, simulation, llm, ...
  tests/unit, tests/acceptance, tests/fixtures
  docs/               setup, operations, prompts (arbetsordrar), proposals, conversations, bot-rapporter
```

## Workflow rules (for humans and Claude)
1. Never commit directly to `main`. Branch as `<name>/<short-topic>` (e.g. `robin/login-page`).
2. One PR per feature. Vanlig kod slås ihop av den som skrev den när CI är grön (D-016). Kod som rör ledger, budget, skatt, stopp eller behörigheter får etiketten `kräver-oberoende-granskning` och ska granskas av någon som inte skrev den (den andra grundaren eller en separat Claude-session) innan den används för riktiga pengar (D-055, föreslaget). Skyddade filer kräver etiketten `founder-approved`, som bara en grundare sätter (D-049).
3. Pull `main` before starting work; rebase/merge `main` into your branch before opening a PR.
4. Claim the task in `TODO.md` first, so that two sessions never work on the same files at the same time.
5. Small commits with clear messages: `feat: …`, `fix: …`, `docs: …`, `chore: …`.
6. Track work in `TODO.md` (or GitHub Issues). Claim a task before starting it.

## Coding rules
- Never commit secrets, API keys or `.env` files. Use `.env.example` for shape only.
- Prefer simple, readable code over clever code.
- Add or update tests for behavior changes.
- Record non-obvious decisions as proposals in `ai-enterprise/docs/proposals/`; an approved decision is written into `ai-enterprise/DECISIONS.md` (protected).

## Don't touch
- `main` branch directly
- `.claude/settings.local.json` (personal, gitignored)
