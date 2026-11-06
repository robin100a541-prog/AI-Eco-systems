# Deployment status — 2026-11-06

**Real-money launch remains blocked.** Passing SIM checks is not production approval.

## What is on `main`

| Item | Status | Evidence |
|---|---|---|
| H1–H4, M1–M5 | Fixed | #126–#130 |
| Independent review (D-055) | Done | `docs/reviews/REVIEW-2026-10-30-ny-session.md` (#133) |
| N1 refused spend undid protected mode | Fixed | #134, `tests/unit/test_review_gates.py` |
| N2 stop-loss not checked before spend | Fixed | #134, same test (fails without the fix) |
| N3 pilot approval by text search | Fixed | #134, `test_n3_agent_decision_with_same_text_is_not_an_approval` |
| **H5 readiness without simulation evidence** | **Fixed** | #134, `registry/assessments.py: evidence_errors`, `test_h5_ready_without_simulation_runs_is_refused` |
| N4–N14 (medium/low) | Open | `docs/reviews/FIXES-2026-10-30.md` |
| Re-review of the #134 fixes (D-055) | Not done | needs a fresh Claude session |
| Daily report date | Fixed 2026-11-06 | file and heading use today's real date; the SIM business day is shown next to it |
| Off-device backup | Code ready, **not connected** | `python -m aie.memory.backup offsite` (see below) |

The daily SIM business day stays at 2027-01-01 between runs. That suggests the cached database is not
carried over between workflow runs. It is not investigated yet and does not affect real-money data.

## Off-device backup: what a founder must do (once)

Real-money data lives only in `data-pilot/data/prod.db` on the founder's computer. It is never in git.
The destination is a **private Google Drive folder**, synced by Google's own app; nothing is shared.

1. Install **Google Drive for desktop**: https://www.google.com/drive/download/ → Download → install →
   sign in with your Google account.
2. Open https://drive.google.com → **New** → **New folder** → name it `AI-Eco-backup` → **Create**.
   Do **not** click Share.
3. On your computer, open the Google Drive folder (Mac: Finder sidebar "Google Drive"; Windows: drive
   `G:`), go to **My Drive**, right-click `AI-Eco-backup` → **Offline access** → **Available offline**.
4. Copy that folder's path, for example `/Users/<you>/Library/CloudStorage/GoogleDrive-<email>/My Drive/AI-Eco-backup`
   (Mac) or `G:\My Drive\AI-Eco-backup` (Windows).
5. In `ai-enterprise/`, after each sales import, run:
   `PYTHONPATH=src python -m aie.memory.backup offsite --to "<the path from step 4>"`
   It writes a verified snapshot plus manifest, keeps the 30 newest and refuses any folder inside the repo.

## Founder input that code cannot supply

- Re-review of the #134 fixes by a fresh Claude session (D-055), and a decision on N4–N14.
- Platform account identity verification and accepting the selling platform's terms.
- Choosing a product: no idea has passed the 7a/Scout bar yet.
- Connecting the off-device backup folder (above).
- Explicit approval of the bounded pilot once the above are done.
