# Oberoende granskning (D-055), ny session — 2026-10-30

**Underlag:** `a52a95fe445c37a48a6cf2811d8d6a40bd207515` (main efter PR #131).
**Utfall: inte godkänd för riktiga pengar.** Tre nya fynd med allvarlighet high är reproducerade, och H5 från
förra granskningen är fortfarande öppet. Testsviten är grön, men den täcker inte fynden nedan.

| ID | Allvarlighet | Fynd | Verifiering |
|---|---|---|---|
| N1 | high | En nekad `record_spend` rullar tillbaka skyddat läge, nödstopp och incidenter | Reproducerat |
| N2 | high | Stop-loss utvärderas inte före utgifter, bara i `tick()` | Reproducerat |
| N3 | high | Pilotens godkännande är en fritextsökning; ett agentbeslut räknas som grundarens godkännande | Reproducerat |
| H5 | high | (kvar från förra granskningen) Bedömningens `ready` härleds inte ur simuleringsbevis | Kodspårat, oförändrat |
| N4 | medium | `sales.list` blockeras inte i skyddat läge | Kodspårat |
| N5 | medium | Piloten bokför alltid hela priset som återbetalning; delåterbetalningar blir fel | Kodspårat |
| N6 | medium | En korrigering av en pilotpost stoppar alla senare importer | Kodspårat |
| N7 | medium | `pilot approve` bokför 500 kr insatt kapital som genomfört, utan underlag för insättningen | Kodspårat |
| N8 | medium | Skatteexporten ger spår C alla årets kostnader och ger varje grundare 100 % av ospårade intäkter | Kodspårat |
| N9 | low | Flera korrigeringar under tröskeln kan tillsammans passera den utan godkännande | Kodspårat |
| N10 | low | `approved` i ledgern kräver bara en sträng som börjar med `approval:`/`decision:` | Kodspårat |
| N11 | low | Drawdown räknar betald skatt som förlust och påverkas av nya insättningar | Kodspårat |
| N12 | low | Momsgränsen (ER-20) kontrolleras inte i pilotens import eller vid manuell listning | Kodspårat |
| N13 | low | Docstrings och felmeddelanden säger fortfarande "två grundare" (motsäger D-049); D-059 saknas i DECISIONS.md | Kodspårat |
| N14 | low | Bara OpenRouter kontrolleras som gratis (`:free`); Groq kan vara betald utan att koden märker det | Kodspårat |

## Oberoende och mandat

Granskaren är en ny Claude Code-session, startad från den schemalagda granskningsprompten i
`docs/reviews/REVIEW-PROMPT.md`. Sessionen har inte skrivit någon av den granskade koden och delar inget
sammanhang med sessionerna som byggde den. Den följer därmed den striktare rutinen i REVIEW-PROMPT.md.
Det finns redan en rapport från i dag, `REVIEW-2026-10-30.md`. Den skrevs av en session som saknade tomt
sammanhang, och den granskade en äldre commit (`e39f117`). Den filen lämnas orörd. Den här rapporten har ett
eget filnamn så att ingenting skrivs över.

Ingen kod har ändrats. Reproduktionerna kördes som fristående skript i en temporär katalog, med testernas
fixturer (`SystemCase`, `PilotLive`) och isolerade databaser. Ingen riktig försäljning, ingen nyckel och
inget nätverk användes.

**Läst:** CONSTITUTION.md (relevanta delar: §5, §23–26, §38, §40, §59), DECISIONS.md D-016, D-049, D-055
och D-063, REQUIREMENTS.md (SR-, ER- och DR-kraven). **D-059 finns inte i DECISIONS.md**, bara som förslag i
`docs/proposals/2026-10-28-D-059-plattformsberoende.md`, trots att `risk_limits.toml` hänvisar till det (N13).

**Granskat:** `src/aie/ledger/`, `src/aie/budget/`, `src/aie/tax/`, `src/aie/risk/`, `src/aie/authorization/`,
`config/permissions.toml`, `src/aie/pilot/`, `src/aie/llm/gateway.py` (och de delar av router/providers som
gateway förlitar sig på), samt de relevanta migrationerna i `src/aie/memory/migrations.py` och kopplingen i
`src/aie/system.py`.

**PR:er med etiketten `kräver-oberoende-granskning`:** #82, #83, #84, #85, #88, #89, #90, #92, #95, #97, #98,
#126, #127, #128, #129 och #130. Alla är redan sammanslagna. Granskningen gäller deras kod som den ser ut på
commiten ovan, inte varje historisk diff för sig. N1 är en direkt följd av rättelsen i #128 (H4).
Ingen kommentar har lagts på dessa PR:er. Enligt D-055 punkt 3 ska granskningen dokumenteras som kommentar
per PR; det kan göras när fynden är åtgärdade.

## Testutfall

Kört från `ai-enterprise/` med lokal Python 3.13.17:

```text
$ PYTHONPATH=src python3 -m unittest discover -s tests
...
----------------------------------------------------------------------
Ran 764 tests in 244.965s

OK
```

Utskriften innehöll även fem `ResourceWarning` (stängda SQLite-anslutningar och en lokal socket) och
mockade loggmeddelanden. Inga tester misslyckades eller hoppades över.

## Status för förra granskningens fynd (REVIEW-2026-10-30.md)

| ID | Status på `a52a95f` | Belägg |
|---|---|---|
| H1 senare återbetalning | Åtgärdat | `pilot/live.py:249–291`: separat `:refund`-post med eget datum |
| H2 avbruten import | Åtgärdat | `pilot/live.py:238` en transaktion; `:296–297` kontroll mot beständiga poster |
| H3 händelsedatum | Åtgärdat | `ledger.py:105,137–139` `occurred_on`/`economic_date`; används i `tax/engine.py:205,307,372` |
| H4 samtidig budget | Åtgärdat, men se N1 | `budget/engine.py:256–286`, `BEGIN IMMEDIATE`; test `test_atomic_spending.py` |
| H5 bedömning utan bevis | **Öppet** | `registry/assessments.py:67–90` oförändrat; testfixturen godkänner fortfarande `{"test": True}` |
| M1 riskklass | Åtgärdat | `budget/approvals.py:129–130`, migration 35 |
| M2 avstämningsincident | Åtgärdat | `pilot/live.py:301–306` återanvänder incidenten |
| M3 Ollama-adress | Åtgärdat | `llm/providers.py:148–157` kräver loopback |
| M4 skattebetalning | Åtgärdat | `tax/engine.py:250–254` en transaktion med `payment_id` |
| M5 webbkvot | Åtgärdat enligt #130 | Ligger utanför granskningsuppdraget; inte djupgranskat |

---

## N1 — En nekad utgift raderar skyddat läge och nödstopp (high)

**Fil/rad:** `src/aie/budget/engine.py:271–286` tillsammans med `src/aie/risk/protected.py:177–191` och `:232–237`.
**Krav:** SR-07, SR-08, §59, SR-09.

`record_spend()` kör `check()` inuti `with self._ledger._db.transaction()`. Spärren `ProtectedMode.spend_block_reasons()`
anropar `update()`. Det skriver händelsen `entered` i `operating_mode_events`, aktiverar nödstoppet vid
bokföringsfel och skapar incidenter. När utgiften sedan nekas kastas `BudgetBlocked`, och **hela transaktionen
rullas tillbaka, inklusive skyddat läge, nödstoppet, incidenterna och revisionsposterna.** Bara en kort
`budget.blocked`-post skrivs efteråt.

**Scenario (reproducerat):** en kostnad bokförs `unapproved`, vilket är ett §59-skäl för skyddat läge och,
eftersom det gäller bokföringen, även för nödstopp. Agentflödet (`simulation/cycle.py:226`) anropar `record_spend`.

```text
before: protected False kill False
record_spend: blocked -> ('skyddat driftläge sedan …: … obehöriga transaktioner i ledgern: [2] (§59)',)
after record_spend: protected False kill False
operating_mode_events rows 0 kill_switch_events rows 0
after advisory check(): protected True kill True
```

Utgiften stoppas visserligen varje gång. Men `AuthorizationEngine` läser bara `state()` (`protected.py:224–230`,
`killswitch.py:135–142`), så **externa verktyg och modellanrop fortsätter som om inget hänt.** Grundarna får
ingen incident, och revisionsloggen saknar inträdet. Ett obehörigt uttag eller en bruten hashkedja ger alltså
inget nödstopp, så länge den enda vägen som upptäcker det är en utgift. I agentflödet är det så.

**Åtgärd:** gör spärrarnas skrivningar beständiga oberoende av utgiftens transaktion. Ett sätt är att köra
`protected.update()` (och stop-loss, se N2) **före** utgiftstransaktionen, och att låta spärren i transaktionen
bara läsa läget. Ett annat är att skriva läge, nödstopp och incident i en egen commit innan `BudgetBlocked` kastas.
**Regression:** `record_spend` med ett §59-skäl ger `protected.state().protected == True` och
`kill.state().engaged == True` efteråt, och en `mode.protected_entered`-post finns i revisionsloggen.

## N2 — Stop-loss blockerar inte förrän nästa `tick()` (high)

**Fil/rad:** `src/aie/risk/stoploss.py:226–235`, `src/aie/system.py:132–136`, `src/aie/budget/engine.py:213–217`.
**Krav:** ER-13, §26.

`StopLoss.spend_block_reasons()` läser bara **sparade** utlösningar (`active()`). Gränserna mäts och sparas
bara i `evaluate()`, som anropas av `System.tick()` och av `pilot check_stops`. Mellan två körningar kan alltså
en nådd gräns passeras. Budgetmotorns egna kontroller fångar inte samma sak, eftersom de mäter budget och
reserv, inte förlust per initiativ eller drawdown.

**Scenario (reproducerat):** insatt kapital 500, godkänt och realiserat 60 kr förlust på initiativet `etsy`
(gräns `MAX_SINGLE_EXPERIMENT_LOSS` = 50 kr). Ingen `tick()` har körts.

```text
breaches now: [('initiative', 'etsy', 'MAX_SINGLE_EXPERIMENT_LOSS')]
active trips: 0
record_spend on loss-making initiative: ALLOWED, entry 3
```

**Åtgärd:** låt spärren även utvärdera `breaches()` och blockera på dem direkt, eller kör `evaluate()` före
varje utgift utanför utgiftstransaktionen. Om `evaluate()` körs inuti transaktionen uppstår samma problem
som i N1: utlösningen rullas tillbaka. Tänk också på att `_stoploss()` i `tick()` hoppar över utvärderingen
helt när inget `capital_in` finns.
**Regression:** en nådd gräns utan föregående `tick()` ger `BudgetBlocked`, och utlösningen finns kvar efteråt.

## N3 — Pilotens godkännande kan uppfyllas av ett agentbeslut (high)

**Fil/rad:** `src/aie/pilot/live.py:125–130` (`approval()`), använt i `:227–229`, och i `src/aie/pilot/cli.py:107–110` och `:138–139`.
**Krav:** D-048, D-049, ER-14, §55, SR-01.

`approval()` letar efter **vilket beslut som helst** vars `chosen_action` matchar `LIKE 'Starta piloten <initiativ>:%'`
och tar det senaste. Funktionen kontrollerar inte att beslutet kommer från godkännandekön, att en grundare har
fattat det, att beloppet är rätt eller att det rör rätt förfrågan. En agent med `decision.record` (CEO, CFO, CRO,
research_lead) får själv fatta beslut upp till `HUMAN_APPROVAL_THRESHOLD` (`governance/escalation.py:122–128`).
Ett beslut med budget 0 och rätt text räcker därför.

**Scenario (reproducerat):** `pilot prepare` körs, och förfrågan #1 väntar på en grundare. `ceo-1` lämnar ett
eget beslut med budget 0 och texten `Starta piloten pilot-…: …`.

```text
approval() after prepare only: None
CEO submit with budget 0 -> Decision
approval() now: (1, '2026-10-30T16:16:00+00:00')
founder request still pending: [1]
import_sales without founder approval: OK, sales = 1
```

Följderna: `aie pilot status` visar "Godkänd: <datum>" fast ingen grundare har godkänt, `import_sales` släpps
igenom, och klockan för regeln om 60 dagar utan försäljning (`check_stops`) kan flyttas fram med ett nytt beslut,
eftersom den senaste träffen används. Tecknen `%` och `_` i initiativnamnet tolkas dessutom som jokertecken.
Det kräver att en agent kan agera mot pilotens databas. `prepare` registrerar organisationen där (`ensure_org`).

**Åtgärd:** spara förfrågans ID när piloten förbereds, och härled godkännandet från `ApprovalRequest`:
status `approved`, typ DECISION, godkänd av en grundare, med just det initiativet och beloppet. Sök aldrig
på fritext. Ta godkännandets tidpunkt från kön, inte från det senaste beslutet.
**Regression:** ett agentbeslut med samma text ger `approval() is None` och nekad import.

## H5 — Bedömningen kan vara "redo" utan bevis (high, kvar)

**Fil/rad:** `src/aie/registry/assessments.py:67–90`.
**Krav:** D-058, D-048, D-063, §54.

Fyndet är oförändrat sedan förra granskningen. `record()` tar emot valfritt `result` och en `ready`-flagga från
anroparen, och `approve()` kontrollerar bara flaggan. Testfixturen `SystemCase.approve_initiative` sparar
fortfarande `{"test": True}` med `ready=True` och får den godkänd. Bedömningen är spärren som låter budgetmotorn
godkänna utgifter i ett initiativ (`initiatives=register`).
**Åtgärd:** samma som förra rapporten: härled `ready` ur sparade och validerade körningar (normal, pessimistisk,
nollförsäljning), och avvisa ett ofullständigt underlag även när en grundare godkänner.

## N4 — `sales.list` blockeras inte i skyddat läge (medium)

**Fil/rad:** `src/aie/risk/protected.py:44–45`, `:224–230`; `config/permissions.toml` (`research_lead`, `sales.list`).
**Krav:** SR-08, §59.

Skyddat läge blockerar bara `research.search` och verktyg som börjar med `external.`, `money.`, `publish.` eller
`payment.`. `sales.list` ("lista eller pausa ett initiativ till försäljning") faller utanför, så research_lead
kan lista ett initiativ till försäljning medan systemet står i skyddat läge. Nödstoppet blockerar det, men
skyddat läge leder bara till nödstopp när orsaken är bokföringen.
**Åtgärd:** lägg till `sales.` i `EXTERNAL_PREFIXES`, eller vänd logiken till en vitlista av ofarliga verktyg,
som nödstoppet gör. Tillåt pausning separat om det behövs.

## N5 — Återbetalning bokförs alltid som hela priset (medium)

**Fil/rad:** `src/aie/pilot/live.py:251–252`, `:295`.
**Krav:** ER-08, ER-09, ER-23.

En rad med `Refunded?=true` ger en återbetalningspost lika med hela `price`. En delåterbetalning, eller en
plattform som också betalar tillbaka avgiften, blir fel i ledgern, i skattereserven och i returkvoten för
stoppreglerna. Avstämningen fångar inte felet, eftersom `csv_net` räknas med samma antagande.
**Åtgärd:** läs återbetalningsbeloppet (och eventuell återbetald avgift) från exporten, eller avvisa raden när
beloppet saknas, på samma sätt som datumet redan avvisas.

## N6 — En korrigering stoppar alla senare importer (medium)

**Fil/rad:** `src/aie/pilot/live.py:264–270`, `:286–297`.
**Krav:** ER-08, SR-12.

`expected_ledger_net` räknas på originalbeloppen, medan `ledger_net` räknar in `corrections()`. Om en grundare
rättar en pilotpost med `Ledger.correct()`, vilket är den väg ER-08 föreskriver, skiljer sig summorna så snart
samma försäljning finns med i en senare export. Det är normalt, eftersom exporterna är kumulativa. Varje sådan
import kastar då `PilotError("ledgerns netto stämmer inte …")`.
**Åtgärd:** definiera hur en rättad post stäms av, till exempel genom att jämföra originalbeloppet för
identiteten och redovisa korrigeringarna separat i avstämningen.

## N7 — Pilotkapitalet bokförs som genomfört utan underlag (medium)

**Fil/rad:** `src/aie/pilot/live.py:111–122`.
**Krav:** ER-11, §40, ER-10.

Vid `pilot approve` bokförs `capital_in` på hela förfrågans belopp med status `settled` och underlaget
`approval:<id>`, inte en bankhändelse. Ledgern visar då 500 kr likvida medel som kanske inte finns. Det gör
400 kr disponibelt för budgetmotorn och nollställer drawdown-mätningen. `approve()` kontrollerar inte heller
att förfrågan faktiskt gäller piloten. Godkänns en annan förfrågan via `aie pilot approve`, bokförs dess belopp
som "pilotkapital".
**Åtgärd:** bokför insättningen separat med underlag (kontoutdrag) när den har skett, eller som `pending`
fram till dess. Kontrollera att förfrågan är pilotens.

## N8 — Skatteexporten fördelar fel (medium)

**Fil/rad:** `src/aie/tax/engine.py:376–391`.
**Krav:** ER-18, ER-21, D-010.

- `costs_share_minor` för spår C (enkelt bolag) summerar **alla** årets kostnader och avgifter, även de som
  hör till initiativ med ett annat spår eller utan spår. Avdragen i underlaget till NE-bilagan blir för höga.
- En ospårad intäkt hamnar med 100 % i **varje** grundares export (`amount = self._signed(e)` när `a is None`).
  Två exporter tillsammans visar alltså dubbla intäkten. En notering varnar för det, men siffran i filen är fel.

**Åtgärd:** begränsa kostnaderna till initiativ vars intäkter har spår C (som `position()` gör vid
`basis = "profit"`). Visa ospårade intäkter som en separat, odelad lista utan "din andel", eller vägra exportera
tills allt har spår.

## N9 — Korrigeringar kan kringgå godkännandetröskeln (low)

**Fil/rad:** `src/aie/ledger/ledger.py:246–269`, `:371–380`.

`correct()` ärver originalets godkännandestatus, och tröskelkontrollen gäller bara korrigeringens eget belopp.
En kostnad på 20 kr (`not_required`) kan rättas upp med +20 kr flera gånger, till ett belopp långt över
`HUMAN_APPROVAL_THRESHOLD`, utan godkännande. Bara grundare och systemkomponenter skriver, så risken gäller
främst misstag. **Åtgärd:** pröva tröskeln mot det korrigerade totalbeloppet.

## N10 — `approved` verifieras inte mot ett faktiskt godkännande (low)

**Fil/rad:** `src/aie/ledger/ledger.py:365–370`.

Det räcker med en sträng som `approval:999` eller `decision:x`. Ledgern kontrollerar inte att godkännandet
finns, gäller beloppet eller är förbrukat. Resultat och `_split_flags` litar på statusen. **Åtgärd:** låt
budgetmotorn ensam sätta `approved` (det gör `record_spend` redan), och validera referensen när andra skrivare
anger den.

## N11 — Drawdown mäts mot likvida medel (low)

**Fil/rad:** `src/aie/risk/stoploss.py:142–150`.

`START_CAPITAL − likvida` räknar `tax_payment` som förlust (via `_OUT` i `capital.py`), vilket kan ge falska
utlösningar. Samtidigt döljs en verklig förlust om mer kapital sätts in. **Åtgärd:** räkna drawdown på
resultatet (`compute_result`) i förhållande till insatt kapital, inte på kassan.

## N12 — Momsgränsen gäller inte pilotens försäljning (low)

**Fil/rad:** `src/aie/tax/engine.py:353–361`; `src/aie/pilot/live.py:217–311`.
**Krav:** ER-20.

Spärren gäller bara agentverktyg som börjar med `sales.`, `publish.` eller `payment.`. Pilotens listning görs för
hand, och `import_sales`/`check_stops` anropar varken `check_vat()` eller varnar. Med 500 kr i tak är risken
liten, men kravet "blockering av ny försäljning vid gränsen" uppfylls inte för den verkliga kanalen.
**Åtgärd:** anropa `check_vat()` i `check_stops` och ta med gränsen bland stoppskälen.

## N13 — Inaktuell dokumentation om två grundare; D-059 saknas (low)

**Fil/rad:** `src/aie/risk/stoploss.py:26–28`, `:200–210`; `src/aie/risk/killswitch.py:18–20`, `:90–100`;
`src/aie/tax/engine.py:333`, `:343–344`; `src/aie/memory/migrations.py:685`.

Koden följer D-049 (en grundare räcker), men docstrings och felmeddelanden ("den andra grundaren måste också …")
säger två. Det kan få en grundare att tro att en återstart kräver en andra röst. D-059 hänvisas till från den
skyddade `risk_limits.toml` och från granskningsprompten, men finns inte i DECISIONS.md.
**Åtgärd:** uppdatera texterna. För in D-059 i DECISIONS.md eller ta bort hänvisningen.

## N14 — Gratisleverantör kontrolleras bara för OpenRouter (low)

**Fil/rad:** `src/aie/llm/router.py:216–217`.
**Krav:** §42, DR-12, ER-22.

Bara OpenRouter-modeller måste sluta på `:free`. Groq räknas som gratis utan kontroll, och om kontot har betalning
aktiverad uppstår kostnader som systemet bokför som 0 (`cost_minor: 0`). Gateway-delen i övrigt är riktig: den
kräver `llm.complete`, avvisar prompter med hemligheter innan något skickas, och routern skickar bara `public`
externt. Klassen sätts av anropande kod, inte av agenten (`simulation/cycle.py:46–55`).
**Åtgärd:** dokumentera kravet på gratiskonto som grundaråtgärd i FOUNDER-CHECKLIST, eller lägg till en
konfigurationsflagga som kräver ett uttryckligt "free tier"-intygande per leverantör.

## Positiva kontroller

- **Ledgern:** STRICT-tabeller, triggers mot UPDATE/DELETE på poster och status, framåtriktad status i databasen
  (`ledger_status_forward`), unika `idempotency_key`/`external_id`, heltal med valuta, och SIM/riktig valuta
  separerade per databasmiljö (`ledger.py:344–349`, `Database._check_environment`).
- **Budget:** `record_spend` serialiserar med `BEGIN IMMEDIATE` och förbrukar godkännandet i samma transaktion.
  Testet med två trådar visar att högst en lyckas. Saknade gränser blockerar (ER-02). Kritisk riskklass blockeras alltid.
- **AuthorizationEngine:** default deny, okänt verktyg nekas, `governance.*` nekas alltid, TESTING bara i sim,
  och fel i spärrar eller revisionslogg ger nej.
- **Skatt:** reserven räknas per spår och år efter händelsedatum, ospårat reserveras med högsta satsen, och
  betalning är atomär och idempotent.
- **Piloten:** importen är nu atomär, daterad och tål återbetalningar och dubbletter. Avstämningsincidenten återanvänds.

## Kvarvarande tillitsgränser (inga nya fynd)

- `--as robin` är en identitetsuppgift, inte autentisering. Agentprocesser får inte ha samma åtkomst som en grundare.
- Revisionsloggens hashkedja upptäcker inte trunkering av slutet utan en externt sparad head-hash.
- Skattesatser, spår och plattformsvillkor är inte juridiskt verifierade (Q-05, Q-TAX-01).

## Rekommenderad ordning

1. N1 och N2 tillsammans: spärrarnas utvärdering ska ske och sparas utanför utgiftstransaktionen.
2. N3: godkännandet ska härledas ur godkännandekön.
3. H5: härled `ready` ur bevis.
4. N4–N8 före första riktiga import; N9–N14 när tillfälle ges.

Efter rättelserna behövs en ny oberoende granskning av den rättade versionen, och en kommentar på varje berörd
PR enligt D-055 punkt 3, innan piloten godkänns.
