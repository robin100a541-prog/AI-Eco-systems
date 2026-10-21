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
| `docs/conversations/` | Arkiv över alla Claude-sessioner |
| `research/QUESTIONS.md` | Öppna frågor som systemet ska utreda |

## Snabbstart
```bash
python3 scripts/check_env.py --founder DittNamn     # Windows: py scripts\check_env.py --founder DittNamn
python3 -m unittest discover -s tests -v
```
