# AI Enterprise System

Ett lokalt, hierarkiskt multiagentsystem som organiserar AI-agenter som ett företag med strikt budget-, risk- och behörighetskontroll. Grundare: Yorgo och Robin.

**Status:** Fas 0 (krav och förutsättningar). Ingen applikationskod ännu. Se `PROJECT_STATUS.md`.

## Dokument
| Fil | Innehåll |
|---|---|
| `CONSTITUTION.md` | Grundkonstitutionen (styrande) |
| `PROJECT_STATUS.md` | Var projektet står just nu — **börja här** |
| `REQUIREMENTS.md` | Alla krav med ID:n |
| `ARCHITECTURE.md` | Teknisk arkitektur, verktyg, licenser |
| `DECISIONS.md` | Beslut och öppna frågor |
| `ROADMAP.md` | Faser och uppgifter |
| `CHANGELOG.md` | Vad som ändrats |
| `docs/setup.md` | Kom igång på din dator |
| `docs/command-center/DATA.md` | Command Center: arkitektur, data och snapshotens schema |
| `docs/command-center/DEPLOY.md` | Command Center: driftsättning steg för steg |
| `docs/conversations/` | Arkiv över alla Claude-sessioner |
| `research/QUESTIONS.md` | Öppna frågor som systemet ska utreda |
| `docs/prompts/` | Färdiga instruktioner att klistra in i Claude Code |

## DEPLOYMENT
Command Center, systemets dashboard, publiceras från `command-center/` på Cloudflare Pages och skyddas av Cloudflare Access (D-085, D-086).
- **Första gången:** följ `docs/command-center/DEPLOY.md` steg för steg (konto, Pages-projekt, Access med två mejladresser, KV, tokens och variabler).
- **Därefter:** en merge till `main` publiceras automatiskt inom någon minut.
- **Kontroll:** `py scripts\check_deploy.py https://<projekt>.pages.dev` visar att sidan kräver inloggning.
- **Lokalt:** `dashboard.cmd` startar samma gränssnitt utan internet.

## Snabbstart
```bash
python3 scripts/check_env.py --founder DittNamn     # Windows: py scripts\check_env.py --founder DittNamn
python3 -m unittest discover -s tests -v
```
