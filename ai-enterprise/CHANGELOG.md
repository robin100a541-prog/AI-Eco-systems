# CHANGELOG

## [Unreleased] — 2026-10-23 — Fas 2 avslutad: D-018 och D-019
### Ändrat
- DECISIONS.md: D-018 (ProviderRouter) godkänd av båda grundarna. Bara fälten *Status* och *Godkänd av* ändrades.
### Tillagt
- D-019, grundarnas beslutsrätt: en grundare räcker upp till `HUMAN_APPROVAL_THRESHOLD`; över den krävs båda. Ändringar i konstitutionen, riskgränserna och behörigheterna kräver alltid båda. Q-01 är besvarad.

## [0.4.0] — 2026-10-23 — Fas 2 klar
### Tillagt
- `src/aie/orchestration/worker.py`: `AgentWorker.work_on(task_id)` kör hela kedjan. Ägaren startar uppgiften, och `report.write` kontrolleras. Modellen nås via `LLMGateway` (PR #19, kräver `llm.complete`) och ProviderRouter, där en uppgift räknas som `internal` om inget annat anges och därför bara går till lokala leverantörer. Svaret blir en rapport, rapporten sparas i audit-loggen och uppgiften avslutas med `audit:<seq>` som underlag. Modellsvaret är alltid en obekräftad hypotes (§29).
- Utan tillgänglig modell blockeras uppgiften med skälet. Den köas och kostar inget.
- `tests/acceptance/test_fas2.py`: 12 acceptanstester, minst ett per kriterium i §50, plus DR-12, DR-13 och SR-10 från början till slut. Hela sviten ger 219 OK på Windows 11, Python 3.12.0 (2 SIGINT-tester överhoppade).
### Ändrat
- Version 0.3.0 → 0.4.0. Fas 2-posterna (Unreleased) nedan ingår i den här versionen.

## [Unreleased] — 2026-10-23 — Fas 2: ProviderRouter bara via Authorization Engine
### Tillagt
- `src/aie/llm/gateway.py`: `LLMGateway` är det enda sättet för en agent att nå `ProviderRouter` (SR-01, SR-02, §35–36). Varje anrop kräver verktyget `llm.complete` i Authorization Engine. Ett nej revideras som `tool.denied`, och inget skickas.
- En prompt som innehåller en hemlighet (`api_key=...` eller värdet av en hemlig miljövariabel) avvisas med `SecretInPrompt`, oavsett dataklass. Avvisningen revideras som `llm.blocked_secret` utan prompten (SR-10).
- `config/permissions.toml`: verktyget `llm.complete` i katalogen och i mandatet för MVP:ns sex roller (D-008: agenterna resonerar med gratismodeller).
- `tests/unit/test_llm_gateway.py`: 10 tester. Läcktesterna lägger en unik markör i prompten och kontrollerar det som skickas externt, loggfilen och audit-loggen. Totalt 208.

## [Unreleased] — 2026-10-23 — Fas 2: ProviderRouter, kvoter och dataklassning
### Tillagt
- `src/aie/llm/`: `RuleProvider` och `OpenAICompatibleProvider` (groq, openrouter `:free`, ollama) med utbytbar transport, så att testerna aldrig går ut på nätet. Nyckeln läses från miljön och syns aldrig i fel, `repr` eller loggar (SR-10).
- `ProviderRouter`: väljer första leverantör som får ta emot datan (DR-13) och har kvot kvar (DR-12). Varje leverantör provas en gång. När ingen är kvar kastas `NoProviderAvailable` och arbetet köas, aldrig betalning (DR-01). Varje anrop loggas utan prompt.
- Migration 6 `provider_usage`: anrop och tokens per leverantör och UTC-dygn. Anropet räknas innan det skickas.
- `config/providers.toml` och `load_providers`: betalda typer avvisas (D-009), saknade gränser är fel (ER-02) och nycklar i filen avvisas.
- D-018 (föreslaget): routerns regler.
- `tests/unit/test_llm_router.py`: 16 tester med falsk transport.

## [Unreleased] — 2026-10-23 — Fas 2: rapportformat (FR-08)
### Tillagt
- `src/aie/reporting/`: `Report` med påståenden (`Claim`) i exakt en av de tio kategorierna i §7, från hypotes till realiserad nettovinst. Rapporten valideras när den skapas och alla fel listas samtidigt.
- Från och med `done` krävs underlag (`ledger:`, `task:`, `audit:`, `file:` eller `url:`). Bokförda och realiserade siffror måste peka på ledgern och ha ett belopp (ER-09, ER-11).
- Belopp är heltal plus valuta och får bara anges för prognos, bokfört och realiserat. Bara nettoresultatet får vara negativt, och en rapport har bara en valuta (ER-15).
- `to_dict` och `from_dict` ger JSON, så att rapporter kan läggas i audit-loggen.
- `tests/unit/test_reporting.py`: 13 tester.

## [Unreleased] — 2026-10-23 — D-017 och D-014 godkända
### Ändrat
- DECISIONS.md: D-017 (behörighetsmodellen) godkänd av båda grundarna. I D-014 är raden *Väntar på* uppdaterad till godkänd av båda. Ingen annan beslutstext ändrad.

## [Unreleased] — 2026-10-23 — Fas 2: uppgifter (FR-07)
### Tillagt
- Migration 5: `tasks` och `task_events`. Databasen vägrar radera uppgifter, ändra avslutade uppgifter och ta bort ägaren från en tilldelad uppgift. Historiken är append-only.
- `src/aie/orchestration/`: `TaskBoard` med `create`, `assign`, `start`, `block`, `complete` och `cancel`. Status går `open → assigned → in_progress → done`, med `blocked` och `cancelled` vid sidan av.
- Behörigheter kontrolleras av kod: `task.create` och `task.assign` via Authorization Engine (nekat försök loggas). Bara ägaren arbetar på uppgiften, ingen agent kan tilldela sig själv och grundarna får göra allt.
- `complete` kräver en beskrivning av vad som gjordes (§7), och `block` och `cancel` kräver en motivering.
- `tests/unit/test_tasks.py`: 13 tester. Totalt 169 gröna på Windows 11, Python 3.12.0 (två SIGINT-tester hoppas över).

## [Unreleased] — 2026-10-23 — Fas 2: agentregistret i databasen
### Tillagt
- Migration 4: tabellerna `agents` och `agent_state_changes`. Databasen vägrar radera agenter och ändra roll eller chef (bara status får ändras). Historiken är append-only och statuskolumnen godtar bara de sju tillstånden (FR-05, FR-06, SR-14).
- `AgentRegistry(permissions, db)` sparar i databasen och överlever omstart. Statusändring och historikrad skrivs i samma transaktion. Ny metod `agents()`.
- 5 nya tester. Totalt 156 gröna på Windows 11, Python 3.12.0, inklusive Fas 1.7. Två SIGINT-tester hoppas över på Windows.
### Rättat
- `AuthorizationEngine.check` kraschade om registret inte gick att läsa. Nu blir svaret nej, i linje med §59.
- `tests/acceptance/test_fas1.py`: `with sqlite3.connect()` stänger inte anslutningen. På Windows låste den databasfilen, så två acceptanstester föll när den temporära mappen skulle städas. Ny hjälpfunktion `open_sqlite` stänger alltid.
### Ändrat
- `AgentRegistry` kräver nu en `Database`. Registret i minnet från PR #11 är borttaget.

## [0.3.0] — 2026-10-23 — Fas 1 klar
### Tillagt
- `tests/acceptance/test_fas1.py`: 12 acceptanstester, ett eller flera per kriterium i konstitutionen §49 och ROADMAP 1.7. De kör `python -m aie ...` i egna processer i en tom mapp. Totalt 151 tester.
### Ändrat
- CLI-testerna i `test_config.py` körs i testets temporära mapp, så att hela testsviten aldrig skriver i repot.
- Version 0.2.0 → 0.3.0. Fas 1.4–1.7 (Unreleased-posterna nedan) ingår i den här versionen.

## [Unreleased] — 2026-10-23 — Fas 1.6: start, stopp och status
### Tillagt
- `python -m aie init | start | stop | status` (FR-01). Kod 0 = lyckades, kod 1 = fel som är utskrivet och loggat.
- `src/aie/runtime.py`: start i ordningen konfiguration → loggning → databas → kontroll av revisionsloggen → driftläge. Ren nedstängning vid `aie stop`, Ctrl+C och SIGTERM; revisionsrader `system.start`, `system.stop_requested` och `system.stop`.
- Migration 3 `runtime_state`: driftläge, pid, tider, stoppbegäran och hur förra körningen slutade (`clean`, `error`, `unclean`).
- Start vägras om revisionsloggen är manipulerad (SR-09) eller om systemet redan kör. En körning som dog utan nedstängning upptäcks och revideras.
- Ett oväntat fel loggas med traceback, ger kod 1 och stänger ändå ned systemet.
- `docs/setup.md` 2d: hur systemet startas och stoppas.
- `tests/unit/test_runtime.py`: 13 tester, bland annat med riktiga processer, och ett test i `test_storage_config.py` för samtidig öppning av en ny databas. Totalt 118.
### Rättat
- `memory/database.py`: två processer som öppnade en ny databas samtidigt kunde krocka. Migrationer kontrolleras nu igen under skrivlåset, och WAL slås på med nya försök i upp till 5 sekunder.
- Signalerna fångas innan något annat görs vid start, så att Ctrl+C under uppstarten också ger en ren nedstängning.
### Ändrat
- Hjälpen för konfigurationsfel (`_log_config_errors`) flyttad från `__main__.py` till `runtime.py`.

## [Unreleased] — 2026-10-23 — Fas 2 förberedd: livscykel och behörigheter
### Tillagt
- `src/aie/agents/`: livscykeln som tillståndsmaskin (FR-06) och ett agentregister i minnet med ID, roll, departement, chef och status (FR-05). En agent kan inte ändra sin egen status (SR-03). Varje ändring kräver motivering och sparas i historiken (SR-14).
- `config/permissions.toml`: verktygskatalog och mandat för MVP:ns sex roller (ceo, cfo, cro, auditor, research_lead, researcher). Inga verktyg flyttar pengar eller kontaktar omvärlden.
- `src/aie/authorization/`: `load_permissions` samlar alla fel och ger oföränderliga mandat. `AuthorizationEngine` nekar allt som inte är tillåtet (SR-01, SR-02), stoppar TESTING-agenter i prod (SR-13) och loggar varje beslut i audit-loggen. Går det inte att logga blir svaret nej.
- D-017 (föreslaget): behörighetsmodellen.
- `tests/unit/test_authorization.py`: 21 tester, bland annat ROADMAP:s nyckeltest för Fas 2. Totalt 125 gröna på Windows 11, Python 3.12.0.
### Medvetet inte med
- Ingen migration och ingen ändring i `__main__.py` eller `system.toml`, eftersom Robin bygger 1.6–1.7.

## [Unreleased] — 2026-10-23 — Fas 1.5: hashkedjad audit-logg
### Tillagt
- Migration 2: tabellen `audit_log` (seq, tid, actor, action, details, prev_hash, hash). Triggers gör att SQLite vägrar UPDATE och DELETE (SR-09).
- `src/aie/audit/`: `AuditLog(db).append(actor, action, details)` lägger till en rad i en transaktion. Raden hashas med SHA-256 över kanonisk JSON plus föregående rads hash.
- `AuditLog.verify()` går igenom kedjan och anger första trasiga raden: ändrat innehåll, bruten länk, saknad rad eller trasig JSON. `head_hash` är kedjans senaste hash.
- Hemliga nycklar (samma regel som konfigurationen) avvisas innan något skrivs, eftersom audit-loggen aldrig kan rensas (SR-10).
- `tests/unit/test_audit.py`: 15 tester, bland annat manipulation med triggers bortkopplade. Totalt 97 gröna på Windows 11, Python 3.12.0.
### Känd begränsning
- Om de sista raderna tas bort är resten av kedjan fortfarande giltig. Det syns bara om `head_hash` jämförs med en kopia som sparats någon annanstans, och den jämförelsen är inte byggd än.
### Ändrat
- `tests/unit/test_storage.py` räknar med antalet migrationer i stället för att anta att det bara finns en.

## [Unreleased] — 2026-10-23 — Fas 1.4b: lagring från konfigurationen
### Tillagt
- `open_database(config.system)` i `src/aie/memory/` öppnar `<data_dir>/<miljö>.db` med värdena från `config/system.toml` (FR-03).
- Lagringsfel loggas som ERROR i `aie.memory` innan de kastas vidare; en återrullad transaktion loggas som WARNING. Öppningen loggas som INFO med sökväg, miljö och schemaversion (FR-04).
- En `data_dir` som inte kan skapas, eller ett SQLite-fel vid öppning, blir `StorageError` med tydligt meddelande i stället för ett råfel.
- `tests/unit/test_storage_config.py`: 7 tester. Totalt 89, gröna på Python 3.11, 3.12 och 3.13.
### Ändrat
- Loggern `aie` har en `NullHandler` när loggningen inte är igång, så Pythons reserv-handler skriver inga varningar till stderr.

## [Unreleased] — 2026-10-23 — Fas 1.4: SQLite-lager
### Tillagt
- `src/aie/memory/`: `Database.open(data_dir, environment)` öppnar `<data_dir>/<miljö>.db` och kör migrationer, var och en i en egen transaktion (FR-03).
- Migration 1: tabellerna `metadata` (miljö, skapad, programversion) och `schema_migrations` (version, namn, kontrollsumma, tid). Båda är STRICT-tabeller.
- Uppstart stoppas med `StorageError` när databasen tillhör en annan miljö (SR-11), när den kommer från en nyare kodversion eller när en körd migration har ändrats.
- WAL, `synchronous=FULL` och främmande nycklar slås på vid öppning. Kräver SQLite >= 3.37.
- `tests/unit/test_storage.py`: 14 tester. Totalt 82 gröna på Yorgos dator (Windows 11, Python 3.12.0, SQLite 3.42.0), inklusive Fas 1.3.
### Rättat
- `monitoring/log.py`: felmeddelandet för en `log_dir` som inte kan skapas använde `repr()`, vilket dubblerade backslash i Windows-sökvägar. Därför föll `test_log_dir_that_is_a_file_gives_clear_error` på Windows. Felet syntes inte på Linux.

## [Unreleased] — 2026-10-23 — Arbetssätt och gemensamma godkännanden
### Tillagt
- CI: `.github/workflows/ai-enterprise-tests.yml` kör `python -m unittest discover -s tests -v` i `ai-enterprise/` på Python 3.11 och 3.12, vid varje PR och varje push till `main`.
- D-016: under byggfaserna mergar författaren sin egen PR när alla tester är gröna; besluten fattas gemensamt på plats.
### Ändrat
- DECISIONS.md: D-001–D-004 och D-013–D-016 är godkända av båda grundarna (beslutat gemensamt på plats, registrerat av Robin). Bara fälten *Status* och *Godkänd av* ändrades.

## [Unreleased] — 2026-10-23 — Robins Fas 0-godkännanden
### Ändrat
- DECISIONS.md: Robin har godkänt D-001, D-002, D-003, D-004 och D-013.
### Tillagt
- D-014: GitHub-repot är publikt (föreslaget av Robin, väntar på Yorgo).
- `docs/environment.md`: Robins miljörapport från Claude Code i molnet (REDO för Fas 1, 49 tester OK); `docs/setup.md` beskriver var respektive grundare utvecklar.

## [0.2.0] — 2026-10-23 — Fas 1.3: loggning
### Tillagt
- `src/aie/monitoring/`: loggning med Pythons `logging` (FR-04). Varje händelse skrivs som en JSON-rad i `<log_dir>/aie.log` (tidsstämpel i UTC, nivå, källa, plats i koden, meddelande, valfria fält) och som läsbar text i konsolen.
- Maskering av hemligheter i fil och konsol (SR-10): `nyckel=värde` där nyckeln ser ut som `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` eller `password`; hemliga nycklar i strukturerade fält; värdet av hemliga miljövariabler var det än står, även i tracebacks.
- En saknad `log_dir` skapas automatiskt. Kan den inte skapas blir det `LoggingSetupError`, och `check-config` skriver `FEL: log_dir ...` och avslutar med kod 1.
- `log_level` i `config/system.toml` (DEBUG, INFO, WARNING, ERROR, CRITICAL). Valfri, standard INFO. Ett okänt värde är ett konfigurationsfel (FR-02). Beslut D-015 föreslaget.
- Loggfilen roteras med `RotatingFileHandler`: vid 5 MB blir `aie.log` till `aie.log.1`, och högst tre gamla filer sparas.
- `check-config` loggar resultatet. Konfigurationsfel skrivs ut som förut och loggas dessutom i `logs/` i arbetsmappen, eftersom `log_dir` är okänd när konfigurationen är ogiltig.
- `tests/unit/test_logging.py` med 19 tester. Totalt 68 tester, alla gröna i Robins Claude Code-molnmiljö (Linux, Python 3.13.17).
### Ändrat
- `is_secret_key` i `src/aie/config/loader.py` är nu publik så att loggningen använder samma regel som konfigurationen.
- Version 0.1.0 → 0.2.0 i `pyproject.toml` och `src/aie/__init__.py`.

## [0.1.0] — 2026-10-21 — Fas 1.1–1.2: paket och konfiguration
### Tillagt
- `pyproject.toml` (paket `aie`, Python >= 3.11, inga beroenden).
- `src/aie/` med `__version__ = "0.1.0"` och CLI:t `python -m aie check-config` (kod 0 = giltig, kod 1 = ogiltig).
- `src/aie/config/`: laddare som returnerar frysta dataklasser och samlar alla valideringsfel i ett meddelande (FR-02, ER-01, ER-02, ER-05, ER-15, SR-10).
- `config/system.toml` och `config/risk_limits.toml` med simulerade värden för alla tio §25-parametrar samt `API_REINVEST_SHARE` och `API_MONTHLY_CAP`.
- D-013: format och valideringsregler för konfigurationen (föreslaget).
- `tests/unit/test_config.py` med 31 tester. Totalt 49 tester, alla gröna på Yorgos dator (Windows 11, Python 3.12.0).
- `docs/environment.md`: Yorgos miljörapport (REDO för Fas 1).
### Ändrat
- `tests/unit/__init__.py` lägger till `src/` i `sys.path` så att testerna körs utan installation.
- `docs/setup.md`: hur paketet körs utan installation, och `py -3` för skript på Windows (shebang-problemet).

## [0.0.4] — 2026-10-21 — Kanalregister och självständig utredning
### Tillagt
- D-011: agenterna utreder själva nya kanaler och lösningar; grundare godkänner.
- `docs/channels.md`: mall + Gumroad, Etsy och Fiverr.
- Krav FR-25 (totalt 79 krav).

## [0.0.4] — 2026-10-21 — Fiverr, forskningskö och konversationsarkiv
### Tillagt
- Fiverr som tjänstekanal i D-010. D-011 (systemet utreder öppna frågor), D-012 (sessioner arkiveras).
- `research/QUESTIONS.md` (R-01…R-10), `docs/conversations/` med första sessionen.
- Krav FR-25, FR-26 (totalt 80 krav).

## [0.0.3] — 2026-10-21 — Försäljningsplattformar
### Tillagt
- D-010: Gumroad och Etsy som försäljningskanaler (avgifter, moms, AI-regler, DAC7).
- Krav SR-18 och ER-23 (totalt 78 krav).

## [0.0.2] — 2026-10-21 — Gratis modeller och skatt
### Tillagt
- D-008 (gratis språkmodeller via ProviderRouter, ersätter D-005), D-009 (betalda API:er finansieras av realiserad vinst), D-010 (skattespår utan aktiebolag).
- Krav ER-18…ER-22 och DR-12…DR-13 (totalt 76 krav).
- `scripts/llm_smoke_test.py` + `tests/unit/test_llm_smoke.py` (8 tester, totalt 18 gröna).
### Ändrat
- ARCHITECTURE.md: avsnitt om gratis modeller, ProviderRouter, uppgradering till betalda API:er och Tax Engine. Q-05 och Q-06 omformulerade.

## [0.0.1] — 2026-10-21 — Fas 0 påbörjad
### Tillagt
- CONSTITUTION.md (v1.0, oförändrad kopia av grundarnas master prompt).
- REQUIREMENTS.md: 69 krav (24 FR, 17 SR, 17 ER, 11 DR).
- ARCHITECTURE.md: arkitekturförslag, verktygsregister, analys av modellåtkomst.
- DECISIONS.md: D-001…D-007 (föreslagna), Q-01…Q-08.
- ROADMAP.md, PROJECT_STATUS.md, README.md, docs/setup.md, docs/environment.md.
- scripts/check_env.py + tests/unit/test_check_env.py (10 tester, gröna i Claudes Linux-miljö).
