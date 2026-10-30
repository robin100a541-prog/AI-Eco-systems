# CHANGELOG

## [Unreleased] — 2026-10-30 — Fas 7b: manuell listning och försäljning
### Tillagt
- `aie pilot prepare --as <grundare> --product products/<id>`: visar listningen, priset, budgettaket (START_CAPITAL, 500 kr), stop-loss och stoppkriterierna, och lägger "godkänn piloten" i godkännandekön.
- `aie pilot approve <nr> --as Robin`: en grundare godkänner (D-049), och pilotkapitalet bokförs med hänvisning till godkännandet.
- `aie results import <csv> --format sales --as <grundare> --product ... --usd-sek ... [--platform-net ...]`: plattformens försäljnings-CSV bokförs i pilotens egen prod-databas i SEK (aldrig SIM): intäkt, avgift och återbetalning. Dubbletter bokförs en gång, skatten reserveras av Tax Engine, och summan stäms av mot plattformens netto (ER-23). En skillnad blir en incident.
- Stoppregler på riktiga data: stop-loss, ingen försäljning på 60 dagar eller en återbetalning per tre försäljningar sätter skyddat läge (inga nya utgifter) och rekommenderar avpublicering.
- Piloten kräver ett godkännande innan försäljning kan importeras.
## [Unreleased] — 2026-10-30 — Fas 7a/7c: produktagent och beslutscykel
### Tillagt
- `python -m aie pilot ideas`: produktagenten föreslår tre produkter via LLMGateway; koden räknar Gumroads avgift (10 % + 0,50 USD), netto, förväntat netto och största förlust, och efterfrågan är alltid overifierad.
- CFO och risk bedömer, en tvist öppnas och eskaleras till CEO när de är oense (§21), och CEO:s beslut med alla åtta fält i §20 steg 7 skrivs i beslutsloggen via godkännandekön.
- Varje modellsvar valideras i kod (fält, budget mot största förlust, förväntat netto, risk som borde invänt). Ett felaktigt svar avvisas och regeln används; 7c-rapporten visar varje roll.
- Den valda produkten skrivs till `products/<id>/`: product.md, product.pdf (stdlib), listing.md med upplysning om AI-användning och idea.json.
- Workflowen `pilot-groq.yml` kör allt på Groq vid knapptryck.
- Plattformens namn, avgift och CSV-kolumner ligger i `config/pilot.toml`, inte i koden (D-056).
## [Unreleased] — 2026-10-30 — Fas 7 steg 1: oberoende granskning
### Tillagt
- `docs/reviews/REVIEW-PROMPT.md`: den exakta prompten för en ny Claude-session som granskar säkerhetskritisk kod (D-055). Ingen granskning finns ännu; det är en grundaråtgärd.
- Utvecklaragenten pausas medan Fas 7–8 byggs: `docs/DEV-AGENT-PAUSED` gör att workflowen hoppar över agentsteget.
## [Unreleased] — 2026-10-30 — Utvecklaragentens regler och stängda frågor
### Ändrat
- Q-BOT-001–004 är stängda som "släppt, lågt värde" (Robin, 2026-10-30) och flyttade till Besvarade.
- Utvecklaragenten tar aldrig en uppgift i en fil som har en öppen grundarfråga. Uppgifter med dokumentation och tester går före lint: ordningen är dokumentation, krav och tester, kodkvalitet, lint, buggar.
## [Unreleased] — 2026-10-30 — Simuleringens marknad är overifierad
### Ändrat
- Varje SIM-rapport (daglig, periodisk och bedömningen före start) anger att marknadsantagandena är OVERIFIERADE, eftersom de kommer ur scenariofilerna och inte från riktig försäljning.
- "Redo" är bara en hypotes tills riktiga försäljningsdata finns (`real_results`, D-062). Rekommendationen börjar då med `HYPOTES:`. `simulate evaluate` skriver ut statusen, och rapportfilen har `status` och `market_assumptions: unverified|verified`.
## [Unreleased] — 2026-10-30 — Fas 6b-5: acceptanstester för §54
### Tillagt
- `tests/acceptance/test_fas6.py` har ett test per kriterium i §54. Alla körs mot riktiga simuleringar av repots scenarier:
  - SIM blandas aldrig med riktiga pengar,
  - förlustinitiativ identifieras,
  - riskgränser och nödstopp nekar utgifter,
  - dagliga och periodiska rapporter stämmer med ledgern,
  - stopp och omstart förlorar ingen historik.
### Rättat
- Daglig rapport: startkapital räknas inte längre som ett aktivt affärsinitiativ. En dag utan poster efter att ledgern startat visar 0 med notering i stället för `SAKNAS`, eftersom bara dagar innan ledgern fanns räknas som saknade data.

## [Unreleased] — 2026-10-30 — Fas 6b-4: övervakning och periodisk rapport (FR-24, FR-22, §58)
### Tillagt
- `reporting/monitor.py` (FR-24) läser revisionsloggen och ledgern och letar efter tre saker:
  - loopar: samma agent gör samma sak 5 gånger i rad,
  - upprepat arbete: samma åtgärd med samma underlag 3 gånger eller fler,
  - kostnad utan värde: ett initiativ med kostnader men ingen intäkt, eller en agent som bara anropar modellen.
- `reporting/periodic.py` (FR-22) täcker de tio punkterna i §58. Varje initiativ har samma nyckeltal, så att perioder och initiativ går att jämföra: netto, marginal, avkastning på kostnad, netto per dag och sämsta dag. Förlustinitiativ och övervakningsfynd blir rekommenderade förändringar, och saknade data står som `SAKNAS`.
- `python -m aie report daily|periodic|monitor` läser bara. `simulate` sparar dessutom en periodisk rapport för hela körningen i `<data_dir>/reports/`.
- Ingen migration behövdes, eftersom allt räknas om ur befintliga data. `tests/unit/test_periodic_report.py` har 5 tester.

## [Unreleased] — 2026-10-30 — Fas 6b-3: daglig rapport (FR-21, §57)
### Tillagt
- `src/aie/reporting/daily.py`: de elva punkterna i §57 hämtas direkt ur ledgern, budgetmotorn, stop-loss, nödstoppet, skyddat läge, incidenter och godkännandeköerna. Saknade data står som `SAKNAS: <skäl>`, aldrig som en tyst nolla.
- `python -m aie simulate start|resume` skriver en rapport per affärsdag till `<data_dir>/reports/daily-ÅÅÅÅ-MM-DD.md`.
- FR-23 (affärsförslagets elva fält) kontrollerades redan i `simulation/actions.py` (6b-2).
- `tests/unit/test_daily_report.py`: 4 tester.

## [Unreleased] — 2026-10-28 — Utvecklaragenten: kontroller som faktiskt bevisar något
### Rättat
- En ny eller omskriven kontroll som redan går igenom innan någon ändring gjorts avvisas, eftersom den inte bevisar något. Körning 9 lade till BL-006 med `!grep ... "__repr__"`, som var sann från början.
- `grep`/`!grep` tar bort citattecken runt texten, så att modellens `"text"` söker efter text och inte efter citattecknen.
- Högst tre förslag tas emot per körning, räknat efter att dubbletter och redan sanna förslag sorterats bort.
- En backloggpunkt som inte nämner någon fil tas ändå: filen tas från dess kontroll. En punkt utan kontroll skrivs om även om den inte nämner någon fil. BL-006–BL-008 hade inget filnamn och skulle aldrig ha tagits.
- `docs/BOT-BACKLOG.md`: BL-006 och BL-007 har fått kontroller som går att misslyckas med. BL-008:s kontroll var redan sann och är borttagen, så agenten skriver en ny.

## [Unreleased] — 2026-10-28 — Utvecklaragenten: en uppgift är klar först när dess kontroll bevisar det
### Ändrat
- `dev_agent/verify.py`: varje uppgift har en kontroll som körs efter att sviten gått grön. Lint: ruff hittar inte längre just det fyndet i filen. Fallerande test: testet går igenom, och ett instabilt (`flaky-test`) tre gånger i rad. Otestat krav: ett test vars docstring säger `Verifies <ID>` finns och går igenom. Backloggpunkt: kontrollen efter `Klart när:`. Går kontrollen inte igenom kastas ändringen, även om alla tester är gröna, och försöket räknas som misslyckat (`check_failed`).
- En backloggpunkt utan giltig kontroll tas inte. Agenten ber modellen skriva in en (`Klart när: ...`), högst två per körning.
- Agenten fyller själv på backloggen. I slutet av varje körning föreslår modellen högst tre nya, små punkter ur koden den läste. Punkter med giltig kontroll läggs till med nästa BL-nummer. Dubbletter hoppas över, och påfyllning sker inte när det redan finns 12 öppna punkter. Förslag om skyddade filer, CI, config, pengar, konton, kunder eller nya funktioner blir frågor i `QUESTIONS-FOR-FOUNDERS.md`.
- En körning öppnar nu också en PR när backloggen ändrats.

## [Unreleased] — 2026-10-28 — PR 11: produktutkast (utkast, inget publicerat)
### Tillagt
- `products/` innehåller tre kandidater med produkt eller tjänst, annonstext med AI-märkning, pris och valideringsplan. Varje kandidat har mätbara kriterier, en regel för att fortsätta, ändra eller sluta, och en checklista för det grundarna gör manuellt:
  - `hushallsbudget-mall` på Etsy
  - `frilans-fakturamall` på Gumroad
  - `kalkylark-stadning` på Fiverr
- `products/initiatives.toml`: kandidaterna som initiativ med status `idea`. Efterfrågan är märkt som antagande.
- **Bedömningen före start (D-058) är körd:** ingen kandidat är redo. Grundarnas tid är större än nettot vid de antagna volymerna. Utskriften och en tröskelkörning med fler besökare finns i `products/README.md`.
- `tests/unit/test_products.py`: 2 tester.

## [Unreleased] — 2026-10-28 — PR 10: utfall från verkligheten (D-062, föreslaget) · kräver-oberoende-granskning
### Tillagt
- Migration 32 `real_results`: en rad per dag och initiativ med källa, append-only och idempotent.
- `src/aie/results/` (`ResultStore`):
  - Import av CSV. Bara grundare importerar, en källa krävs på varje rad, och en dålig rad avvisar hela filen.
  - Sammanställning per valuta.
  - Rapporten prognos mot utfall.
- `python -m aie results import|list|report`.
- Bedömningen före start använder uppmätta värden före antaganden när initiativet har minst 7 dagar med utfall, märkta "verifierat i verkligheten" (`apply_observed`, `drop_replaced`).
- `docs/templates/utfall.csv`, som bara har rubrikraden, och `docs/setup.md` 2h.
- Förslaget D-062 finns i `docs/proposals/2026-10-28-D-062-utfall-fran-verkligheten.md`.
- `tests/unit/test_results.py`: 7 tester.

## [Unreleased] — 2026-10-28 — PR 9: nattlig körning i GitHub Actions (D-061, föreslaget)
### Tillagt
- `.github/workflows/nightly.yml`:
  - Körs varje natt och med knappen "Run workflow".
  - Kör stegen kontroll av sim, tester, hälsokontroll och bedömning med skriptade agenter av `normal` och `platform_ban`.
  - Kör en valfri kort Groq-simulering. Den körs bara i huvudrepot med repository secret, och får misslyckas.
  - Laddar upp en artefakt och öppnar eller kommenterar ett ärende vid fel.
  - Jobbet har bara läsrätt.
- Förslaget D-061 finns i `docs/proposals/2026-10-28-D-061-nattlig-korning.md`.
- `tests/unit/test_nightly_workflow.py`: 5 tester av arbetsflödets säkerhetsregler.
### Rättat
- `simulate start --agents groq` utan `GROQ_API_KEY` skapade körningen innan felet upptäcktes, så datamappen kunde inte användas igen. Nu byggs gatewayn före start. Det testas i `test_cycle.py`.

## [Unreleased] — 2026-10-28 — PR 8: simulering med Groq-agenter (D-060, föreslaget)
### Tillagt
- `python -m aie simulate start|resume --agents groq`:
  - Använder bara leverantörer av typen `groq` ur `providers.toml`, utan reserv.
  - Förfrågningarna märks `public`, och det är tillåtet bara i sim med SIM.
  - Saknas `GROQ_API_KEY` vägrar kommandot att starta.
- `ProviderRouter.calls_left()` och `LLMGateway.calls_left()`.
- `WorkCycle` pausar före en dag som kvoten inte räcker till och loggar `simulation.paused_quota`. `resume` fortsätter senare.
- Bedömningar (`evaluate`, `assess`) vägrar `groq`.
- `docs/setup.md` 2g: så kör Yorgo detta själv med sin gratisnyckel.
- Förslaget D-060 finns i `docs/proposals/2026-10-28-D-060-groq-agenter.md`.
- `tests/unit/test_groq_agents.py`: 4 tester. Nätverket är mockat.

## [Unreleased] — 2026-10-28 — PR 7: skydd mot plattformsberoende och scenariot platform_ban (D-059, föreslaget) · kräver-oberoende-granskning
### Tillagt
- Nya gränser i `config/loader.py` och `RiskLimits`: `MAX_PLATFORM_REVENUE_SHARE` (procent) och `MIN_ACTIVE_PLATFORMS` (antal, ny typ). Värdena läggs i `risk_limits.toml` i PR 7b, som en grundare godkänner.
- `src/aie/registry/dependency.py` (`DependencyGuard`):
  - Plattformar med gemensamma beroenden räknas som en grupp.
  - Andelen av intäkterna räknas de senaste 90 dagarna.
  - Ger varning, rapport, och en spärr mot nya initiativ i en grupp på eller över gränsen. När det finns intäkter och en gräns saknas, stoppas nya initiativ (ER-02).
- `System.tick()` skriver `dependency.warning` i revisionsloggen.
- `python -m aie registry dependency`.
- Scenarier kan ha `[[platforms]]` med `dependencies`, och initiativ kan ha `platform`.
- Ny händelse `platform_ban`, och scenariot `config/scenarios/platform_ban.toml`, där plattform A stänger kontot dag 30.
- Förslaget D-059 finns i `docs/proposals/2026-10-28-D-059-plattformsberoende.md`.
- `tests/unit/test_dependency.py`: 10 tester.
### Ändrat
- `python -m aie registry` bygger registret med hela systemet, så att D-058 och D-059 gäller även där.
- `tests/fixtures/limits/risk_limits.toml` har fått de två föreslagna gränserna, så att testerna kör med gränserna satta. Saknade gränser testas separat.
## [Unreleased] — 2026-10-28 — Utvecklaragenten: sök/ersätt-block och starkare modell
### Ändrat
- Modellen svarar med sök/ersätt-block (`FILE:` + `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE`), samma metod som aider bygger på, i stället för unified diffs. `dev_agent/edits.py` kräver att varje SEARCH finns exakt en gång i en befintlig fil. Nya filer får bara skapas under `tests/`. Blocken görs om till en diff som `check_patch` granskar som förut. Vid fel skickas det exakta felet tillbaka i återkopplingsförsöket. Rött ⇒ filerna återställs.
- Prompten innehåller listan över de riktiga filerna under `src/aie/`, så att modellen inte hittar på sökvägar.
- `groq` kör nu `openai/gpt-oss-120b` och `groq-2` `openai/gpt-oss-20b` som reserv. Båda används bara om de finns i Groqs aktuella modellista. `groq-3` (`llama-3.3-70b-versatile`) är borttagen, eftersom Groq inte längre erbjuder den.
- Uppgifterna tas lättast först: dokumentation och lint, sedan små tester, sist buggar. Uppgifter som redan är frågor i `QUESTIONS-FOR-FOUNDERS.md` hoppas över.
- `extract_diff`, `repair_diff` och `git apply` används inte längre och är borttagna.

## [Unreleased] — 2026-10-28 — PR 6: simulera före start, hård spärr (D-058, föreslaget) · kräver-oberoende-granskning
### Tillagt
- Migration 31 `assessments` och `assessment_events`: bedömningar med exakt de parametrar de gäller (SHA-256), och ett beslut per bedömning.
- `src/aie/registry/assessments.py`:
  - `AssessmentStore`.
  - `check_active()`: automatisk paus och incident efter 14 dagar under den pessimistiska prognosen, kopplad till `System.tick()`.
- `src/aie/simulation/assessment.py`:
  - Scenarier byggs från registret: normalt, pessimistiskt (efterfrågan × 0,25, returer × 2) och noll försäljning, med flera körningar var.
  - Grundarnas tid och fasta avgifter räknas som kostnad. Antagandena märks, och en känslighetsanalys ingår.
- `python -m aie assess run|list|show|approve|reject`.
- **Spärr:** ett initiativ eller en plattform godkänns, aktiveras eller får utgifter bara med en godkänd och redo bedömning med samma parametrar. Ändras parametrarna går initiativet tillbaka till `reviewed`.
- `config/simulation.toml [assessment]`: antagandena, märkta som antaganden.
- Förslaget D-058 finns i `docs/proposals/2026-10-28-D-058-simulera-fore-start.md`.
- `tests/unit/test_assessment.py`: 6 tester. `test_registry.py` har fått 3 tester till, och registertesterna och `test_system.py` följer nu den nya ordningen.

## [Unreleased] — 2026-10-28 — PR 5: webbläsning för Research (D-057, föreslaget) · kräver-oberoende-granskning
### Tillagt
- `src/aie/research/web.py` (`WebReader`): läser kända offentliga sidor med `urllib` bakom `AuthorizationEngine`.
  - Bara GET, och bara värdar i `config/research.toml`.
  - SSRF-skydd även efter omdirigeringar, och `robots.txt` följs.
  - Dagskvot, storleksgräns, tidsgräns och bara textinnehåll.
  - Blockeras vid nödstopp och i skyddat läge.
- Migration 30 `web_fetches`: varje försök med URL, datum, utfall, SHA-256 och text, append-only. Innehållet är opålitlig data (`ExternalContent`, SR-06).
- `python -m aie research fetch|history`.
- `research/QUESTIONS.md`: R-11 om ett gratis sök-API. Inget är kopplat in.
- Förslaget D-057 finns i `docs/proposals/2026-10-28-D-057-webblasning.md`.
- `tests/unit/test_web.py`: 8 tester med ett låtsasnät, utan nätverksanrop.

## [Unreleased] — 2026-10-28 — PR 4: plattforms- och initiativregistret (D-056, föreslaget)
### Tillagt
- Migration 29 `registry_versions`: plattformar och initiativ som versionerad data, append-only.
- `src/aie/registry/`:
  - `Register`: statusflödet idé → undersökt → granskad → godkänd → aktiv, pausad eller avvecklad. Agenter går via "Utred möjlighet" (D-011), och bara grundare godkänner.
  - `spend_block_reason`: initiativspärren (D-054).
  - Import från `config/registry/*.toml`, och `python -m aie registry list|show|import|status`.
- `config/registry/platforms.toml`: Etsy, Gumroad och Fiverr från `docs/channels.md` med status `investigated`. Okända uppgifter är okända.
- `build_system` kopplar registret till budgetmotorn. Simuleringen registrerar scenariots initiativ i sin egen databas.
- Inga plattformsnamn i `src/`, även i exempeltexter, och ett test kontrollerar det.
- Förslaget D-056 finns i `docs/proposals/2026-10-28-D-056-register.md`.
- `tests/unit/test_registry.py`: 8 tester. `test_system.py` registrerar ett initiativ före utgiften.

## [Unreleased] — 2026-10-28 — F6: uppdelade köp per departement och dag, initiativspärr (D-054, föreslaget) · kräver-oberoende-granskning
### Tillagt
- `BudgetEngine._split_flags`: utöver D-028 (samma initiativ, sju dagar) flaggas utgifter i samma departement samma dag, i olika initiativ, som tillsammans passerar `HUMAN_APPROVAL_THRESHOLD`. Det går alltså inte längre att kringgå tröskeln med nya initiativnamn.
- `BudgetEngine(initiatives=)`: initiativspärren. Ett okänt eller icke godkänt initiativ ger nej, och ett register som inte svarar ger nej. Spärren aktiveras när initiativregistret (PR 4) kopplas in.
- Förslaget D-054 finns i `docs/proposals/2026-10-28-D-054-uppdelning-och-initiativ.md`.
- `tests/unit/test_split_department.py`: 6 tester. `test_budget.py` och `test_split.py` är anpassade till den nya regeln. Skälen står i förslaget, och inget krav har tagits bort.

## [Unreleased] — 2026-10-28 — F5: godkända utgifter kan genomföras, en gång (D-053, föreslaget) · kräver-oberoende-granskning
### Tillagt
- Migration 28 `spend_approvals` och `spend_approval_events`, append-only. Unika index ger högst ett beslut och högst en förbrukning per godkännande.
- `src/aie/budget/approvals.py` (`SpendApprovals`): förfrågan, godkännande och avslag av en grundare (D-049). Ett godkännande gäller i 7 dagar och för samma departement, initiativ och valuta, med högst det godkända beloppet.
- `BudgetEngine.check(..., approval_id=)`: godkännandet ersätter bara kravet på en grundare, och alla andra gränser gäller ändå. Vid ja förbrukas det atomiskt.
- `python -m aie spend list|approve|reject`.
- I simuleringen blir en utgift över tröskeln en förfrågan, och den genomförs dagen efter att en grundare har godkänt den.
- Förslaget D-053 finns i `docs/proposals/2026-10-28-D-053-godkanda-utgifter.md`.
- `tests/unit/test_spend_approvals.py`: 7 tester, varav ett med två samtidiga anslutningar.

## [Unreleased] — 2026-10-28 — F3+F4: betald skatt och skatteunderlag (D-052, föreslaget) · kräver-oberoende-granskning
### Tillagt
- Migration 27 `tax_payment`: ledgern får posttypen `tax_payment`. Tabellen byggs om i en transaktion, och alla poster, id:n, statusar och spärrar finns kvar. Den nya tabellen `tax_payments` kopplar en betalning till spår och år. Migration 27 var reserverad för 6b-4, som nu får migration 36 (TODO.md).
- `TaxEngine.pay()`, `liability_minor()`, `payments()` och `payments_by_track_year()`. Avsättningen per spår och år minskar med betald skatt och blir aldrig negativ, och kassan minskar exakt en gång.
- `basis = "revenue" | "profit"` i `tax.toml`. Standard är `revenue` tills Skatteverket har bekräftat skattebehandlingen.
- Departementens bas (D-051) räknar med hela skatteskulden, så en betalning ändrar inte basen.
- Förslaget D-052 finns i `docs/proposals/2026-10-28-D-052-skattebetalning.md`.
- `tests/unit/test_tax_payment.py`: 8 tester, varav ett uppgraderar en ledger från schemaversion 26.

## [Unreleased] — 2026-10-28 — F1+F2: riktiga budgettak per departement (D-051, föreslaget) · kräver-oberoende-granskning
### Rättat
- `BudgetEngine` i kapitalläget: taket räknas nu från en fast bas (insatt kapital − reserv + resultatdel). Förut räknades det från det kapital som var kvar, så upprepade utgifter kunde låta research använda 95 % av basen trots andelen 40 % (verifierat före rättelsen). Nu är det högst 40 %, och bufferten på 44 % skyddas.
- Resultatdelen är 80 % av vinsten efter skatt (`REINVESTMENT_POLICY`) och räknas före departementens egna utgifter, så att inget räknas två gånger. En förlust krymper basen fullt ut. Insatt kapital är `capital_in` minus `capital_out`.
- `BudgetEngine.capital_base()` och `department_cap()`.
- Förslaget D-051 finns i `docs/proposals/2026-10-28-D-051-budgettak.md`. `DECISIONS.md` är skyddad och uppdateras i en egen PR.
- `tests/unit/test_budget_cap.py`: 8 tester. Tre tester i `test_budget_capital.py` har fått de förväntade värden som den rättade formeln ger, med uträkningen i kommentarer.

## [Unreleased] — 2026-10-28 — Utvecklaragenten lagar modellernas hunk-huvuden
### Rättat
- Körning 4 nådde Groq utan 429, men varje diff stoppades av `git apply` med "No valid patches in input". Modellen skrev `@@` utan radnummer, vilket gick att återskapa lokalt. `repair_diff` bygger nu om varje hunk-huvud från raderna som följer och lagar tomma sammanhangsrader, och `git apply --recount` räknar om antalen. Innehållet i diffen ändras inte.
- Prompten kräver fullständiga hunk-huvuden och visar en exempeldiff. När en diff inte går att applicera visar felet nu diffens huvuden, både i loggen och i återkopplingen till modellen.

## [Unreleased] — 2026-10-28 — Utvecklaragenten: Groqs gränser per modell
### Ändrat
- `config/providers.toml`: två Groq-reservmodeller, `groq-2` (`openai/gpt-oss-120b`) och `groq-3` (`llama-3.3-70b-versatile`). Groqs gratisgränser gäller per modell, så vid 429 provas nästa Groq-modell direkt. Utvecklaragenten använder en Groq-modell bara om den finns i Groqs aktuella modellista (`GET /models`).
- Leverantören väntar inte längre själv vid 429. Svarar ingen riktig modell på grund av 429, väntar utvecklaragenten ut minuten en gång (60 s) och frågar igen.
- `TokenPacer` håller en körning under 6 000 tokens per rullande minut. Kontexten är högst 6 000 tecken och svaret högst 2 500 tokens. Återkopplingsanropet skickar bara 3 000 tecken kontext.
- Jobbloggen visar varför varje försök misslyckades, både första svaret och det slutliga.

## [Unreleased] — 2026-10-28 — Utvecklaragenten: bättre prompt, återkoppling och färre PR:er
### Ändrat
- Prompten anger paketet `aie` under `src/`, importstilen `from aie.x import Y`, hur tester körs och att svaret bara får vara en giltig unified diff med standardbiblioteket. Ett befintligt test skickas med som exempel.
- Avvisad diff, diff som inte går att applicera eller röda tester ger ett nytt försök, där modellen får exakt felet som återkoppling.
- Mindre prompter: av Markdown-filer skickas bara raderna med uppgiftens krav-ID:n, och kontexten är högst 8 000 tecken. Vid HTTP 429 väntar leverantören (`Retry-After`, högst 60 s) och försöker en gång till.
- `llm.provider_failed` loggar även leverantörens felkod. Körningen skriver ut varje misslyckat anrop, aldrig nyckel eller prompt.
- En körning utan ändring och utan nya grundarfrågor öppnar ingen PR. Rapporten sparas med `actions/cache` och committas i nästa PR som ändrar kod; den syns också i Actions-sammanfattningen.

## [Unreleased] — 2026-10-28 — Utvecklaragenten når Groq
### Rättat
- Första körningen nådde aldrig Groq och visade inte varför; bara `rule` svarade. Externa anrop skickar nu en egen `User-Agent` (urllibs standard kan spärras med 403), gpt-oss får `reasoning_effort = "low"`, och agentens anrop är mindre (kontext 10 000 tecken, `max_tokens` 3000) så att det ryms i gratisgränsen per minut.
- Ett misslyckat anrop loggas nu som `llm.provider_failed` med HTTP-status och felkod, även när en reserv svarar. Svarskroppen i övrigt och nyckeln loggas aldrig.
- `dev-agent run` skriver vilka leverantörer som är på (bara namn), första Groq-statusen och vem som svarade, både i loggen och i rapporten.
- `dev-agent open-pr` misslyckas inte längre när automatisk merge inte går att slå på. PR:en finns då ändå, och en varning skrivs ut.

## [Unreleased] — 2026-10-28 — Utvecklaragenten (D-050)
### Tillagt
- Rollen `developer` och verktyget `dev.propose_patch` i `config/permissions.toml` (skyddad fil; `founder-approved` på Robins begäran). Prestationsprofil för rollen (aldrig mätt på intäkt).
- `src/aie/dev_agent/`: `python -m aie dev-agent run|open-pr`. Väljer en uppgift (backlogg, fallerande test, ruff, krav utan test), frågar en gratismodell via `LLMGateway`, granskar diffen (skyddade filer, `.github/`, `config/`, egen kod, högst 200 rader, bara standardbiblioteket, inga försvagade tester), applicerar, kör hela sviten utan nycklar, backar vid rött, högst 3 försök. Kvot slut ⇒ stannar lugnt. Allt revideras; rapport i `docs/bot-reports/`, frågor efter 3 misslyckanden.
- `.github/workflows/dev-agent.yml`: var tredje timme och manuellt; PR med `BOT_TOKEN` och automatisk merge när alla obligatoriska checkar är gröna.
- D-050. `tests/unit/test_dev_agent.py`: 12 tester med fejkad modell och fejkad GitHub.

## [Unreleased] — 2026-10-28 — D-049: grundarna agerar som en
### Ändrat
- **D-049** (godkänt av Robin, gäller för båda): en grundares godkännande räcker överallt. D-019 punkt 2 och 3 är ersatta.
- Koden följer: godkännandekön kräver alltid 1 grundare (även styrändringar); en grundare beslutar direkt över `HUMAN_APPROVAL_THRESHOLD` i beslutsloggen och tvister; budgetmotorn anger 1 grundare (även vid uppdelade köp); nödstopp, stop-loss, momsgränsen, operativa regler och avveckling avgörs av en grundares röst.
- 26 tester uppdaterade till den nya regeln. Agenter beslutar fortfarande aldrig över gränsen, och hårda gränser kan fortfarande inte godkännas bort.
- `docs/BOT.md`: anspråk finns bara för att undvika dubbelarbete. Ett anspråk utan commit på 6 timmar är inaktuellt och får tas över från befintlig gren, även Fas 6b-3–6b-5. Boten sätter fortfarande aldrig `founder-approved`.
## [Unreleased] — 2026-10-28 — Nattboten har alltid arbete
### Ändrat
- `docs/BOT.md` (skyddad fil, ändrad på Robins uttryckliga begäran): när det inte finns någon ledig uppgift i aktuell fas arbetar boten med `docs/BOT-BACKLOG.md` i prioritetsordning (buggar, kravtäckning, säkerhet, kodkvalitet, dokumentation, förslag till nästa fas). Inga nya funktioner utanför konstitutionen och ROADMAP; idéer blir förslag till grundarna. Minst 3 nya backlogpunkter per körning.
### Tillagt
- `docs/BOT-BACKLOG.md` med fem första punkter (BL-001–BL-005), uppmätta 2026-10-28. `docs/proposals/` för designförslag (bara text).

## [Unreleased] — 2026-10-28 — Skyddade filer och nattboten
### Tillagt
- `.github/workflows/protected-files.yml`: checken `protected-files` fäller en PR som ändrar eller tar bort `CONSTITUTION.md`, `DECISIONS.md`, `config/risk_limits.toml`, `config/permissions.toml`, själva workflow-filen eller `docs/BOT.md`, om PR:en inte har etiketten `founder-approved`. Bara grundarna sätter etiketten.
- `docs/BOT.md`: nattbotens regler (vilken uppgift, anspråk, bygga, merge, problem, grundarfrågor, aldrig, rapport).
- `docs/QUESTIONS-FOR-FOUNDERS.md` (mall) och `docs/bot-reports/`.

## [Unreleased] — 2026-10-27 — Värden för 500 kr och kapitalbudget (D-047), godkända av båda grundarna
### Ändrat
- `config/risk_limits.toml` för ett simulerat startkapital på 500 kr:

  | Gräns | Värde |
  |---|---|
  | `START_CAPITAL` | 50 000 (500 kr) |
  | `MINIMUM_RESERVE` | 10 000 (100 kr) |
  | `MAX_SINGLE_EXPERIMENT_LOSS` | 5 000 |
  | `MAX_DEPARTMENT_BUDGET` | 20 000 |
  | `MAX_SINGLE_TRANSACTION` | 5 000 |
  | `MAX_COMMITTED_CAPITAL` | 15 000 |
  | `MAX_ALLOWED_UNVERIFIED_SPEND` | 1 000 |
  | `HUMAN_APPROVAL_THRESHOLD` | 2 500 (25 kr) |
  | `REINVESTMENT_POLICY` | 80 % |
  | `MAX_TOTAL_DRAWDOWN` | 20 % (oförändrad) |

- `config/budgets.toml` använder `mode = "capital"`. Andelarna av det disponibla kapitalet är: research 40 %, executive 5 %, finance 5 %, risk, compliance och audit 2 % vardera, och 44 % buffert.
- Testerna använder en låst kopia av de tidigare värdena (`tests/fixtures/limits/`, `fixture_config.py`), så att grundarnas värden kan ändras utan att testerna går sönder. Två tester kontrollerar repots egna filer.
- Provat på riktigt med `simulate evaluate`:
  - `normal` gav 5 × 90 dagar med vinst i alla körningar, även de sista 30 dagarna, och en marginal runt 40 %. Resultatet var "redo för 500 kr" med grundarnas godkännande.
  - `loss` blev "inte redo". En av fem körningar stoppade hela företaget och föll 22,8 %.
- Hela sviten ger 562 OK.

## [Unreleased] — 2026-10-27 — Kapitalbaserade budgetar och bedömning av lönsamhet (D-047, D-048)
### Tillagt
- `budgets.toml` `mode = "capital"` (D-047): andel av det disponibla kapitalet i stället för fast budget, utan period. Plattformsavgifter räknas inte mot departementet, och stop-loss mäter inte departementsbudgeten i det läget. `fixed` är fortfarande standard.
- `BudgetEngine.usage()` ger vad som återstår, i båda lägena.
- `src/aie/simulation/readiness.py` och `python -m aie simulate evaluate` (D-048): många oberoende körningar bedöms mot `config/simulation.toml`. Resultatet är en rekommendation, aldrig en handling, och rapporten har SHA-256.
- Scenarierna har realistiska avgifter: Etsy 10,5 % + 5,70 kr per order, Gumroad 10 % + 5,50 kr, Fiverr 20 % (D-010, simulerat).
- D-047 och D-048 (föreslagna).
- `tests/unit/test_budget_capital.py` (7) och `tests/unit/test_readiness.py` (7). Hela sviten ger 561 OK på Windows 11, Python 3.12.0.
- Provat på riktigt: `simulate evaluate --scenario normal` med nuvarande fasta budget gav 5 × 90 dagar och svaret "inte redo". Plattformsavgifterna förbrukade research-budgeten, och stop-loss stoppade departementet, så de sista 30 dagarna gav 0. Det är precis det D-047 åtgärdar.

## [Unreleased] — 2026-10-27 — Fas 6b-2: åtgärdsprotokoll, arbetscykel och `python -m aie simulate`
### Tillagt
- `src/aie/simulation/`:
  - `actions.py`: åtgärdsprotokollet och kontrollen av de 11 fälten i §12 (FR-23).
  - `agents.py`: organisationen, `ScriptedPolicy` och `build_gateway`.
  - `cycle.py`: `WorkCycle`, där en dag följer §20 och varje åtgärd går genom spärrarna.
  - `cli.py`: kommandot `python -m aie simulate start|resume|status`.
- `Simulation.begin_day` och `finish_day`, så att agenterna agerar mellan dagens händelser och marknaden. Initiativ som inte är listade säljer inte.
- `BudgetEngine.usage()`, `System.budgets`.
- `config/permissions.toml`: `sim.spend`, `sales.list`, `forecast.make` och `proposal.submit` (D-044, **behörighetsändring**).
- D-043 och D-044 (föreslagna).
- `tests/unit/test_cycle.py`: 15 tester. Hela sviten ger 547 OK på Windows 11, Python 3.12.0.
- Provat på riktigt:
  - `simulate start --scenario budget_overrun --days 4`, och sedan `resume --days 6` i en ny process. Budgetförsöken dag 3 och 8 nekades, och revisionsloggen var OK.
  - `--agents local` utan Ollama: agenternas tur blev tom och nekandet noterades. Inget skickades ut.

## [Unreleased] — 2026-10-26 — Fas 6b-1: simulerat startkapital, marknad och scenarier (FR-20)
### Tillagt
- Migration 26 `simulation_runs` och `simulation_days`, append-only.
- `src/aie/simulation/`:
  - `SimClock`: simulerad affärstid.
  - `Market`: seedad, deterministisk marknad med heltalsbelopp.
  - `load_scenario` och `parse_scenario`: validering av scenarier.
  - `Simulation.start`, `resume`, `advance` och `run`: startkapital, order som ledgerposter, skattespår, pauser från spärrarna, omstart.
- `config/scenarios/`: normal, loss, budget_overrun, conflict, vat, intrusion och kill.
- `build_system(clock=)`. I sim får `system:simulation` skriva i ledgern och märka skattespår. `TaxEngine(components=)`.
- D-042 (föreslaget).
- `tests/unit/test_simulation.py`: 13 tester. Hela sviten ger 532 OK på Windows 11, Python 3.12.0.
- Provat på riktigt: process 1 startar `normal` och kör dag 1–3, process 2 återupptar och kör dag 4–5. Det gav 34 poster utan dubbletter, och `aie status` visar revisionsloggen OK med schemaversion 26.

## [Unreleased] — 2026-10-26 — Fas 6a: hela systemet kopplat i `python -m aie start`
### Tillagt
- `src/aie/system.py`: `build_system()` och `System.tick()`. Alla spärrar, Tax Engine och Fas 5-komponenterna kopplas ihop på ett ställe.
- `runtime.start` bygger systemet och kör `tick()` i varje varv. Utan konfigurationen för spärrarna startar systemet inte.
- D-041 (föreslaget).
- `tests/unit/test_system.py`: 7 tester. `tests/unit/test_runtime.py` kopierar nu `permissions.toml`, `budgets.toml` och `tax.toml` och sätter grundarna.
- Hela sviten ger 519 OK på Windows 11, Python 3.12.0.
- Provat på riktigt: `python -m aie start`, `status` och `stop` med repots konfiguration. Schemaversion 25, alla elva komponenter står i `system.start` och avslutet var rent.

## [Unreleased] — 2026-10-26 — Fas 5f: SR-17, Fas 5 stängd
### Tillagt
- Migration 25 `removal_cases` och `removal_events`, append-only.
- `src/aie/evaluation/removal.py`: `RemovalReview` med `open`, `respond`, `vote`, `dismiss` och spärren `transition_block_reason`.
  - Ett ärende kräver kriterier ur §33 med kontrollerat underlag. Slutsatser är aldrig underlag.
  - Avstängning beslutas av en grundare, och avveckling av båda.
- `AgentRegistry.set_guard()`: när spärren är kopplad kan avstängning och avveckling av en verksam agent bara ske genom ett beslutat ärende.
- D-040 (föreslaget).
- `tests/unit/test_removal.py`: 7 tester.
- `tests/acceptance/test_fas5.py`: 6 acceptanstester för §53 och SR-17.
- Hela sviten ger 512 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 5e: versionerade strategier (FR-18)
### Tillagt
- Migration 24 `strategy_versions`, append-only.
- `src/aie/evaluation/strategies.py`: `StrategyRegistry` med `save`, `restore`, `active`, `get`, `history`, `names` och `diff`. Den hanterar både strategier och agentversioner.
  - En återställning är en ny version.
  - Obligatoriska ändringar kräver godkända operativa regler (FR-17) och en grundare.
- D-039 (föreslaget).
- `tests/unit/test_strategies.py`: 5 tester. Hela sviten ger 499 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 5d: lärdomsregister (FR-17)
### Tillagt
- Migration 23 `lessons` och `lesson_events`, append-only.
- `src/aie/evaluation/lessons.py`: `LessonRegistry` med `propose`, `from_incident`, `add_evidence`, `promote`, `vote_rule`, `demote`, `reject`, `rules` och `require_rule`.
  - De fem statusarna och sju orsakstyperna i §29 finns.
  - Statusen går ett steg i taget. Test krävs för att lärdomen ska räknas som testad, och två test för reproducerbar. En regel kräver båda grundarna.
- D-038 (föreslaget).
- `tests/unit/test_lessons.py`: 6 tester. Hela sviten ger 494 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 4f: Tax Engine (ER-18–21), Fas 4 stängd
### Tillagt
- Migration 21 `tax_assignments` och 22 `tax_events`, append-only. De är Robins nummer och användes av Yorgo vid överlämningen.
- `config/tax.toml` med simulerade, försiktiga satser per spår, momsgränsen och fördelningen mellan grundarna i spår C.
- `src/aie/tax/`:
  - `TaxEngine.assign`: skattespår per intäkt (ER-18).
  - `position` och `reserved_minor`: reserverad skatt (ER-19).
  - `vat_status`, `check_vat`, `vat_vote` och spärren `tool_block_reason`: momsgränsen (ER-20).
  - `export`: deklarationsunderlag per grundare med SHA-256 (ER-21).
- `capital_position(tax_reserved_minor=)` och `BudgetEngine(tax=)`. Reserverad skatt räknas som åtagande, och återinvesterbar vinst räknas efter skatt.
- `config/permissions.toml`: verktyget `tax.assign` för CFO.
- D-032–D-034 (föreslagna).
- `tests/unit/test_tax.py`: 8 tester.
- `tests/acceptance/test_fas4.py`: 7 acceptanstester för §52 och ROADMAP:s nyckeltester.
- Hela sviten ger 488 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — godkännanden av D-025, D-027–D-031 och D-035–D-037
### Ändrat
- DECISIONS.md: Robin har godkänt D-025, D-027, D-028 och D-029–D-031. Yorgo och Robin har gemensamt godkänt D-035–D-037. Alla nio har nu status Godkänd. Bara fälten *Status* och *Godkänd av* är ändrade.
- PROJECT_STATUS och ROADMAP: Fas 3 är stängd, och godkännandena är borttagna från nästa åtgärder.

## [Unreleased] — 2026-10-26 — Fas 5c: prestationsmätning per roll (FR-19)
### Tillagt
- Migration 20 `performance_reviews`, append-only. Den var reserverad som 22 och är omnumrerad (TODO.md).
- `src/aie/evaluation/performance.py`: `PerformanceReview.scorecard`, `review` och `reviews`, med rollprofiler (`PROFILES`) för alla sju roller.
  - Måtten är måluppfyllelse, prognosprecision med trend, ekonomiskt bidrag (bara CEO och departementschefer), regelefterlevnad, felhantering, riskidentifiering och verifierade incidenter.
  - Den som rapporterar fel krediteras. Bara verifierade incidenter räknas mot de involverade. Nekanden från stopp räknas inte.
  - Det finns ingen totalpoäng, och bedömningen ändrar aldrig agentens tillstånd.
- D-037 (föreslaget).
- `tests/unit/test_performance.py`: 10 tester. Hela sviten ger 473 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 5b: prognoslogg och prognos mot utfall (FR-16)
### Tillagt
- Migration 19 `forecasts` och `forecast_outcomes`, append-only. Den var reserverad som 21 och är omnumrerad (TODO.md).
- `src/aie/evaluation/forecasts.py`: `ForecastLog.make`, `revise`, `record_outcome`, `evaluate`, `compare`, `overdue` och `accuracy`.
  - Utfall för `net`, `revenue` och `costs` hämtas automatiskt från ledgerns initiativ, men aldrig från ett preliminärt resultat (ER-11).
  - En revidering är en ny prognos. Den ursprungliga jämförs också (§20 steg 10).
  - Den som gjorde prognosen rapporterar inte själv utfallet.
- D-036 (föreslaget).
- `tests/unit/test_forecasts.py`: 9 tester. Hela sviten ger 463 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 5a: incidentrapporter (FR-15)
### Tillagt
- Migration 18 `incidents` och `incident_entries`, append-only. Den var reserverad som 20 men numrerades om eftersom Tax Engine inte var påbörjad. Robin får 21–22 (TODO.md).
- `src/aie/evaluation/incidents.py`: `IncidentLog` med de 16 fälten i §28.
  - Ifyllda fält ändras bara genom rättelseposter med motivering.
  - Verifieringen (fält 16) görs sist och inte av den som ansvarar för uppföljningen.
  - Rapportören räknas inte som involverad (§31, §33).
- `StopLoss`, `KillSwitch` och `ProtectedMode` tar `incidents=`. Varje utlöst stopp blir då automatiskt en incident. `IncidentLog.sync()` hittar stopp som skett utan koppling.
- D-035 (föreslaget).
- `tests/unit/test_incidents.py`: 11 tester. Hela sviten ger 454 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Yorgo godkänner D-029–D-031
### Ändrat
- DECISIONS.md: Yorgo har godkänt D-029 (stop-loss), D-030 (nödstopp) och D-031 (skyddat driftläge). Alla tre väntar på Robin och har därför status Föreslagen. Bara fältet *Godkänd av* är ändrat.

## [Unreleased] — 2026-10-26 — Fas 4e-3: skyddat driftläge (SR-08)
### Tillagt
- Migration 17 `operating_mode_events`, append-only.
- `src/aie/risk/protected.py`: `ProtectedMode.assess`, `update`, `report_incident` och `exit`.
  - Bedömningen kontrollerar de sju villkoren i §59: reserven nära, behörighetskontrollen, revisionsloggen och ledgerns siffror (ER-16), obehöriga poster, incidenter, saknade kontrollfunktioner och kontroller som inte kan genomföras.
  - Läget aktiveras automatiskt före varje utgift. Bruten bokföring aktiverar dessutom nödstoppet.
  - Utgifter och externa verktyg blockeras, medan analys och dokumentation fortsätter.
  - En grundare lämnar läget när skälen är borta, och obehöriga poster kan kvitteras.
- `AuthorizationEngine.add_gate()`.
- D-031 (föreslaget).
- `tests/unit/test_protected_mode.py`: 15 tester. Hela sviten ger 443 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 4e-2: nödstopp (SR-07)
### Tillagt
- Migration 16 `kill_switch_events`, append-only.
- `src/aie/risk/killswitch.py`: `KillSwitch.engage`, `vote_release` och `state`.
  - Spärrarna `tool_block_reason`, för `AuthorizationEngine(..., gates=...)`, och `spend_block_reasons`, för `BudgetEngine`.
  - Under nödstopp är bara läsa, rapportera, verifiera, riskbedöma och stoppa tillåtet, och inga utgifter görs. Inget raderas.
  - Återstart kräver två olika grundare och en intakt revisionslogg.
- `python -m aie kill status|engage|release --as <grundare> --reason ...`.
- `docs/operations.md`: den dokumenterade processen för nödstopp, stop-loss och återstart (§26, §38).
- `AgentWorker` blockerar uppgiften med skälet om modellanropet nekas, till exempel under nödstopp, i stället för att krascha.
- D-030 (föreslaget).
- `tests/unit/test_killswitch.py`: 10 tester, bland annat CLI:t i en egen process. Hela sviten ger 428 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Fas 4e-1: stop-loss (ER-13)
### Tillagt
- Migration 15: `stop_loss_trips` och `stop_loss_votes`. Båda är append-only.
- `src/aie/risk/stoploss.py`: `StopLoss`.
  - `breaches()` mäter förlust per initiativ, total drawdown, departementsbudget och reserv från ledgern. En saknad gräns räknas som nådd.
  - `evaluate()` sparar utlösningar med exponering, förpliktelser och vilka som informerats, och loggar dem i revisionsloggen.
  - `approve_resume()` kräver plan, åtgärdat läge och två olika grundare.
- `BudgetEngine(..., gates=...)`: spärrar som blockerar nya åtaganden. Stop-lossen är den första. Kan en spärr inte avgöra blir svaret nej.
- D-029 (föreslaget).
- `tests/unit/test_stoploss.py`: 12 tester. Hela sviten ger 418 OK på Windows 11, Python 3.12.0.

## [Unreleased] — 2026-10-26 — Yorgo godkänner D-020–D-028
### Ändrat
- DECISIONS.md: Yorgo har godkänt D-020–D-028 (2026-10-26). D-020–D-024 och D-026 har nu godkänts av båda och har status Godkänd. D-025, D-027 och D-028 väntar på Robin. Bara fälten *Status* och *Godkänd av* är ändrade.

## [Unreleased] — 2026-10-26 — Fas 3i: Utred möjlighet (FR-25)
### Tillagt
- Migration 14: `opportunities` och `opportunity_steps`. Bara stage och status får ändras, ett avslutat ärende ändras aldrig och stegen är append-only.
- `src/aie/collaboration/opportunities.py`: `OpportunityRegister` med `open`, `submit_findings`, `compliance_review`, `cfo_estimate`, `founder_decision` och `waiting_for`.
  - Fast ordning: Research → Compliance → CFO → grundare (D-011).
  - Compliance `uncertain` skickar ärendet tillbaka till Research (§17).
  - Fynd är obekräftade hypoteser (§29).
  - En skattefråga godkänns bara med underlag från Skatteverket eller en rådgivare.
  - Allt loggas i revisionsloggen.
- D-025 (föreslaget).
- `tests/unit/test_opportunities.py`: 11 tester. Hela sviten ger 406 OK på Windows 11, Python 3.12.0 (2 SIGINT-tester överhoppade).
### Ändrat
- Migrationsnummer 14 i stället för 12, enligt fördelningen i `TODO.md`. Robins godkännandekö tog 12 och ledgern 13.

## [Unreleased] — 2026-10-25 — Fas 4d: uppdelningsdetektering
### Tillagt
- Budgetmotorn flaggar möjliga uppdelade köp (ER-04, §5, D-028): utgifter i samma initiativ inom sju dagar, som inte behövde godkännande, och som tillsammans med den nya passerar `HUMAN_APPROVAL_THRESHOLD` eller `MAX_SINGLE_TRANSACTION`. En flaggad utgift kräver båda grundarna. Flaggan står i `BudgetCheck.flags` och i revisionsloggen.
- D-028 (föreslagen). `tests/unit/test_split.py`: 5 tester, bland annat ROADMAP Fas 4-nyckeltestet "10 köp à 99 under gräns 100 i samma initiativ → flaggas".
### Ändrat
- `tests/unit/test_budget.py`: varje testpost får ett eget initiativ, så att budgettesterna inte ser ut som uppdelade köp.

## [Unreleased] — 2026-10-25 — Fas 4c: skyddad reserv och kapitalbegrepp
### Tillagt
- `src/aie/budget/capital.py`: `capital_position()` räknar §23:s sju begrepp från ledgern (likvida, bundet, totalt, reserv, åtaget, disponibelt, återinvesterbart). Väntade inbetalningar räknas aldrig (ER-11); återinvesterbar vinst är 0 tills Tax Engine finns.
- Budgetmotorn blockerar varje utgift som är större än det disponibla kapitalet (likvida − `MINIMUM_RESERVE` − åtaget), så att den skyddade reserven aldrig används (§5, ER-05). Saknas `MINIMUM_RESERVE` blockeras allt (ER-02).
- D-027 (föreslagen). `tests/unit/test_capital.py`: 10 tester.
### Ändrat
- `tests/unit/test_budget.py`: startkapitalet sätts in som en `capital_in`-post, eftersom kapital bara räknas från ledgern.
## [Unreleased] — 2026-10-25 — Robin godkänner D-020–D-024 och D-026
### Ändrat
- `DECISIONS.md`: Robin ☑ på D-020, D-021, D-022, D-023, D-024 och D-026 (bara fältet *Godkänd av*). Yorgos godkännande saknas; besluten är fortfarande `Föreslagen` tills båda har godkänt. D-026 ändrar gränser och kräver båda enligt D-019 punkt 3.
- D-023 hade tappat fältet *Godkänd av* vid en merge; fältet är återställt. Beslutstexten är oförändrad.

## [Unreleased] — 2026-10-25 — Fas 4b: budgetmotor och kontroll före transaktion
### Tillagt
- `config/budgets.toml` (D-026, föreslagen): budget, maxåtagande, riskutrymme och användningsområde per departement (ER-17). Laddaren avvisar okända departement, budgetar över `MAX_DEPARTMENT_BUDGET`, maxåtagande över budgeten, `critical` som riskutrymme och budgetar som tillsammans äter av den skyddade reserven.
- `src/aie/budget/`: `BudgetEngine.check()` och `require()` före varje ekonomisk handling (ER-03). De blockerar överskriden budget (§52), departementets maxåtagande, `MAX_COMMITTED_CAPITAL`, `MAX_SINGLE_TRANSACTION`, riskklass över utrymmet eller `critical`, saknade gränser (ER-02) och `API_SPEND` (ER-22). Över `HUMAN_APPROVAL_THRESHOLD` krävs båda grundarna. Varje kontroll revideras.
- `tests/unit/test_budget.py`: 13 tester, bland annat ROADMAP Fas 4-nyckeltestet "budgetöverskridande blockeras".

## [Unreleased] — 2026-10-25 — Fas 4a: ledger
### Tillagt
- Migration 13: `ledger_entries` (§40:s tolv fält, unik idempotensnyckel och unikt externt ID) och `ledger_status` (statushändelser). Allt är append-only; status går bara från `pending` till `settled`, `failed` eller `cancelled`.
- `src/aie/ledger/`: `Ledger.record()`, `set_status()`, `correct()` (korrigeringsposter, ER-08), `entries()`, `corrections()`. Heltal med valuta (ER-01); bara `SIM` i sim och aldrig `SIM` i prod (ER-15); idempotens och dubblettskydd (ER-07, SR-12); godkännande över `HUMAN_APPROVAL_THRESHOLD` måste anges (ER-14); underlag krävs; hemligheter avvisas. Allt revideras.
- `compute_result()` och `result_for()`: nettovinst bara från genomförda poster, preliminär när något väntar eller kostnader saknas (ER-09, ER-11). `recompute()`: Audit räknar om med SQL direkt mot tabellerna och får avvikelserna (ER-16).
- D-024 (föreslagen). `tests/unit/test_ledger.py`: 22 tester.
### Ändrat
- Migrationsnummer: ledgern tog 13 och Yorgos FR-25 (#32) får 14 (se `TODO.md`).

## [Unreleased] — 2026-10-25 — Fas 3-acceptans (§51)
### Tillagt
- `tests/acceptance/test_fas3.py`: 12 tester, minst ett per kriterium i §51, och båda nyckeltesten i ROADMAP Fas 3. Kedjan byggs som `python -m aie approvals` bygger den (`aie.governance.cli.build`) med de riktiga konfigurationsfilerna. Testet hittade att en ägare inte kunde lämna sin egen uppgift vidare nedåt; rättat i PR #36.

## [Unreleased] — 2026-10-25 — Fas 3k: tilldelning nedåt i befälskedjan
### Ändrat
- `TaskBoard.assign` (Yorgos FR-07): en agent får bara tilldela nedåt i sin egen befälskedja (§8, D-020, D-023). Gäller både den nya och, vid byte, den gamla ägaren. CEO kan inte styra kontrollfunktionerna; grundarna får tilldela vem som helst. Före ändringen kunde Research-chefen ge uppgifter till CFO och till CEO.
- `tests/unit/test_tasks.py`: agenterna får en riktig befälskedja (CEO → Research-chef → forskare).
### Tillagt
- `tests/unit/test_delegation.py`: 8 tester. D-023 (föreslagen).
## [Unreleased] — 2026-10-25 — Fas 3j: `manual`-provider
### Tillagt
- `src/aie/llm/manual.py`: `ManualProvider` och `ManualInbox`. Förfrågan läggs i `<data_dir>/manual/<miljö>/` och providern kastar `ManualPending`. När en grundare har svarat returneras svaret nästa gång samma förfrågan görs. Inget nätverk, bara `public`-data (DR-13), dagsgränser som andra leverantörer (ER-02). Svar med hemligheter, tomma svar, för långa svar och dubbla svar avvisas.
- `kind = "manual"` i `config/providers.toml` (bortkommenterad som standard) och `load_providers(..., manual_dir=...)`.
- `python -m aie manual list|show|answer <id> --as <grundare> --file <fil|->`. Bara grundare (D-021); `manual.answered` och `manual.denied` revideras utan texten.
- D-022 (föreslagen).
- `tests/unit/test_manual.py`: 11 tester.

## [Unreleased] — 2026-10-23 — Fas 3: eskalering till grundarna och godkännandekö
### Tillagt
- Migration 12: `approval_requests` och `approval_votes`. Förfrågningar raderas aldrig, en avgjord förfrågan ändras aldrig och rösterna är append-only.
- `ApprovalQueue` (`src/aie/governance/escalation.py`): `submit_decision()` registrerar beslutet direkt när det är inom mandat och gräns, annars hamnar det i kön (över `HUMAN_APPROVAL_THRESHOLD` eller utanför agentens mandat). `submit_dispute()` tar en tvist som är eskalerad till grundarna, och `submit_governance()` en ändring i konstitution, gränser eller mandat. Kön räknar ut 1 eller 2 grundare enligt D-019.
- `approve()` och `reject()`: bara grundare, en röst var, ett nej med motivering avslår. Ett godkänt beslut skrivs i beslutsloggen med grundarna som beslutsfattare. En tvist över en hård gräns kan aldrig godkännas, bara avslås.
- `python -m aie approvals list|approve|reject [id] --as <grundare> --note "..."` visar och avgör kön. Allt revideras.
- `config/system.toml`: `founders = ["robin", "yorgo"]` (D-021).
- `tests/unit/test_escalation.py`: 16 tester, bland annat att allt fungerar när alla kvoter är slut och att styrningskoden aldrig importerar en modellklient.
## [Unreleased] — 2026-10-23 — Fas 3h: juridisk konflikt ⇒ stopp och Compliance (SR-16)
### Tillagt
- Migration 11 `legal_holds`. Högst en aktiv hållning per uppgift. En hållning raderas aldrig, kan inte ändras och släpps bara en gång.
- `src/aie/orchestration/legal.py`: `LegalDesk.raise_conflict`.
  - Alla som får agera, även arbetsagenter, och grundarna kan flagga med spårbart underlag.
  - Flaggningen öppnar ett samråd med CRO och Compliance (`ConsultationBoard.open_for_legal_review`), sparar hållningen och blockerar uppgiften.
- `LegalDesk.release` kan bara göras av Compliance eller en grundare.
  - `cleared` kräver att samrådet är klart och att Compliance inte har invänt. Inte ens en grundare kan släppa förbi en invändning (§6).
  - `cancelled` avbryter uppgiften.
- `TaskBoard` läser hållningen direkt ur databasen och vägrar `start`, `assign`, `block` och `complete` medan den är aktiv, oavsett anropare.
- `tests/unit/test_legal.py`: 9 tester.

## [Unreleased] — 2026-10-23 — Fas 3g: externt innehåll är opålitlig data (SR-06)
### Tillagt
- `src/aie/security/external.py`:
  - `ExternalContent(source, content)` kräver källan `url:` eller `file:`.
  - `render()` ramar in innehållet som data. Markörerna tas bort ur innehållet, så att det inte kan bryta sig ut ur ramen, och mycket lång text kortas.
  - `injection_signals()` hittar typiska styrförsök på svenska och engelska: ignorera instruktioner, rollbyte, falsk systemröst, påstådd behörighet, `governance.*`, hemligheter, pengar och ramförsök.
- `AgentWorker.work_on(..., external=(...))`:
  - Extern data läggs inramad i prompten, och systemprompten säger att den aldrig ska följas.
  - Misstänkta signaler loggas som `external.injection_suspected` utan innehållet och syns i rapporten som en iakttagelse med källan som underlag.
  - Behörigheter avgörs fortfarande bara av registret, mandaten och stoppen.
- `tests/unit/test_external.py`: 7 tester, bland annat en manipulerad webbsida från början till slut där modellen själv lyder attacken utan att något händer.

## [Unreleased] — 2026-10-23 — Fas 3: oenighet
### Tillagt
- Migration 10: `disputes`, `dispute_positions` och `dispute_events`. Ståndpunkter och händelser är append-only; en avgjord tvist kan inte ändras.
- `DisputeBoard` (`src/aie/governance/disputes.py`): `open()` kräver minst två ståndpunkter från olika agenter (ingen falsk konsensus), med påstående, underlag och konflikttyp `goal`/`data`/`risk`/`method` (§21). `request_analysis()`, `resolve()` och `escalate()` revideras.
- Hårda gränser (§21): ett förslag över `MAX_SINGLE_TRANSACTION`, `MAX_DEPARTMENT_BUDGET` eller `MAX_SINGLE_EXPERIMENT_LOSS`, med en saknad gräns, eller med riskklass `critical` kan aldrig godtas via `resolve()`, oavsett röster och oavsett vem som avgör. Tvisten eskaleras då till grundarna. Över `HUMAN_APPROVAL_THRESHOLD` krävs grundarna (D-019).
- Rätt nivå: CEO om CEO inte är part och förslaget är inom gränserna, annars grundarna. En eskalering går aldrig nedåt.
- `config/permissions.toml`: verktyget `dispute.resolve` för CEO.
- `tests/unit/test_disputes.py`: 16 tester, bland annat ROADMAP:s nyckeltest (CFO och CRO oense → eskaleras med dokumenterad tvist).

## [Unreleased] — 2026-10-23 — Fas 3: beslutslogg
### Tillagt
- Migration 9 `decisions`: ett beslut per rad med de åtta fälten i §20 steg 7 (vald åtgärd, motivering, underlag, budget, riskklass, förväntat resultat, villkor för avbrytande, uppföljning). Varje beslut pekar på en uppgift. Append-only; ett nytt beslut kan ersätta ett gammalt (`supersedes`).
- `src/aie/governance/`: `DecisionLog.record()`, `for_task()`, `trace()` (uppgift, uppgiftshistorik och alla beslut om uppgiften, §51). Varje beslut revideras som `decision.recorded`.
- Befogenheter kontrolleras av kod: agenter behöver `decision.record` och får bara besluta om egna uppgifter. Över `HUMAN_APPROVAL_THRESHOLD` kastas `NeedsApproval` för agenter och för en ensam grundare (D-019). Fritext med hemligheter avvisas.
- `config/permissions.toml`: verktyget `decision.record` för CEO, CFO, CRO och Research-chefen.
- `tests/unit/test_decisions.py`: 12 tester. Totalt 231.

## [Unreleased] — 2026-10-23 — Fas 3c: samråd (FR-11)
### Tillagt
- Migration 8: `consultations` och `consultation_opinions`. Samråd ändras aldrig. Yttranden är append-only, och varje roll får ett yttrande per samråd.
- `src/aie/collaboration/`: `required_for` avgör vilka som måste yttra sig.
  - Ett belopp kräver CFO, riskklass medium eller högre kräver CRO och juridik eller villkor kräver Compliance.
  - Grundarna krävs över `HUMAN_APPROVAL_THRESHOLD`, vid kritisk risk och när gränsen saknas (D-019, ER-02).
- `ConsultationBoard`:
  - Bara nivå 1–3 och grundare får öppna ett samråd.
  - Bara krävda roller får yttra sig, och ett yttrande kräver motivering. En invändning kräver underlag.
  - Samrådet är klart när alla krävda roller har yttrat sig. Enighet krävs inte, utan invändningarna lämnas vidare till oenighetshanteringen (§20, §21).
  - Varje steg loggas i audit-loggen.
- `tests/unit/test_consultation.py`: 13 tester.

## [Unreleased] — 2026-10-23 — Fas 3b: kontrollfunktionernas stopp (SR-05)
### Tillagt
- Migration 7 `control_stops`. Ett stopp gäller en agent, ett departement eller ett verktyg. Det raderas aldrig, kan inte ändras och kan bara hävas en gång.
- `src/aie/authorization/stops.py`: `ControlStops.place`, `lift`, `active` och `blocking`.
  - Bara grundare eller aktiva kontrollfunktioner med `action.block` får sätta stopp.
  - Kontrollfunktioner kan inte stoppa varandra, sina departement eller själva stoppverktyget (§18). Det kan bara grundarna.
  - Bara den som satte stoppet, eller en grundare, kan häva det. Ingen operativ chef kan det, inte ens CEO (SR-05).
  - Satta och hävda stopp loggas i audit-loggen.
- `AuthorizationEngine(..., stops=...)` nekar alla verktyg som träffas av ett aktivt stopp och anger stoppets nummer och skäl.
- `tests/unit/test_stops.py`: 13 tester.

## [Unreleased] — 2026-10-23 — Fas 3a: hierarki och styrverktyg
### Tillagt
- `src/aie/agents/hierarchy.py`: nivåerna i §8, regler för rapportvägar (`reporting_line_error`) och `OrgChart`. `OrgChart` har befälskedja, underställda, departementschefer, kontrollfunktioner och `is_above`.
- Registret vägrar rapportvägar som bryter mot §8. Kontrollfunktionerna kan inte lyda under CEO, en chef måste lyda under CEO och en arbetsagent måste ha en chef i samma departement (FR-09).
- `permissions.toml`:
  - obligatorisk `level` per roll
  - ny roll `compliance` (nivå 2)
  - styrverktygen `governance.change_constitution`, `governance.change_limits` och `governance.change_mandate`, som ingen roll kan få
- Authorization Engine nekar alla `governance.*` och loggar försöket (SR-04). Det gör ROADMAP:s första nyckeltest för Fas 3 grönt.
- D-020 (föreslaget).
- `tests/unit/test_hierarchy.py`: 9 tester. `tests/unit/org_helpers.py` skapar giltiga chefer i tester som inte handlar om hierarkin.
### Ändrat
- Fas 2-acceptansens MVP: CFO och CRO rapporterar till grundarna, inte till CEO.
- `test_llm_gateway.py`, `test_tasks.py` och `test_authorization.py` registrerar agenter med giltiga rapportvägar.

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
