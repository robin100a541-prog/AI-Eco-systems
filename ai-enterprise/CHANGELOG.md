# CHANGELOG

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
