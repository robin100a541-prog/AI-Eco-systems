# Deployment status — 2026-10-30

**Real-money launch remains blocked.** Passing SIM checks is not production approval.

## Technical work performed by Codex

| Item | Change / evidence |
|---|---|
| H1, H2, H3, M2 | #126: atomic sale imports, later refunds, economic dates and repeatable reconciliation |
| Backup and recovery rehearsal | #127: private SQLite snapshots, manifest, isolated restore and integrity checks |
| H4, M1 | #128: serialized spending/approval consumption, original risk/category and renewed authority checks |
| M3, M4 | #129: loopback-only internal model endpoints; atomic, idempotent tax-payment recording |
| M5 | #130: atomic attempt quotas, including failures and interrupted requests |
| Daily workflow smoke check | #131: isolated manual verify_only mode, no credentials/cache/PR/Pages |

These are implementation and test results, **not independent approval** of the changes.
Baseline regression suites passed locally and required 3.11/3.12 CI checks are recorded on each PR.
Migration 34 preserves old registration dates; migration 35 rejects unclassified legacy approvals;
migration 36 conservatively seeds the attempt counter from stored fetches. Back up before upgrading.

Actions run 41083637658 verified two independent daily CLI processes on the feature branch, with
persisted SIM days 1 and 2, two daily reports, a public SIM dashboard, and an intact audit chain.
Its cycle and pages jobs were skipped. This does not verify Groq quotas, production caches,
report-PR merging, GitHub Pages setup, off-device backups or real sales.

## Next engineering task (still open)

**H5: simulation evidence must authorize readiness.** The existing public assessment store still
accepts a caller-provided ready flag. No real-money pilot should proceed until it is replaced by
validation of completed runs and a new independent review. See
`proposals/2026-10-30-assessment-evidence-design.md` for a concrete implementation outline.

## Founder input that code cannot supply

- Actual identity verification and accepting the selling platform's account terms.
- Tax-authority confirmation for the real selling arrangement.
- Reading and approving a fact-checked final product.
- Choosing a private off-device backup destination; no destination has been connected.
- Explicit approval of the bounded pilot, after the technical blockers are resolved.

The code agent can handle implementation, tests and recovery rehearsals. The founder does not need
to write code or manually repair these defects. `FOUNDER-CHECKLIST.md` covers the eventual human steps;
it must not be read as permission to bypass H5 or independent review.
