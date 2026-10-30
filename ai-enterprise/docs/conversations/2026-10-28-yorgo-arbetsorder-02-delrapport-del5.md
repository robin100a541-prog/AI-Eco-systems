# Delrapport efter DEL 5, arbetsorder 02 (2026-10-28)

Session: Yorgo och Claude (Opus 5.5) i Claude Code. Arbetsordern finns i `docs/prompts/02-fixar-och-plattformar.md`.

## Läget vid start (verifierat)
- main var på `a086130`, inte `083bb25`. PR #68–#79 hade tillkommit.
- D-049 ("en grundares godkännande räcker") ersätter D-019 punkt 2 och 3. Arbetsorderns krav på "båda grundarna" läses därför som "en grundare".
- `DECISIONS.md`, `risk_limits.toml`, `permissions.toml`, `CONSTITUTION.md` och `docs/BOT.md` är skyddade av CI-kontrollen `protected-files`. De kräver etiketten `founder-approved`, som bara en grundare sätter. Nya beslutsförslag läggs därför i `docs/proposals/`, och `DECISIONS.md` uppdateras i en egen PR som lämnas öppen.
- Nummer reserverade och pushade före kod (PR #80): migration 28–35 och D-051–D-064. Migration 27 användes av F3, eftersom migrationerna måste vara 1..N, och 6b-4 får migration 36.

## Rättat och sammanslaget

| Punkt | PR | Vad | Förslag |
|---|---|---|---|
| F1+F2 | #82 | Departementens tak räknas från en fast bas. Research nådde 95 % av basen före rättelsen och når 40,0 % efter. Bufferten på 44 % skyddas, och 20 % av vinsten spenderas aldrig. | D-051 |
| F3+F4 | #83 | Posttypen `tax_payment` (migration 27, ledgern återskapad utan dataförlust). Avsättningen per spår och år minus betald skatt. `basis = revenue/profit`. | D-052 |
| F5 | #84 | Godkända utgifter (migration 28): giltiga 7 dagar, förbrukas exakt en gång även vid samtidiga försök, och kopplade till simuleringen. `python -m aie spend`. | D-053 |
| F6 | #85 | Uppdelade köp per departement och dag oavsett initiativnamn, och initiativspärren (aktiveras med registret i PR 4). | D-054 |

Alla fyra har etiketten `kräver-oberoende-granskning` och ska granskas av någon som inte skrev dem innan Fas 7.

## Väntar på en grundare
- **PR #86 (F7):** granskningsregeln D-055 och en uppdaterad `CLAUDE.md`. Lämnad öppen enligt arbetsordern.
- **Beslutsförslagen D-051–D-055** finns i `docs/proposals/`. De förs in i `DECISIONS.md` i en egen PR som kräver `founder-approved`.

## Testresultat (faktiska körningar)
- Varje PR: de nya testerna är gröna lokalt och CI är grön på Python 3.11 och 3.12, även kontrollen `protected-files`.
- Hela sviten lokalt (Windows 11, Python 3.12) efter F6: `Ran 620 tests ... FAILED (errors=3, skipped=2)`.
  - De tre felen finns i `test_dev_agent`: databasfilen är låst när testmappen städas på Windows. De finns i main före arbetsorder 02, och de går igenom på Linux (CI). Det är ett eget fel som inte rättas i den här arbetsordern.

## Fortsätter med DEL 6
PR 4 (plattforms- och initiativregister) följer direkt.
