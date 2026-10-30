# Shared Task List

Format: `- [ ] task — @owner (branch)`. Claim before you start.

## Now
- **Överlämning endast 2026-10-26:** Robin lämnar över alla sina uppgifter till @yorgo-jarjous **endast idag**. Robin har godkänt överlämningen 2026-10-26 (endast idag). Från 2026-10-27 gäller den vanliga fördelningen igen, och det som inte är klart går tillbaka till @robin.
- [x] Fill in Goal + Tech stack in CLAUDE.md — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/overlamning-idag)
- [x] Add friend as collaborator — klart (Yorgo-jarjous är collaborator); fill in Team table — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/overlamning-idag)
- [x] ai-enterprise Fas 4f: Tax Engine (ER-18–21), migration 21–22, D-032–D-034, Fas 4 stängd — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/fas4f-tax)
- [x] ai-enterprise Fas 5d: lärdomsregister (FR-17), migration 23, D-038 — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/fas5d-lardomar)
- [x] ai-enterprise Fas 5e: versionerade strategier (FR-18), migration 24, D-039 — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/fas5e-strategier)
- [x] ai-enterprise Fas 5f: ingen avveckling för obekväma slutsatser (SR-17), D-040 — @robin → @yorgo-jarjous (endast 2026-10-26) (yorgo/fas5f-sr17)
- [x] ai-enterprise Fas 6a: koppla in spärrar, incidentlogg, prognoslogg och prestationsmätning i `python -m aie start` — @yorgo-jarjous (yorgo/fas6a-koppling)
- [x] ai-enterprise Fas 6b-1: simulerat startkapital, marknad och scenarier (FR-20), migration 26, D-042 — @yorgo-jarjous (yorgo/fas6b1-marknad)
- [x] ai-enterprise Fas 6b-2: åtgärdsprotokoll och arbetscykel, `python -m aie simulate` (FR-20, FR-23), D-043, D-044 (behörighetsändring) — @yorgo-jarjous
- [x] ai-enterprise Fas 6b-3: daglig rapport och affärsförslag (FR-21, FR-23), D-045 — övertagen av Robin enligt D-049 (#93 var bara ett anspråk)
- [x] ai-enterprise Fas 6b-4: övervakning och periodisk rapport (FR-24, FR-22), migration 36 (27 användes av F3), D-046 — övertagen av Robin enligt D-049; ingen migration behövdes
- [ ] ai-enterprise Fas 6b-5: acceptanstester för §54, Fas 6 stängs — @yorgo-jarjous
- [ ] ai-enterprise Arbetsorder 02 (`docs/prompts/02-fixar-och-plattformar.md`) — @yorgo-jarjous, en session åt gången. **Reserverat 2026-10-28: migration 28–35 och D-051–D-064.** Nattboten och andra sessioner: rör inte punkterna nedan.
  - [x] F1+F2 budgettak per departement och återinvestering (PR #82)
  - [x] F3+F4 skattebetalning och skatteunderlag, migration 27 (PR #83)
  - [x] F5 godkända utgifter förbrukas en gång, migration 28 (PR #84)
  - [x] F6 uppdelade köp per departement och dag, initiativspärr (PR #85)
  - [ ] F7 granskningsregel och CLAUDE.md — PR #86 öppen, väntar på en grundare
  - [ ] PR 4 plattforms- och initiativregister · PR 5 webbläsning · PR 6 simulering före start · PR 7 plattformsberoende · PR 8 Groq i simuleringen · PR 9 schemalagd körning · PR 10 import av verkliga resultat · PR 11 produktutkast


## Next
- **Nummerfördelning (för att undvika krockar):** migration 7–8 och D-020 är använda av Yorgo (PR #26, #27). **Robin: migration 9–10 och 12 (använda), samt D-021–D-024** (beslutslogg, oenighet, eskalering; D-021 använd). **Robin: migration 13 (ledgern), D-024, D-026, D-027 och D-028** (D-021–D-024 var slut; D-025 är Yorgos). **Yorgo: migration 11 och 14 samt D-025** (SR-16, FR-25). Ändrat 2026-10-23: migrationer måste vara 1..N utan luckor, och eskaleringen (13) var inte påbörjad, så Yorgo tog 11–12. Ändrat igen 2026-10-23 (Robin): eskaleringen blev klar före FR-25, som inte var påbörjad, så eskaleringen tog 12 och FR-25 får 13. Ändrat 2026-10-25 (Robin): ledgern blev klar medan FR-25 (#32) fortfarande var ett utkast med nummer 12 som ändå måste bytas, så ledgern tog 13 och FR-25 får 14. Övriga Fas 4-delar (budgetmotor, reserv, uppdelningsdetektering, stop-loss, nödstopp, skyddat driftläge, Tax Engine) är inte tagna. Använt 2026-10-26 (Yorgo): **migration 15–17 och D-029–D-031** för Fas 4e. **Robin: migration 18–19 och D-032–D-034** för Tax Engine (4f), ej påbörjad. **Yorgo: migration 20–22 och D-035–D-037** för Fas 5a–5c. Migrationer måste vara 1..N utan luckor. Om Robin använder färre nummer, eller om Yorgo blir klar först, numreras Yorgos migrationer om till nästa lediga före sammanslagning och det skrivs här. **Fas 5 lämnas åt Robin:** lärdomsregistret (FR-17), versionerade strategier (FR-18) och SR-17 (ingen avveckling för obekväma slutsatser). Den som behöver fler tar nästa nummer efter den andres block och skriver det här först. **Omnumrerat 2026-10-26 (Yorgo):** Tax Engine var inte påbörjad när 5a blev klar, så Fas 5a–5c tar **migration 18–20** (i stället för 20–22). **Robin får migration 21–22** för Tax Engine; D-032–D-034 är oförändrade. **Överlämning 2026-10-26 (endast idag):** Yorgo använder Robins migration 21–22 och D-032–D-034 för Tax Engine, samt migration 23 och uppåt och D-038 och uppåt för FR-17, FR-18 och SR-17. **Fas 6b (Yorgo, plan godkänd av båda 2026-10-26): migration 26–27 och D-042–D-046.** Nästa lediga efter det: migration 28 och D-047. **Använt 2026-10-27 (Yorgo): D-047 och D-048** (budgetmodell och vägen till riktiga pengar). Nästa lediga: D-049. **Använt 2026-10-28 (Robin): D-050** (utvecklaragenten). Nästa lediga: D-051 (D-049 i PR #70). **Reserverat 2026-10-28 (Yorgo, arbetsorder 02): migration 28–35 och D-051–D-064.** Migration 27 användes 2026-10-28 av F3 (tax_payment), eftersom migrationerna måste vara 1..N utan luckor; 6b-4 får i stället migration 36. Nästa lediga efter det: migration 37 och D-065. **Använt 2026-10-28 (Robin): D-049** (grundarna agerar som en). Nästa lediga: D-050.

## Done
- [x] ai-enterprise Fas 5c: prestationsmätning per roll (FR-19, §31), migration 20, D-037 — @yorgo-jarjous (PR #53)
- [x] ai-enterprise Fas 5b: prognoslogg och prognos mot utfall (FR-16), migration 19, D-036 — @yorgo-jarjous (PR #52)
- [x] ai-enterprise Fas 5a: incidentrapporter (FR-15), migration 18, D-035 — @yorgo-jarjous (PR #51)
- [x] ai-enterprise Fas 4e: stop-loss (PR #46), nödstopp (PR #47), skyddat driftläge — migration 15–17, D-029–D-031 — @yorgo-jarjous
- [x] ai-enterprise Fas 3i: Utred möjlighet (FR-25, D-011), migration 14, D-025 — @yorgo-jarjous (PR #32)
- [x] ai-enterprise Fas 4d: uppdelningsdetektering (ER-04), D-028 — @robin
- [x] ai-enterprise Fas 4c: skyddad reserv och kapitalbegrepp (ER-05, ER-10), D-027 — @robin
- [x] ai-enterprise Fas 4b: budgetmotor och kontroll före transaktion, `config/budgets.toml`, D-026 — @robin
- [x] ai-enterprise Fas 4a: ledger (§40, ER-01, ER-06–09, ER-11, ER-14–16, SR-12), migration 13, D-024 — @robin
- [x] ai-enterprise Fas 3-acceptans: `tests/acceptance/test_fas3.py`, ett eller flera tester per kriterium i §51 — @robin
- [x] ai-enterprise Fas 3k: uppgifter tilldelas bara nedåt i befälskedjan (D-023, ändrar Yorgos `TaskBoard.assign`) — @robin
- [x] ai-enterprise Fas 3j: `manual`-provider, `python -m aie manual`, D-022 — @robin
- [x] ai-enterprise Fas 3h: juridisk konflikt ⇒ stopp och Compliance (SR-16), migration 11 — @yorgo-jarjous (PR #31)
- [x] ai-enterprise Fas 3g: externt innehåll är opålitlig data (SR-06) — @yorgo-jarjous (PR #30)
- [x] ai-enterprise Fas 3: eskalering till grundarna enligt D-019, godkännandekö i CLI — @robin
- [x] ai-enterprise Fas 3: oenighet (§21) — @robin
- [x] ai-enterprise Fas 3: beslutslogg (§20 steg 7, spårbarhet uppgift → beslut) — @robin
- [x] ai-enterprise Fas 3c: samråd FR-11 (migration 8) — @yorgo-jarjous (yorgo/fas3-samrad)
- [x] ai-enterprise Fas 3b: kontrollfunktionernas stopp SR-05 (migration 7) — @yorgo-jarjous (PR #26)
- [x] ai-enterprise Fas 3a: hierarki, rapportvägar, styrverktyg (SR-04), Compliance, D-020 — @yorgo-jarjous (PR #24)
- [x] ai-enterprise Fas 2-avslut: D-018 godkänt, D-019 beslutsrätt (Q-01 besvarad) — @robin
- [x] ai-enterprise Fas 2-acceptans: AgentWorker via LLMGateway, acceptanstester §50, version 0.4.0 — Fas 2 klar — @yorgo-jarjous (PR #20)
- [x] ai-enterprise Fas 2: agenter når ProviderRouter bara via Authorization Engine (`llm.complete`), läcktester (DR-12, DR-13) — @robin (PR #19)
- [x] ai-enterprise Fas 2: ProviderRouter, kvoter, dataklassning — @yorgo-jarjous (PR #18)
- [x] ai-enterprise Fas 2: rapportformat FR-08 — @yorgo-jarjous (PR #17)
- [x] ai-enterprise Fas 2: uppgifter FR-07 (migration 5) — @yorgo-jarjous (PR #16)
- [x] ai-enterprise Fas 2: agentregistret i databasen (migration 4) — @yorgo-jarjous (PR #14)
- [x] ai-enterprise Fas 2 (förberedelse): livscykel, agentregister i minnet, `config/permissions.toml`, Authorization Engine, D-017 — @yorgo-jarjous (PR #11)
- [x] ai-enterprise Fas 1.6–1.7: start/stop/status, acceptanstester — Fas 1 klar — @robin (PR #12 och PR #13)
- [x] ai-enterprise Fas 1.4b: lagring från config, fel loggas — @robin (PR #8)
- [x] ai-enterprise Fas 1.5: hashkedjad audit-logg (append-only) — @yorgo-jarjous (PR #9)
- [x] ai-enterprise Fas 1.4: SQLite-lager med migrationer och metadatatabell — @yorgo-jarjous (PR #5)
- [x] CI: testerna körs på Python 3.11 och 3.12 — @robin (PR #7)
- [x] ai-enterprise Fas 1.3: loggning (fil + konsol, maskerade hemligheter) — @robin (PR #4)
- [x] Add ai-enterprise (Fas 0 + Fas 1.1–1.2: package + validated config) to `ai-enterprise/` — @yorgo-jarjous (PR #1)
