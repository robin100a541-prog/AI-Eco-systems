# PROJECT_STATUS

**Senast uppdaterad:** 2026-10-21 av Claude (Claude Code-session med Yorgo)
**Aktuell fas:** Fas 1 — Grundsystem
**Fasstatus:** 1.1 och 1.2 klara på grenen `fas1-grund`, väntar på granskning · Fas 0-punkterna 0.6–0.8 och 0.10 är fortfarande öppna

## Läs detta först (för den som öppnar en ny Claude-konversation)
1. Ge Claude hela repot eller åtminstone: CONSTITUTION.md, PROJECT_STATUS.md, DECISIONS.md, ARCHITECTURE.md, REQUIREMENTS.md.
2. Skriv: *"Fortsätt projektet enligt PROJECT_STATUS.md."*
3. Claude har **ingen** kännedom om den andra grundarens konversationer. Allt som gäller står i filerna.

## Vad som finns (verifierat)
| Sak | Bevis |
|---|---|
| Kravlista FR/SR/ER/DR, 80 krav | REQUIREMENTS.md |
| Arkitekturförslag + verktygsregister med licenser, gratis modeller och skattemodul | ARCHITECTURE.md |
| Beslut D-001…D-013 (föreslagna, D-005 ersatt av D-008), 8 öppna frågor; kanalregister och forskningskö | DECISIONS.md, docs/channels.md, research/QUESTIONS.md |
| `scripts/check_env.py` körd på Yorgos dator: **REDO för Fas 1** | docs/environment.md (Windows 11, Python 3.12.0, 2026-10-21) |
| Paketet `aie` (1.1): `pyproject.toml`, `src/aie/`, `python -m aie check-config` | Kod 0 med standardkonfigurationen; kod 1 med en medvetet trasig konfiguration, där alla 7 fel listades (körd 2026-10-21 på Yorgos dator) |
| Konfiguration (1.2): `config/system.toml`, `config/risk_limits.toml`, laddare med frysta dataklasser | `py -m unittest discover -s tests -v` → **49 OK** (18 gamla + 31 nya), körd 2026-10-21 på Yorgos dator, Windows 11, Python 3.12.0 |
| Inga tredjepartsimporter i `src/` | Sökning efter `^import\|^from` i `src/`: bara standardbiblioteket och relativa importer |

## Ändrat 2026-10-21 (Fas 1-session med Yorgo)
- 1.1 och 1.2 byggda på grenen `fas1-grund`. Konfigurationen vägrar starta vid fel och samlar alla fel i ett meddelande.
- D-013 föreslaget: konfigurationens format och valideringsregler. Bland annat är `MAX_TOTAL_DRAWDOWN`, `REINVESTMENT_POLICY` och `API_REINVEST_SHARE` procentsatser.
- `docs/setup.md`: hur paketet körs utan installation (`PYTHONPATH=src`), och att Windows behöver `py -3 scripts\...` på grund av skriptens shebang.

## Vad som INTE är gjort / inte verifierat
- **GitHub är inte kopplat.** Repot har ingen remote, så grenen `fas1-grund` är bara committad lokalt. Ingen pull request finns.
- Ingen har granskat `fas1-grund`.
- Testerna är bara körda på Windows (Yorgo). macOS/Linux och Robins dator är inte provade.
- Robins `check_env.py` (0.6) och Groq-testet (0.10) är inte gjorda. Inga beslut är godkända (0.8).
- Värdena i `config/risk_limits.toml` är simulerade (Q-04).
- `python -m aie` fungerar bara när `PYTHONPATH=src` är satt (se `docs/setup.md`).

## Nästa åtgärder
| # | Vad | Vem |
|---|---|---|
| 1 | Koppla repot till GitHub (0.7), pusha `main` och `fas1-grund`, öppna PR för `fas1-grund` | En grundare |
| 2 | Granska PR:en för `fas1-grund`, särskilt D-013 | Robin (eller Yorgo) |
| 3 | Kör `check_env.py` på Robins dator (0.6) | Robin |
| 4 | Fas 1.3: strukturerad loggning (JSON-rader till `logs/`) | Claude + den som har tid, efter att 1.1–1.2 är granskade |

## Blockerare
Inga tekniska. Delning mellan grundarna är blockerad tills repot finns på GitHub (punkt 1).
