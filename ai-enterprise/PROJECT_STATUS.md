# PROJECT_STATUS

**Senast uppdaterad:** 2026-10-23 av Claude (Claude Code-session med Robin)
**Aktuell fas:** Fas 1 — Grundsystem
**Fasstatus:** 1.1–1.5 mergade till `main` (PR #1, #4, #5, #8, #9) och CI (PR #7) · 1.6 (init/start/stop/status) på grenen `robin/fas1-6-start-stop` · 1.7 återstår · Fas 0-punkterna 0.8 och 0.10 är öppna

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
| Loggning (1.3): `src/aie/monitoring/`, JSON-rader i `<log_dir>/aie.log` och text i konsolen, maskerade hemligheter, rotation vid 5 MB med 3 gamla filer, `log_level` i `system.toml` | `python3 -m unittest discover -s tests -v` → **68 OK** (49 gamla + 19 nya), körd 2026-10-23 i Robins Claude Code-molnmiljö, Linux, Python 3.13.17 |
| Lagring (1.4, Yorgo): `src/aie/memory/`, `<data_dir>/<miljö>.db`, ordnade migrationer i egna transaktioner, tabellerna `metadata` och `schema_migrations` | `tests/unit/test_storage.py`, 14 tester; 82 OK på Yorgos dator (Windows 11, Python 3.12.0) och i CI (3.11, 3.12) |
| Lagring (1.4b): `open_database(config.system)` använder `data_dir` och miljön från konfigurationen; fel loggas som ERROR och återrullade transaktioner som WARNING (`aie.memory`) | `tests/unit/test_storage_config.py`, 7 tester; 89 OK på Python 3.11, 3.12 och 3.13 |
| Revisionslogg (1.5, Yorgo): `src/aie/audit/`, hashkedja, triggrar vägrar UPDATE/DELETE, `verify()` med `head_hash` | `tests/unit/test_audit.py`, 15 tester (PR #9) |
| Start/stopp (1.6): `python -m aie init/start/stop/status`, driftläget i tabellen `runtime_state` (migration 3), ren nedstängning vid `stop`, Ctrl+C och SIGTERM, vägrar start vid manipulerad revisionslogg eller om systemet redan kör, upptäcker en körning som dog | `tests/unit/test_runtime.py`, 13 tester (bland annat riktiga processer), plus 1 samtidighetstest i `test_storage_config.py`; 118 OK på Python 3.11, 3.12 och 3.13; körda 40 gånger i rad utan fel |
| CI på GitHub Actions: testerna körs på Python 3.11 och 3.12 vid varje PR och push till `main` | `.github/workflows/ai-enterprise-tests.yml`; checkarna syns på varje PR |
| Inga tredjepartsimporter i `src/` | Sökning efter `^import\|^from` i `src/`: bara standardbiblioteket och relativa importer (kontrollerad igen 2026-10-23) |

## Ändrat 2026-10-21 (Fas 1-session med Yorgo)
- 1.1 och 1.2 byggda på grenen `fas1-grund`. Konfigurationen vägrar starta vid fel och samlar alla fel i ett meddelande.
- D-013 föreslaget: konfigurationens format och valideringsregler. Bland annat är `MAX_TOTAL_DRAWDOWN`, `REINVESTMENT_POLICY` och `API_REINVEST_SHARE` procentsatser.
- `docs/setup.md`: hur paketet körs utan installation (`PYTHONPATH=src`), och att Windows behöver `py -3 scripts\...` på grund av skriptens shebang.

## Ändrat 2026-10-23 (Fas 1.3-session med Robin)
- Repot finns på GitHub (`robin100a541-prog/AI-Eco-systems`, publikt), med projektet i `ai-enterprise/`. PR #1 (Fas 0 + 1.1–1.2) är mergad.
- 1.3 byggd på grenen `robin/fas1-3-loggning`: loggning till fil och konsol, maskering av hemligheter, automatiskt skapad `log_dir`, tydligt fel och kod 1 när den inte kan skapas. `check-config` loggar sitt resultat och sina fel.
- Ny valfri nyckel `log_level` i `config/system.toml` (standard INFO), föreslagen som D-015. Loggfilen roteras vid 5 MB och tre gamla filer sparas.
- D-001–D-004 och D-013–D-016 är godkända av båda grundarna. D-016: under byggfaserna mergar författaren sin PR när alla tester är gröna, utan granskning.
- PR #3 (mergad): Robins miljörapport från Claude Code i molnet, Robins godkännanden av D-001–D-004 och D-013, och förslaget D-014 (repot är publikt).

## Ändrat 2026-10-23 (Fas 1.4 och 1.4b)
- D-016 i kraft: författaren mergar sin PR när testerna är gröna. CI (PR #7) kör testerna på Python 3.11 och 3.12.
- 1.4 (Yorgo, PR #5): SQLite-lagret. Rättade även ett Windows-fel i loggningens felmeddelande.
- 1.4b (Robin): databasen öppnas från konfigurationen och lagringsfel loggas. Loggern `aie` har en `NullHandler` när loggningen inte är igång, så inget skrivs till stderr av misstag.

## Ändrat 2026-10-23 (Fas 1.5 och 1.6)
- 1.5 byggdes samtidigt av Yorgo (PR #9) och Robin (PR #10). Robin valde Yorgos version; PR #10 stängdes.
- 1.6: kommandona `init`, `start`, `stop`, `status`. `stop` fungerar via databasen (ingen signal), så det fungerar likadant på Windows.
- Två samtidighetsfel i lagret rättade: två processer som öppnade en ny databas samtidigt kunde båda försöka köra migration 1, och `PRAGMA journal_mode = WAL` gav "database is locked" utan att vänta. Återskapade med 6 samtidiga processer (30 av 30 omgångar fel före, 0 av 30 efter).

## Vad som INTE är gjort / inte verifierat
- `pid_alive` på Windows använder Win32-API:t (OpenProcess) och är bara testad i CI på Linux. Yorgo bör köra `py -m unittest discover -s tests -v` på Windows.
- När konfigurationen är ogiltig loggas felen i `logs/` i arbetsmappen, inte i den `log_dir` som står i `system.toml`.
- De gamla CLI-testerna körs med repots rot som arbetsmapp och skapar därför `ai-enterprise/logs/aie.log`. Mappen är gitignorerad.
- Groq-testet (0.10) är inte gjort. D-005–D-012 och Q-01 är inte beslutade (0.8).
- Värdena i `config/risk_limits.toml` är simulerade (Q-04).
- `python -m aie` fungerar bara när `PYTHONPATH=src` är satt (se `docs/setup.md`).

## Nästa åtgärder
| # | Vad | Vem |
|---|---|---|
| 1 | Godkänna D-005–D-012 och besvara Q-01 (0.8) | Båda, på plats |
| 2 | Fas 1.5: hashkedjad audit-logg | Robin (Claude) |
| 3 | Fas 1.7: acceptanstester för Fas 1 (konstitutionen §49) | Robin (Claude) |

## Blockerare
Inga.
