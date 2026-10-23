# Shared Task List

Format: `- [ ] task — @owner (branch)`. Claim before you start.

## Now
- [ ] ai-enterprise Fas 2: efter PR #18 — agenter når ProviderRouter bara via Authorization Engine (`llm.complete`), läcktester för logg/audit/prompt (DR-12, DR-13) — @robin (robin/fas2-llm-behorighet)
- [ ] Fill in Goal + Tech stack in CLAUDE.md — @robin
- [ ] Add friend as collaborator, fill in Team table — @robin
- [ ] ai-enterprise Fas 2: ProviderRouter + kvoter (DR-12) och dataklassning (DR-13), migration 6 `provider_usage` — @yorgo-jarjous (yorgo/fas2-provider-router)

## Next
- ai-enterprise Fas 2-acceptans: agenter som resonerar via ProviderRouter (rule i tester), uppgift → rapport → audit från början till slut, ROADMAP:s nyckeltest som acceptanstest. Godkännande av D-018 (båda).

## Done
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
