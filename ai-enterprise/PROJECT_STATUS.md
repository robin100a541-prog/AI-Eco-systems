# PROJECT_STATUS

**Senast uppdaterad:** 2026-10-26 av Claude (Claude Code-session med Yorgo)
**Aktuell fas:** Fas 5. **Fas 4 är stängd:** 4a–4f är klara, och §52 är acceptanstestad. Fas 5a–5c är klara: incidentrapporter, prognoslogg och prestationsmätning. **Kvar i Fas 5: FR-17, FR-18 och SR-17 (Robin).** Fas 3 är klar: byggd, acceptanstestad (§51) och alla beslut är godkända av båda.
**Fasstatus:** Fas 1–4 och Fas 5a–5c är mergade till `main`. Acceptanstester finns för §49, §50 och §51. Fas 0-punkterna 0.8 och 0.10 är öppna.

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
| Acceptanstester Fas 1 (1.7): ett per kriterium i §49 och ROADMAP 1.7, med de riktiga kommandona i egna processer | `tests/acceptance/test_fas1.py`, 12 tester; hela sviten 151 OK på Python 3.11, 3.12 och 3.13 och i CI |
| LLM via Authorization Engine (Fas 2, Robin): `LLMGateway` kräver `llm.complete`; nekat anrop revideras och skickar inget; prompter med hemligheter avvisas | `tests/unit/test_llm_gateway.py`, 10 tester, bland annat läcktester mot extern transport, loggfil och audit-logg; 208 OK på Python 3.11, 3.12 och 3.13 |
| Beslutslogg (Fas 3, Robin): `src/aie/governance/decisions.py`, migration 9 `decisions` (append-only), alla åtta fält i §20 steg 7, kopplad till uppgiften; `decision.record` i mandatet för CEO, CFO, CRO och Research-chefen; över `HUMAN_APPROVAL_THRESHOLD` krävs grundarna (D-019) | `tests/unit/test_decisions.py`, 12 tester; 231 OK på Python 3.11, 3.12 och 3.13 |
| Oenighet (Fas 3, Robin): `src/aie/governance/disputes.py`, migration 10 (ståndpunkter och händelser append-only), konflikttyp mål/data/risk/metod, kompletterande analys, eskalering till CEO eller grundarna; varken röster eller grundare kan godta ett förslag över `MAX_SINGLE_TRANSACTION`, `MAX_DEPARTMENT_BUDGET`, `MAX_SINGLE_EXPERIMENT_LOSS` eller med riskklass critical | `tests/unit/test_disputes.py`, 16 tester, bland annat ROADMAP:s nyckeltest (CFO och CRO oense → eskaleras) |
| Eskalering (Fas 3, Robin): `src/aie/governance/escalation.py`, migration 12, grundarnas godkännandekö (1 eller 2 grundare enligt D-019, ett nej avslår, hårda gränser kan inte godkännas), `python -m aie approvals list/approve/reject`, `founders` i `system.toml` (D-021) | `tests/unit/test_escalation.py`, 16 tester; 314 OK på Python 3.11, 3.12 och 3.13 efter PR #31 (migration 11) |
| Tilldelning nedåt i befälskedjan (Fas 3k, Robin, i Yorgos `TaskBoard`): en agent tilldelar bara sina egna underställda, både ny och gammal ägare prövas, CEO styr inte kontrollfunktionerna (D-023) | `tests/unit/test_delegation.py`, 8 tester; 333 OK på Python 3.11, 3.12 och 3.13 (efter Fas 3j) |
| `manual`-provider (Fas 3j, Robin): `src/aie/llm/manual.py`, inkorg i `<data_dir>/manual/<miljö>/`, bara public-data, dagsgränser, `python -m aie manual list/show/answer` för grundarna (D-022) | `tests/unit/test_manual.py`, 11 tester; 325 OK på Python 3.11, 3.12 och 3.13 |
| Acceptanstester Fas 3 (Robin): ett eller flera per kriterium i §51 och båda nyckeltesten i ROADMAP Fas 3 | `tests/acceptance/test_fas3.py`, 12 tester; hela sviten 345 OK på Python 3.11, 3.12 och 3.13 |
| Ledger (Fas 4a, Robin): `src/aie/ledger/`, migration 13, §40:s tolv fält, append-only, idempotens och externt ID, korrigeringsposter, SIM skilt från verklig valuta, godkännande över gränsen, nettovinst från genomförda poster (preliminär när något saknas), Audits återberäkning (D-024) | `tests/unit/test_ledger.py`, 22 tester; 367 OK på Python 3.11, 3.12 och 3.13 |
| Budgetmotor (Fas 4b, Robin): `src/aie/budget/`, `config/budgets.toml` (D-026), kontroll före varje ekonomisk handling mot budget, maxåtagande, `MAX_SINGLE_TRANSACTION`, `MAX_COMMITTED_CAPITAL`, riskutrymme och `API_SPEND`; över tröskeln krävs båda grundarna | `tests/unit/test_budget.py`, 13 tester; 380 OK på Python 3.11, 3.12 och 3.13 |
| Skyddad reserv och kapitalbegrepp (Fas 4c, Robin): `src/aie/budget/capital.py`, §23:s sju begrepp från ledgern, budgetmotorn blockerar allt som skulle ta av `MINIMUM_RESERVE` (D-027) | `tests/unit/test_capital.py`, 10 tester; 390 OK på Python 3.11, 3.12 och 3.13 |
| Uppdelningsdetektering (Fas 4d, Robin): budgetmotorn flaggar små utgifter i samma initiativ inom sju dagar som tillsammans passerar tröskeln eller `MAX_SINGLE_TRANSACTION`; flaggade kräver båda grundarna (D-028) | `tests/unit/test_split.py`, 5 tester; 395 OK på Python 3.11, 3.12 och 3.13 |
| CI på GitHub Actions: testerna körs på Python 3.11 och 3.12 vid varje PR och push till `main` | `.github/workflows/ai-enterprise-tests.yml`; checkarna syns på varje PR |
| Fas 2, agentramverket (Yorgo): livscykel och agentregister i databasen (migration 4), `config/permissions.toml` och Authorization Engine med default deny (D-017), uppgifter (migration 5), rapportformat i §7:s tio kategorier, ProviderRouter med kvoter och dataklassning (migration 6, D-018), `AgentWorker` (uppgift → modell → rapport → audit) | PR #11, #14, #16, #17, #18 och Fas 2-acceptansen. `tests/acceptance/test_fas2.py` har 12 tester, minst ett per kriterium i §50. Hela sviten ger 219 OK (2 SIGINT-tester överhoppade) på Windows 11, Python 3.12.0, och i CI |
| Fas 3 (Yorgo): hierarki och styrverktyg (PR #24, D-020), kontrollfunktionernas stopp (PR #26), samråd (PR #27), externt innehåll som opålitlig data (PR #30), juridisk konflikt till Compliance (PR #31), "Utred möjlighet" (PR #32, D-025) | `test_hierarchy.py`, `test_stops.py`, `test_consultation.py`, `test_external.py`, `test_legal.py` och `test_opportunities.py`; 406 OK efter PR #32 |
| Stop-loss (Fas 4e-1, Yorgo): `src/aie/risk/stoploss.py`, migration 15. Fyra gränser mäts från ledgern, nya åtaganden blockeras via `BudgetEngine(gates=)`, förpliktelser listas men avbryts aldrig, återupptagande kräver plan och två grundare (D-029) | `tests/unit/test_stoploss.py`, 12 tester (PR #46) |
| Nödstopp (Fas 4e-2, Yorgo): `src/aie/risk/killswitch.py`, migration 16, `python -m aie kill`. Inga utgifter, bara läs-, rapport-, verifierings- och stoppverktyg, inget raderas. Återstart enligt `docs/operations.md`: två grundare och intakt revisionslogg (D-030) | `tests/unit/test_killswitch.py`, 10 tester, bland annat CLI:t i en egen process (PR #47) |
| Skyddat driftläge (Fas 4e-3, Yorgo): `src/aie/risk/protected.py`, migration 17. Sju villkor i §59, automatiskt inträde före varje utgift, utgifter och externa verktyg blockeras, bruten bokföring aktiverar dessutom nödstoppet, en grundare lämnar läget när skälen är borta (D-031) | `tests/unit/test_protected_mode.py`, 15 tester. Hela sviten ger 443 OK på Windows 11, Python 3.12.0 |
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

## Ändrat 2026-10-23 (Fas 1.7 — Fas 1 klar)
- Acceptanstester för varje kriterium i §49 (`tests/acceptance/`). Version 0.3.0.
- Hela testsviten skriver nu bara i temporära mappar.

## Ändrat 2026-10-23 (Fas 2 — Yorgo)
- **Arbetssätt:** Yorgos Claude tar nästa lediga uppgift utan att fråga. Ordningen är anspråk i `TODO.md`, bygg, testa, PR och merge vid grön CI (D-016).
- **Rättat i Fas 1-acceptanstesterna:** `with sqlite3.connect()` stänger inte filen, så på Windows kunde den temporära mappen inte raderas.
- **Rättat i `AuthorizationEngine`:** den nekar nu i stället för att krascha när registret inte kan läsas (§59).
- **Modellsvar:** blir alltid en **obekräftad hypotes** i rapporten (§29).
- **Tester:** inga nätverksanrop.
- **Version:** 0.4.0.

## Ändrat 2026-10-26 (Yorgo: godkännanden och Fas 4e)
- **Godkännanden:** Yorgo godkände D-020–D-028 (PR #44). D-020–D-024 och D-026 är nu godkända av båda. D-025, D-027 och D-028 väntar på Robin.
- **Fas 4e** byggd som tre PR:er:
  - stop-loss (PR #46)
  - nödstopp (PR #47)
  - skyddat driftläge
  Det gav migration 15–17 och D-029–D-031 (föreslagna). Tax Engine lämnas åt Robin, som tar migration 18 och D-032 och uppåt.
- **Spärrar:** `BudgetEngine` och `AuthorizationEngine` har den nya valfria parametern `gates=`. Där kopplas stop-loss, nödstopp och skyddat driftläge in. En spärr som inte kan avgöra ger nej (§59).
- **`docs/operations.md`:** den dokumenterade processen för nödstopp, stop-loss och återstart.

## Ändrat 2026-10-26 (Yorgo: Fas 5a–5c)
- **Godkännanden:** Yorgo godkände D-029–D-031 (PR #49). De väntar på Robin.
- **Nummer:** Tax Engine var inte påbörjad, så Fas 5a–5c tog migration 18–20 i stället för 20–22. Robin får 21–22. Det står i TODO.md.
- **5a incidentrapporter** (PR #51): `evaluation/incidents.py`, migration 18 och D-035.
  - Alla 16 fälten i §28 finns, och fälten ändras bara genom rättelseposter.
  - Stop-loss, nödstopp och skyddat driftläge skapar automatiskt en incident när de kopplas med `incidents=`. `sync()` hittar stopp som skett utan koppling.
- **5b prognoslogg** (PR #52): `evaluation/forecasts.py`, migration 19 och D-036.
  - Utfall för ledgermått hämtas automatiskt, men aldrig från ett preliminärt resultat.
  - En revidering är en ny prognos.
- **5c prestationsmätning** (PR #53): `evaluation/performance.py`, migration 20 och D-037.
  - Varje roll har en profil, och det finns ingen totalpoäng.
  - Den som rapporterar fel krediteras, och bara verifierade incidenter räknas mot de involverade.
- **Fas 5-acceptans (§53):** två av fem kriterier är uppfyllda. De tre andra hör till Robins FR-17 och FR-18.

## Ändrat 2026-10-26 (godkännanden)
- Yorgo och Robin godkände D-035–D-037 gemensamt. Robin godkände också D-025, D-027, D-028 och D-029–D-031. Därmed är D-020–D-031 och D-035–D-037 godkända av båda. Inga Fas 3–5-beslut väntar.

## Ändrat 2026-10-26 (Yorgo tar Robins uppgifter, endast idag)
- **Överlämning:** Robin har lämnat över sina uppgifter till Yorgo för 2026-10-26 (godkänt av Robin, endast idag). Från 2026-10-27 gäller den vanliga fördelningen igen.
- **Fas 4f Tax Engine:** `src/aie/tax/`, `config/tax.toml`, migration 21–22 och D-032–D-034.
  - Skattespår per intäkt (ER-18).
  - Försiktig skattereserv som åtagande, kopplad via `BudgetEngine(tax=)` (ER-19).
  - Momsgränsen med varning och blockering (ER-20).
  - Deklarationsunderlag per grundare (ER-21).
  - Satserna är simulerade, och spåren bekräftas med Skatteverket före Fas 7 (Q-05).
- **Fas 4 stängd:** `tests/acceptance/test_fas4.py` täcker de fem kriterierna i §52 och ROADMAP:s nyckeltester.

## Vad som INTE är gjort / inte verifierat
- Spärrarna kopplas inte in automatiskt i `python -m aie start`. Den som bygger en `AuthorizationEngine` eller `BudgetEngine` måste skicka med `gates=`. `python -m aie kill` fungerar fristående. Att koppla in alla spärrar i körningen är kvar till Fas 6, när systemet kör agenter i en arbetscykel.
- `IncidentLog`, `ForecastLog` och `PerformanceReview` kopplas inte in i `python -m aie start`, precis som spärrarna. Det görs i Fas 6. Kvalitet, kostnadseffektivitet, samarbetsförmåga och dokumentation (§31) mäts inte än och listas som omätta.
- Hela sviten, inklusive start och stopp med riktiga processer och `pid_alive`, är körd på Windows (473 OK, 2026-10-26). Bara de två SIGINT-testerna hoppas över, eftersom Windows inte skickar SIGINT till en annan process.
- Routern är bara testad med falsk transport. Inget riktigt anrop till Groq eller OpenRouter är gjort (0.10). Ollama är installerat men körde inte på Yorgos dator.
- När konfigurationen är ogiltig loggas felen i `logs/` i arbetsmappen, inte i den `log_dir` som står i `system.toml`.
- Groq-testet (0.10) är inte gjort. D-005–D-012 är inte beslutade (0.8); Q-01 är besvarad av D-019.
- Värdena i `config/risk_limits.toml` är simulerade (Q-04).
- `python -m aie` fungerar bara när `PYTHONPATH=src` är satt (se `docs/setup.md`).

## Nästa åtgärder
| # | Vad | Vem |
|---|---|---|
| 1 | Godkänna D-032–D-034 (Tax Engine) | Båda |
| 2 | Fas 5: lärdomsregister (FR-17), versionerade strategier (FR-18) och SR-17, med nästa lediga migration och D-038 och uppåt | Robin |
| 3 | Godkänna D-005–D-012 (0.8) | Båda, på plats |

## Blockerare
Inga.
