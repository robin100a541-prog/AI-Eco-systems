# AI Eco Systems — Project Brain

Both collaborators' Claude Code sessions read this file. Keep it current; edit it via PR like any other code.

## Goal
Ett självstyrande AI-företagssamhälle (`ai-enterprise/`) där specialiserade AI-agenter arbetar som ett företag med hierarki, budgetar och revision, under grundarnas kontroll. Det byggs för Robin och Yorgo enligt `ai-enterprise/CONSTITUTION.md`, och allt körs i simulering (`SIM`) tills Fas 7.

## Team
| Person | GitHub | Owns |
|---|---|---|
| Robin | @robin100a541-prog | ai-enterprise: styrning (beslut, oenighet, eskalering), ledger, budgetmotor, reserv, Tax Engine, lärdomar och strategier |
| Yorgo | @yorgo-jarjous | ai-enterprise: agenter och behörigheter, orkestrering, samråd, stopp (stop-loss, nödstopp, skyddat läge), incidenter, prognoser och prestationsmätning |

## Tech stack
Python ≥ 3.11 med bara standardbiblioteket, SQLite (STRICT-tabeller och append-only-triggers) och `unittest`. CI är GitHub Actions på Python 3.11 och 3.12. Lokala modeller körs via Ollama, och molnmodeller via Groq och OpenRouter bakom `ProviderRouter`. Det finns inget hosting; allt körs lokalt. Se `ai-enterprise/ARCHITECTURE.md`.

## Folder structure
```
/            repo root (CLAUDE.md, README, TODO.md)
/.claude     shared Claude Code settings + commands
/docs        decisions, specs, notes
/src         application code (adjust once stack is chosen)
```

## Workflow rules (for humans and Claude)
1. Never commit directly to `main`. Branch as `<name>/<short-topic>` (e.g. `robin/login-page`).
2. One PR per feature. The other person reviews before merge.
3. Pull `main` before starting work; rebase/merge `main` into your branch before opening a PR.
4. Stay in your own area (see Team table) to avoid merge conflicts. Touching the other person's area → mention it in the PR.
5. Small commits with clear messages: `feat: …`, `fix: …`, `docs: …`, `chore: …`.
6. Track work in `TODO.md` (or GitHub Issues). Claim a task before starting it.

## Coding rules
- Never commit secrets, API keys or `.env` files. Use `.env.example` for shape only.
- Prefer simple, readable code over clever code.
- Add or update tests for behavior changes.
- Record non-obvious decisions in `docs/decisions/` (one short markdown file each).

## Don't touch
- `main` branch directly
- `.claude/settings.local.json` (personal, gitignored)
