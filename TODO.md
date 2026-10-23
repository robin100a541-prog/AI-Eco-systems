# Shared Task List

Format: `- [ ] task — @owner (branch)`. Claim before you start.

## Now
- [ ] ai-enterprise Fas 2-avslut: D-018 godkänt, D-019 beslutsrätt (Q-01) — @robin (robin/fas2-avslut)
- [ ] ai-enterprise Fas 3: beslutslogg (§20 steg 7, spårbarhet uppgift → beslut) — @robin (robin/fas3-beslutslogg)
- [ ] ai-enterprise Fas 3: oenighet (§21: påståenden, bevis, konflikttyp; inga omröstningar över hårda gränser) — @robin (robin/fas3-oenighet)
- [ ] ai-enterprise Fas 3: eskalering till grundarna enligt D-019, godkännandekö i CLI — @robin (robin/fas3-eskalering)
- [ ] Fill in Goal + Tech stack in CLAUDE.md — @robin
- [ ] Add friend as collaborator, fill in Team table — @robin

## Next
- Godkännande av D-018 (båda).
- ai-enterprise Fas 3: CEO-flöde, departementschefer, samråd mellan agenter — Yorgo (överenskommet på plats)

## Done
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
