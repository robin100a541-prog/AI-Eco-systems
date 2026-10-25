# ROADMAP — implementeringsplan

Varje fas avslutas först när alla **M-krav** för fasen (REQUIREMENTS.md) har gröna tester eller dokumenterad manuell verifiering, och resultatet är noterat i PROJECT_STATUS.md och CHANGELOG.md.

## Fas 0 — Krav och tekniska förutsättningar ← **pågår**

| # | Uppgift | Vem | Klar |
|---|---|---|---|
| 0.1 | Kravlista med ID:n (REQUIREMENTS.md) | Claude | ✅ |
| 0.2 | Arkitekturförslag + verktygsregister (ARCHITECTURE.md) | Claude | ✅ |
| 0.3 | Beslutsförslag D-001…D-007 + öppna frågor | Claude | ✅ |
| 0.4 | Miljökontrollskript `scripts/check_env.py` + tester | Claude | ✅ (testat i Claudes Linux-miljö) |
| 0.5 | Köra `check_env.py` på **Yorgos** dator, spara resultat i `docs/environment.md` | Yorgo | ✅ (2026-10-21, Windows 11) |
| 0.6 | Köra `check_env.py` på **Robins** dator, spara resultat i `docs/environment.md` | Robin | ✅ (2026-10-23, Claude Code i molnet, PR #3) |
| 0.7 | Skapa privat GitHub-repo, lägga till varandra, pusha dessa filer | En grundare | ☐ |
| 0.8 | Godkänna/avvisa D-001…D-010 i DECISIONS.md och besvara Q-01 | Båda | ◐ (D-001–D-004 godkända och Q-01 besvarad av D-019, 2026-10-23; D-005–D-010 öppna) |
| 0.9 | Gratis modellgränssnitt: `scripts/llm_smoke_test.py` + 8 tester mot falsk server | Claude | ✅ (testat lokalt; riktiga API:er kunde inte nås från Claudes miljö) |
| 0.10 | Skapa gratiskonto hos Groq (och ev. OpenRouter), kör `llm_smoke_test.py`, klistra in resultatet i `docs/environment.md` | Minst en grundare | ☐ |

**Acceptanskriterier Fas 0 (§48):**
- [x] Arkitekturen är dokumenterad.
- [x] Verktygsvalen är motiverade, med licens och kostnad.
- [x] Inga okända obligatoriska betaltjänster finns i planen (API och hosting uttryckligen uteslutna).
- [x] Kritiska säkerhetsgränser är identifierade (SR-01…SR-17).
- [x] Båda grundarnas miljöer är inventerade (0.5, 0.6).
- [ ] Besluten är godkända av grundarna (0.8).

## Fas 1 — Grundsystem (FR-01…04, SR-09 grund, SR-10, DR-08) ✅ **klar 2026-10-23**
1.1 Paketstruktur `src/aie/`, `pyproject.toml`, `.gitignore`. ✅ (2026-10-21, gren `fas1-grund`)
1.2 Konfigurationsläsning + validering (`config/system.toml`, `config/risk_limits.toml`). ✅ (2026-10-21, 31 tester gröna, väntar på granskning)
1.3 Strukturerad loggning (JSON-rader till `logs/`). ✅ (2026-10-23, gren `robin/fas1-3-loggning`, 68 tester gröna, sammanslagen i PR #4)
1.3b CI: GitHub Actions kör testerna på Python 3.11 och 3.12 vid varje PR och push till `main`. ✅ (2026-10-23, PR #7)
1.4 SQLite-lager med migrationer och metadatatabell (miljö, schemaversion). ✅ (2026-10-23, gren `yorgo/fas1-4-sqlite`, 14 tester gröna, PR #5)
1.4b Databasen öppnas från `data_dir` och miljön i konfigurationen; lagringsfel loggas. ✅ (2026-10-23, gren `robin/fas1-4b-lagring-config`, 89 tester gröna)
1.5 Hashkedjad audit-logg (append-only). ✅ (2026-10-23, gren `yorgo/fas1-5-audit`, 15 tester gröna)
1.6 CLI: `init`, `start`, `stop`, `status`. ✅ (2026-10-23, gren `robin/fas1-6-start-stop`, 118 tester gröna)
1.7 Tester: konfigurationsfel stoppar start · data överlever omstart · manipulerad audit-rad upptäcks. ✅ (2026-10-23, `tests/acceptance/test_fas1.py`, 151 tester gröna)

**Acceptanskriterier Fas 1 (konstitutionen §49).** Varje kriterium har ett eget acceptanstest i `tests/acceptance/test_fas1.py` som kör de riktiga kommandona i egna processer:
- [x] Systemet startar och avslutas korrekt: `TestStartsAndStops` (`init`, `start`, `stop`, `status` ger kod 0, ren nedstängning, även med Ctrl+C).
- [x] Konfigurationen kan läsas och valideras: `TestConfigReadAndValidated` (giltig konfiguration godkänns; en ogiltig listar alla fel och stoppar start).
- [x] Fel loggas: `TestErrorsLogged` (konfigurationsfel och lagringsfel i loggfilen med tid, nivå och källa; hemligheter syns aldrig).
- [x] Data överlever omstart: `TestDataSurvivesRestart` (två körningar; en dödad process utan nedstängning; ingen data försvinner, kedjan är intakt).
- [x] Tester kan köras reproducerbart: `TestReproducible` (bara standardbiblioteket) samt CI på Python 3.11 och 3.12 vid varje PR och push. Hela sviten skriver bara i temporära mappar.
- [x] ROADMAP 1.7: en manipulerad audit-rad upptäcks: `TestTamperedAuditDetected` (`status` ger kod 1 och `start` vägrar).

## Fas 2 — Agentramverk (FR-05…08, SR-01…03, SR-13, SR-14) ✅ klar 2026-10-23 (version 0.4.0)
Agentregister, mandat i `config/permissions.toml`, livscykel som tillståndsmaskin, uppgifter, rapportformat, Authorization Engine (default deny), ProviderRouter med Groq/OpenRouter/Ollama/`rule`, kvotspårning och dataklassning (DR-12, DR-13).
Nyckeltest: en agent försöker använda ett verktyg utanför mandatet → nekas och loggas.

Förberett 2026-10-23 (gren `yorgo/fas2-prep-behorigheter`, D-017, godkänt av båda 2026-10-23): livscykel, agentregister i minnet, `config/permissions.toml` och Authorization Engine med default deny och audit-loggning. Nyckeltestet är grönt (`test_tool_outside_mandate_denied_and_logged`). Registret sparas i databasen sedan migration 4 (PR #14). Uppgifter (FR-07) finns sedan migration 5 (PR #16). Rapportformatet (FR-08) finns i `src/aie/reporting/` (PR #17). ProviderRouter med kvoter (DR-12) och dataklassning (DR-13) finns i `src/aie/llm/` och migration 6 (PR #18, D-018). `AgentWorker` kör hela kedjan uppgift → router → rapport → audit, och `tests/acceptance/test_fas2.py` har minst ett test per kriterium i §50.

**Acceptanskriterier Fas 2 (§50):**
- [x] Agenter har identifierbara roller (`TestRoles`).
- [x] Uppgifter kan tilldelas och följas upp (`TestTasksEndToEnd`).
- [x] Agenter kan inte använda obehöriga funktioner (`TestUnauthorized`, med nyckeltestet).
- [x] Agentstatus sparas beständigt (`TestPersistence`).
- [x] D-018 godkänt av båda (2026-10-23).

Agenter når `ProviderRouter` bara via `LLMGateway` och Authorization Engine (`llm.complete`), och prompter med hemligheter avvisas (2026-10-23, gren `robin/fas2-llm-behorighet`, 208 tester gröna).

## Fas 3 — Hierarki och samarbete (FR-09…14, SR-04…06, SR-16)
CEO-flöde, departementschefer, beslutspost i 11 steg, samråd, oenighet, eskalering, godkännandekö. `manual`-provider införs.
Nyckeltest: CEO försöker höja sin egen gräns → nekas. CFO och CRO oense → eskaleras med dokumenterad tvist.

| Del | Vem | Status |
|---|---|---|
| 3a Hierarki nivå 0–5, rapportvägar, departementschefer, styrverktyg (SR-04), Compliance (D-020) | Yorgo | ✅ första nyckeltestet grönt (`test_ceo_cannot_raise_own_limit_or_change_own_mandate`), PR #24 |
| 3b Kontrollfunktionernas stopp (SR-05), migration 7 | Yorgo | ✅ PR #26 |
| 3c Samråd (FR-11), migration 8 | Yorgo | ✅ PR #27 |
| 3d Beslutslogg (FR-10, §20 steg 7): migration 9 `decisions`, spårbarhet uppgift → beslut | Robin | ✅ gren `robin/fas3-beslutslogg` |
| 3e Oenighet (FR-12, §21): migration 10, påståenden, underlag och konflikttyp; inga röster över hårda gränser; ROADMAP:s nyckeltest CFO mot CRO | Robin | ✅ gren `robin/fas3-oenighet` |
| 3f Eskalering och godkännandekö (FR-13, D-019, D-021), migration 12; `python -m aie approvals` | Robin | ✅ PR #33 |
| 3g Externt innehåll är opålitlig data (SR-06) | Yorgo | ✅ PR #30 |
| 3h Juridisk konflikt ⇒ stopp och Compliance (SR-16), migration 11 | Yorgo | ✅ PR #31 |
| 3j `manual`-provider (D-005, D-022): `python -m aie manual`, ingen migration | Robin | ✅ PR #35 |
| 3k Tilldelning nedåt i befälskedjan (§51 "rätt ansvarig roll", D-023) | Robin | ✅ gren `robin/fas3-delegering` |
| 3i Utred möjlighet (FR-25, D-011), migration 14, D-025 | Yorgo | ☐ |

**Acceptanskriterier Fas 3 (§51)**, i `tests/acceptance/test_fas3.py` (12 tester, hela kedjan med de riktiga konfigurationsfilerna, ingen språkmodell):
- [x] Uppgifter går till rätt ansvarig roll (`TestRightRole`, D-023).
- [x] Beslut fattas endast inom tillåtna befogenheter (`TestAuthority`, med nyckeltestet "CEO försöker höja sin egen gräns").
- [x] Konflikter dokumenteras (`TestConflictsDocumented`).
- [x] Eskalering fungerar (`TestEscalation`, med nyckeltestet "CFO och CRO oense").
- [x] Det finns spårbarhet från uppgift till beslut (`TestTraceability`).
- [ ] 3i (Yorgo) och godkännande av D-020–D-023 återstår innan Fas 3 stängs.

## Fas 4 — Ekonomisk kontroll (ER-01…17, SR-07, SR-08, SR-11, SR-12)
Ledger, budgetmotor, reserv, uppdelningsdetektering, nettovinst, stop-loss, nödstopp, skyddat driftläge, idempotens, Tax Engine (ER-18…21), spärrad `API_SPEND` (ER-22).
| Del | Vem | Status |
|---|---|---|
| 4a Ledger (ER-01, ER-06–09, ER-11, ER-14–16, SR-12), migration 13, D-024: `src/aie/ledger/`, nettovinst och Audits återberäkning | Robin | ✅ gren `robin/fas4-ledger` |
| 4b Budgetmotor och kontroll före transaktion (ER-03, ER-17, ER-22) | Robin | ☐ tagen |
| 4c Reserv och kapitalbegrepp (ER-05, ER-10) | – | ☐ ledig |
| 4d Uppdelningsdetektering (ER-04) | – | ☐ ledig |
| 4e Stop-loss, nödstopp, skyddat driftläge (ER-13, SR-07, SR-08) | – | ☐ ledig |
| 4f Tax Engine (ER-18…21) | – | ☐ ledig |

Nyckeltester: budgetöverskridande blockeras · samma externa ID två gånger → avvisas · 10 köp à 99 under gräns 100 men inom samma initiativ → flaggas · nödstopp → inga nya transaktioner, ingen data raderad.

## Fas 5 — Lärande och utvärdering (FR-15…19, SR-17)
Incidentrapporter, prognoslogg, utvärdering, lärdomsregister med verifieringsstatus, versionerade strategier.

## Fas 6 — Affärssimulering (FR-20…24)
Simulerade marknader och scenarier i `SIM`-valuta. Audit jämför rapporter mot transaktionsdata. Resultaten avgör om pilot är försvarbar.

## Fas 7 — Kontrollerad pilot
Kräver: Fas 1–6 godkända, Q-03…Q-05 och Q-07 besvarade, §25-parametrar satta, nödstopp testat, skattespår för pilotens intäkter bekräftat med Skatteverket.

## Fas 8 — Kontinuerlig drift
Återkommande cykel enligt §56, statusrapport per cykel.
