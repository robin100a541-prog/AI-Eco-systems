# AI Eco Systems — Project Brain

Both collaborators' Claude Code sessions read this file. Keep it current; edit it via PR like any other code.

## Goal
<!-- One or two sentences: what are we building and for whom? -->
TBD — fill in the project goal.

## Team
| Person | GitHub | Owns |
|---|---|---|
| Robin | @robin100a541-prog | TBD |
| Friend | @TBD | TBD |

## Tech stack
TBD — languages, frameworks, hosting, key services.

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
