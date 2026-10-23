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
| 0.8 | Godkänna/avvisa D-001…D-010 i DECISIONS.md och besvara Q-01 | Båda | ◐ (D-001–D-004 godkända 2026-10-23; D-005–D-010 och Q-01 öppna) |
| 0.9 | Gratis modellgränssnitt: `scripts/llm_smoke_test.py` + 8 tester mot falsk server | Claude | ✅ (testat lokalt; riktiga API:er kunde inte nås från Claudes miljö) |
| 0.10 | Skapa gratiskonto hos Groq (och ev. OpenRouter), kör `llm_smoke_test.py`, klistra in resultatet i `docs/environment.md` | Minst en grundare | ☐ |

**Acceptanskriterier Fas 0 (§48):**
- [x] Arkitekturen är dokumenterad.
- [x] Verktygsvalen är motiverade, med licens och kostnad.
- [x] Inga okända obligatoriska betaltjänster finns i planen (API och hosting uttryckligen uteslutna).
- [x] Kritiska säkerhetsgränser är identifierade (SR-01…SR-17).
- [x] Båda grundarnas miljöer är inventerade (0.5, 0.6).
- [ ] Besluten är godkända av grundarna (0.8).

## Fas 1 — Grundsystem (FR-01…04, SR-09 grund, SR-10, DR-08) ← **pågår**
1.1 Paketstruktur `src/aie/`, `pyproject.toml`, `.gitignore`. ✅ (2026-10-21, gren `fas1-grund`)
1.2 Konfigurationsläsning + validering (`config/system.toml`, `config/risk_limits.toml`). ✅ (2026-10-21, 31 tester gröna, väntar på granskning)
1.3 Strukturerad loggning (JSON-rader till `logs/`). ✅ (2026-10-23, gren `robin/fas1-3-loggning`, 68 tester gröna, sammanslagen i PR #4)
1.4 SQLite-lager med migrationer och metadatatabell (miljö, schemaversion). ✅ (2026-10-23, gren `yorgo/fas1-4-sqlite`, 14 tester gröna, PR #5)
1.5 Hashkedjad audit-logg (append-only).
1.6 CLI: `init`, `start`, `stop`, `status`.
1.7 Tester: konfigurationsfel stoppar start · data överlever omstart · manipulerad audit-rad upptäcks.

## Fas 2 — Agentramverk (FR-05…08, SR-01…03, SR-13, SR-14)
Agentregister, mandat i `config/permissions.toml`, livscykel som tillståndsmaskin, uppgifter, rapportformat, Authorization Engine (default deny), ProviderRouter med Groq/OpenRouter/Ollama/`rule`, kvotspårning och dataklassning (DR-12, DR-13).
Nyckeltest: en agent försöker använda ett verktyg utanför mandatet → nekas och loggas.

## Fas 3 — Hierarki och samarbete (FR-09…14, SR-04…06, SR-16)
CEO-flöde, departementschefer, beslutspost i 11 steg, samråd, oenighet, eskalering, godkännandekö. `manual`-provider införs.
Nyckeltest: CEO försöker höja sin egen gräns → nekas. CFO och CRO oense → eskaleras med dokumenterad tvist.

## Fas 4 — Ekonomisk kontroll (ER-01…17, SR-07, SR-08, SR-11, SR-12)
Ledger, budgetmotor, reserv, uppdelningsdetektering, nettovinst, stop-loss, nödstopp, skyddat driftläge, idempotens, Tax Engine (ER-18…21), spärrad `API_SPEND` (ER-22).
Nyckeltester: budgetöverskridande blockeras · samma externa ID två gånger → avvisas · 10 köp à 99 under gräns 100 men inom samma initiativ → flaggas · nödstopp → inga nya transaktioner, ingen data raderad.

## Fas 5 — Lärande och utvärdering (FR-15…19, SR-17)
Incidentrapporter, prognoslogg, utvärdering, lärdomsregister med verifieringsstatus, versionerade strategier.

## Fas 6 — Affärssimulering (FR-20…24)
Simulerade marknader och scenarier i `SIM`-valuta. Audit jämför rapporter mot transaktionsdata. Resultaten avgör om pilot är försvarbar.

## Fas 7 — Kontrollerad pilot
Kräver: Fas 1–6 godkända, Q-03…Q-05 och Q-07 besvarade, §25-parametrar satta, nödstopp testat, skattespår för pilotens intäkter bekräftat med Skatteverket.

## Fas 8 — Kontinuerlig drift
Återkommande cykel enligt §56, statusrapport per cykel.
