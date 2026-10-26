# DECISIONS — beslutslogg

Regler: nya beslut läggs **överst i sin sektion** med nästa lediga ID. Ett beslut ändras aldrig i efterhand — det ersätts av ett nytt beslut som hänvisar till det gamla ("Ersätter D-00X"). Status: `Föreslagen` → `Godkänd` / `Avvisad` / `Ersatt`.

Ett beslut räknas som **Godkänt** först när den/de som har beslutsrätt har skrivit sitt namn och datum i fältet *Godkänd av*. Eftersom beslutsfördelningen mellan grundarna ännu inte är fastställd (Q-01) kräver Fas 0-besluten tills vidare **båda** grundarnas godkännande.

---

## Fas 3 — beslut

### D-039 Versionerade strategier: varje ändring är en ny version, återställning är en ny version, obligatoriskt kräver en regel
- **Status:** Föreslagen · **Föreslagen av:** Claude (session med Yorgo, under Robins överlämning), 2026-10-26 · **Bygger på:** D-038 · **Gäller:** FR-18, FR-17, §30, §53
- **Beslut:**
  1. `StrategyRegistry` sparar strategier och agentversioner (`agent:<id>`) som numrerade versioner. Varje version har innehåll (JSON-objekt), motivering, författare och de lärdomar den bygger på, med lärdomarnas status vid sparandet. Den senaste versionen gäller.
  2. Inget skrivs om (migration 24). `restore()` skapar en ny version med den gamla versionens innehåll som pekar på den (`restores`), så att strategiförändringar kan återställas utan att historiken försvinner (§53).
  3. En obligatorisk ändring av gemensamma regler (`mandatory=True`) kräver minst en lärdom. Alla lärdomar som anges måste vara godkända operativa regler, och ändringen görs av en grundare (FR-17).
  4. Vanliga ändringar görs av grundarna eller nivå 1–3. De får hänvisa till lärdomar med lägre status, och sådana lärdomar markeras som ej verifierade.
  5. `diff()` visar vilka nycklar som ändrades mellan två versioner.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-038 Lärdomsregister: fem statusar ett steg i taget, test krävs, bara båda grundarna gör en regel
- **Status:** Föreslagen · **Föreslagen av:** Claude (session med Yorgo, under Robins överlämning), 2026-10-26 · **Bygger på:** D-019, D-035, D-036 · **Gäller:** FR-17, §27, §29, §30, §53
- **Beslut:**
  1. `LessonRegistry` sparar lärdomar med påstående, orsakstyp (de sju i §29), område och minst en källa (`incident:`, `forecast:`, `decision:`, `task:`, `ledger:` eller `test:`). Incident- och prognoskällor kontrolleras mot loggarna.
  2. Statusarna är de fem i §29, och de går ett steg i taget:
     - **Preliminär:** granskas av grundare eller nivå 1–3, inte av den som föreslog lärdomen.
     - **Testad:** kräver minst ett test, det vill säga en prognos med utfall eller ett `test:`-underlag.
     - **Reproducerbar:** kräver minst två olika test.
     - **Godkänd operativ regel:** kräver att båda grundarna röstar.
  3. Bara godkända operativa regler får ändra gemensamma regler. `require_rule()` kastar för allt annat, och en obekräftad hypotes kan aldrig bli en regel automatiskt (§53).
  4. Sänkning och avvisning görs med motivering. Inget raderas eller skrivs om (migration 23).
  5. `from_incident()` skapar en hypotes från en incidents förebyggande åtgärd eller grundorsak (§27).
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-034 Skatteunderlag: inget raderas, export per grundare och år med kontrollsumma
- **Status:** Föreslagen · **Föreslagen av:** Claude (session med Yorgo, under Robins överlämning), 2026-10-26 · **Bygger på:** D-010, D-024, D-032 · **Gäller:** ER-21, §30
- **Beslut:**
  1. Underlaget arkiveras genom att ingenting kan raderas. Ledgern (migration 13) och skattetabellerna (migration 21–22) har triggers mot ändring och radering, så underlaget finns kvar i minst 7 år (`ARCHIVE_YEARS`).
  2. `TaxEngine.export(founder, year, out_dir)` skriver ett deklarationsunderlag per grundare och kalenderår som JSON. Filen innehåller varje post med andel, spår och underlag. Spår C får också grundarens andel av årets kostnader och avgifter, som underlag för NE-bilagan.
  3. Varje export loggas med filnamn och SHA-256 i `tax_events` och i revisionsloggen.
  4. Underlaget är inte en deklaration. Intäkter utan spår markeras och ska märkas innan deklarationen.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-033 Momsgränsen: varning vid 80 %, ny försäljning blockeras vid gränsen tills båda grundarna har beslutat
- **Status:** Föreslagen · **Föreslagen av:** Claude (session med Yorgo, under Robins överlämning), 2026-10-26 · **Bygger på:** D-010, D-019, D-024 · **Gäller:** ER-20
- **Beslut:**
  1. Årets försäljning är realiserade och väntade intäkter minus realiserade återbetalningar, per kalenderår. Gränsen är `vat_threshold` i `config/tax.toml` (120 000 kr; simulerat i `SIM`).
  2. Vid `vat_warning_percent` (80 %) loggas en varning till grundarna och CFO, en gång per år. Vid gränsen loggas det en gång till.
  3. Vid gränsen blockerar spärren `TaxEngine.tool_block_reason` alla verktyg som börjar med `sales.`, `publish.` eller `payment.`, tills **båda** grundarna har röstat med `vat_vote()`, till exempel efter momsregistrering. Det är en fråga som binder båda (D-019).
  4. Ledgern tar fortfarande emot försäljning som redan har skett (D-024). Bara *ny* försäljning stoppas.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-032 Tax Engine: skattespår per intäkt, försiktig skattereserv som åtagande, CFO får märka
- **Status:** Föreslagen · **Föreslagen av:** Claude (session med Yorgo, under Robins överlämning), 2026-10-26 · **Bygger på:** D-010, D-024, D-027 · **Ändrar:** `config/permissions.toml` (nytt verktyg `tax.assign` för CFO) och D-027 punkt 4 (återinvesterbar vinst när Tax Engine är kopplad) · **Gäller:** ER-18, ER-19
- **Beslut:**
  1. Tax Engine räknar och reserverar skatt, men väljer inte spår åt Skatteverket. D-010 och Q-05 är fortfarande öppna, och satserna i `config/tax.toml` är simulerade och försiktiga.
  2. Varje intäkt och återbetalning märks med ett spår (A ISK, B egenanställning, C enkelt bolag, D hobby) och en fördelning mellan grundarna. Spår C delas enligt `partnership_shares`, och A, B och D ägs av en grundare. En rättelse i ledgern ärver spåret. Ett byte av spår är en ny rad med motivering (migration 21).
  3. Märker gör grundarna och roller med `tax.assign`. Det är bara CFO.
  4. Reserverad skatt beräknas per spår och kalenderår som satsen × realiserad bruttointäkt, avrundat uppåt. En intäkt utan spår reserveras med `untracked_rate`, som måste vara minst lika hög som den högsta satsen.
  5. `capital_position(tax_reserved_minor=)` räknar den reserverade skatten som ett åtagande, så att den aldrig blir disponibel. `BudgetEngine(tax=)` använder den före varje utgift.
  6. När Tax Engine är kopplad är återinvesterbar vinst (nettovinst − reserverad skatt) × `REINVESTMENT_POLICY`, högst det disponibla. Utan Tax Engine är den 0, som i D-027.
  7. `API_SPEND` är fortfarande spärrad (ER-22) tills grundarna sätter `API_MONTHLY_CAP` över 0.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-037 Prestationsmätning: rollprofiler enligt §31, ingen totalpoäng, den som hittar fel straffas aldrig
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-020, D-035, D-036 · **Gäller:** FR-19, §31, §33
- **Beslut:**
  1. `PerformanceReview.scorecard()` mäter varje agent med rollens profil (`PROFILES`). Måtten är måluppfyllelse (uppgifter), prognosprecision (prognosloggen, med trend), ekonomiskt bidrag (ledgerns nettovinst för departementet, för CEO hela företaget), regelefterlevnad, felhantering, riskidentifiering (CRO) och verifierade incidenter.
  2. Kontrollfunktionerna (nivå 2) mäts aldrig på ekonomiskt bidrag. Arbetsagenter i research mäts inte heller på det. Granskande roller mäts på hur väl de hittar problem.
  3. Att rapportera en incident räknas som ett bidrag och ger aldrig ett sämre värde. En incident räknas mot en involverad agent först när den är verifierad (fält 16).
  4. Regelefterlevnad räknar bara försök att använda verktyg utanför rollens mandat. Nekanden från nödstopp, skyddat läge, stop-loss eller avstängning räknas inte.
  5. Det finns ingen sammanvägd totalpoäng. Det som §31 nämner men som ännu inte kan mätas (kvalitet, kostnadseffektivitet, samarbetsförmåga och dokumentation) listas öppet.
  6. `review()` sparar en ögonblicksbild som aldrig ändras (migration 20). Den görs av grundarna eller nivå 1–3, aldrig av agenten själv, och ändrar aldrig agentens tillstånd. Prövning och avstängning är egna beslut (§33, SR-17).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo; genomgånget gemensamt)

### D-036 Prognoslogg: prognoser skrivs aldrig om, utfall från ledgern jämförs automatiskt, ingen bedömer sin egen prognos
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-006, D-020, D-024 · **Gäller:** FR-16, §20 steg 10, ER-11
- **Beslut:**
  1. `ForecastLog` sparar en prognos innan utfallet finns, med mått, enhet, väntat värde, valfritt intervall, förfallodag och valfri länk till beslutet (`decision:<id>`). Alla värden är heltal (D-006).
  2. Måtten `net`, `revenue` och `costs` räknas från ledgerns affärsinitiativ (ER-09). Måttet `count` rapporteras.
  3. Inget raderas eller skrivs om (migration 19). En ny bedömning är en ny prognos som pekar på den gamla. Båda jämförs, eftersom §20 steg 10 jämför med den ursprungliga prognosen. Ingen reviderar efter förfallodagen.
  4. `evaluate()` hämtar utfallet från ledgern när prognosen har förfallit och resultatet inte är preliminärt (ER-11). Underlaget, det vill säga ledgerposterna, sparas med utfallet. `overdue()` visar förfallna prognoser som saknar utfall.
  5. Rapporterade utfall registreras av grundarna eller nivå 1–3, aldrig av den som gjorde prognosen. Rättelser är nya poster med motivering.
  6. `accuracy(agent)` ger antal jämförda prognoser, träffar inom intervallet, genomsnittligt fel i baspunkter och antal förfallna. Prestationsmätningen (5c) använder den.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo; genomgånget gemensamt)

### D-035 Incidentrapporter: 16 fält enligt §28, bara rättelseposter, varje stopp blir en incident
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-020, D-029, D-030, D-031 · **Gäller:** FR-15, §28, §31, §33
- **Beslut:**
  1. `IncidentLog` har de 16 fälten i §28 i samma ordning. Incident-ID och datum sätts automatiskt, och resten fylls i efter hand.
  2. Inget raderas eller skrivs om. Varje fält är en append-only post (migration 18). En ändring av ett ifyllt fält är en rättelse: en ny post som pekar på den gamla och har en motivering.
  3. Alla agenter som får agera kan öppna en incident. Grundarna, rapportören och agenter på nivå 1–3 kan skriva i den.
  4. Fält 16 (verifiering) fylls i sist, och inte av den som är ansvarig för uppföljningen (fält 15).
  5. Varje stop-loss-utlösning (D-029), nödstopp (D-030) och inträde i skyddat driftläge (D-031) blir automatiskt en incident med förifyllda fält. `sync()` skapar aldrig dubbletter.
  6. Den som rapporterar ett fel räknas inte som involverad (§31, §33). `involving()` visar bara incidenter där agenten finns i fält 4.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo; genomgånget gemensamt)

### D-031 Skyddat driftläge: sju villkor i §59, automatiskt inträde, en grundare lämnar när skälen är borta
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-019, D-027, D-030 · **Gäller:** SR-08, §59
- **Beslut:**
  1. `ProtectedMode.assess()` kontrollerar §59:
     - disponibelt kapital ≤ 10 % av `MINIMUM_RESERVE`, eller reserven saknas
     - behörighetskontrollen släpper igenom ett styrverktyg
     - revisionsloggens kedja är bruten, eller ledgerns resultat räknat på två sätt skiljer sig (ER-16)
     - obehöriga (`unapproved`) ledgerposter som inte är kvitterade eller korrigerade
     - en anmäld säkerhetsincident
     - ingen aktiv CFO, CRO, Compliance eller Audit
     - en kontroll som kraschar, eftersom systemet då inte kan avgöra läget
  2. Läget aktiveras automatiskt före varje utgift (spärren i `BudgetEngine`). Bruten bokföring, det vill säga revisionsloggen, ledgerns siffror eller obehöriga transaktioner, aktiverar dessutom nödstoppet (D-030) som `system:protected-mode`.
  3. I skyddat läge blockeras alla utgifter och externa verktyg: `research.search` och verktyg som börjar med `external.`, `money.`, `publish.` eller `payment.`. Analys och dokumentation fortsätter, även modellanrop, eftersom ProviderRouter håller intern data på datorn (DR-13).
  4. Säkerhetsincidenter anmäls av grundarna eller av kontrollfunktionerna.
  5. **En grundare** lämnar läget (D-019 punkt 1: ingen beloppsåtgärd), och bara när inget skäl längre gäller. Obehöriga poster kan kvitteras uttryckligen i samma steg. Incidenter stängs när läget lämnas.
  6. Händelserna är append-only (migration 17).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-030 Nödstopp: vad som stoppas, vem aktiverar, återstart kräver två grundare och intakt revisionslogg
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-019, D-020 · **Gäller:** SR-07, §38
- **Beslut:**
  1. När nödstoppet är aktivt blockerar `BudgetEngine` alla nya utgifter. `AuthorizationEngine` nekar alla verktyg utom `report.read`, `report.write`, `ledger.read`, `audit.verify`, `risk.assess` och `action.block`. Det betyder inga modellanrop, ingen webbsökning och inga nya eller tilldelade uppgifter.
  2. Ingenting raderas, och ledgern tar fortfarande emot fakta (D-024). Händelserna är append-only (migration 16).
  3. Nödstoppet kan aktiveras av grundarna, av aktiva kontrollfunktioner (nivå 2 med `action.block`) och av uttryckligen angivna systemkomponenter, till exempel `system:protected-mode`. CEO och chefer kan inte aktivera det.
  4. Återstart följer `docs/operations.md`: två *olika* grundare röstar var för sig efter den senaste aktiveringen, och revisionsloggen måste vara intakt vid varje röst.
  5. `python -m aie kill status|engage|release` är gränssnittet för grundarna.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-029 Stop-loss: fyra gränser mäts från ledgern, nya åtaganden stoppas, två grundare återupptar
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-019, D-024, D-026, D-027 · **Gäller:** ER-13, §26
- **Beslut:**
  1. `StopLoss.evaluate()` mäter fyra gränser från ledgern:
     - `MAX_SINGLE_EXPERIMENT_LOSS` per initiativ: realiserad nettoförlust ≥ gränsen.
     - `MAX_TOTAL_DRAWDOWN` för företaget: (START_CAPITAL − likvida medel) / START_CAPITAL ≥ gränsen.
     - Departementets `budget` i `budgets.toml`: utgifter, väntade och genomförda, ≥ budgeten.
     - `MINIMUM_RESERVE` för företaget: likvida medel − åtaganden ≤ reserven.
     En saknad gräns räknas som nådd (ER-02).
  2. En utlösning sparas (migration 15) med exponering (väntade utbetalningar i området), förpliktelser (deras poster) och vilka som informerats: CRO, CFO och, för ett departement, departementschefen. Utlösningen loggas i revisionsloggen.
  3. Medan utlösningen är aktiv blockerar `BudgetEngine` (spärr via `gates=`) **nya åtaganden** i området. Befintliga förpliktelser **avbryts eller raderas inte**. De hanteras som vanligt via ledgern (§26).
  4. Verksamheten återupptas först när **två olika grundare** har godkänt en återhämtningsplan (D-019 punkt 3, riskgränser). Det går inte medan gränsen fortfarande är nådd. Då måste läget åtgärdas först, eller gränsen ändras via PR.
  5. `evaluate()` utlöser inte samma gräns två gånger. Utlösningar och godkännanden är append-only.
  6. Kan en spärr inte avgöra blir svaret nej (§59).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-025 "Utred möjlighet": fast ordning, osäkert räknas som risk, skatt kräver Skatteverket
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-26 · **Bygger på:** D-011, D-019 · **Gäller:** FR-25
- **Beslut:**
  1. Ett utredningsärende (kanal, verktyg, gratis-API, intäktsväg, skatt, villkor, licens eller marknad) går alltid i ordningen **Research → Compliance → CFO → grundarna**. Inget steg kan hoppas över (migration 14, `collaboration/opportunities.py`).
  2. Ärendet öppnas av grundarna eller nivå 1–3. Fynden lämnas av Research (departementet research med `research.search`) med minst en källa (`url:` eller `file:`). De är alltid en **obekräftad hypotes** (§29).
  3. Compliance svarar `ok`, `not_ok` eller `uncertain`. **`uncertain` skickar ärendet tillbaka till Research** (§17: osäkerhet är risk, inte OK). `not_ok` avslutar ärendet som avvisat.
  4. CFO räknar fram förväntat netto efter avgifter och skatt, i heltal i minsta enhet. Det kan vara negativt.
  5. Grundarna godkänner eller avvisar. En **skattefråga** kan bara godkännas om någon källa är Skatteverket (`skatteverket.se`) eller en rådgivares underlag (`file:`). Godkända skatte-, villkors- och licensfrågor får status `approved_rule`, övriga `approved`.
  6. Ärendet kan valfritt hänvisa till en fråga i `research/QUESTIONS.md` (`R-01` …). Varje fråga utreds i högst ett ärende.
  7. Stegen är append-only, ett avslutat ärende ändras aldrig och allt loggas i revisionsloggen. Agenterna föreslår bara. De skapar inga konton, godkänner inga villkor och väljer inget skattespår (D-011).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-028 Uppdelade köp: samma initiativ, sju dagar, grundarna avgör
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-019, D-026
- **Beslut:**
  1. Budgetmotorn summerar utgifter (kostnader och avgifter, väntade och genomförda) i **samma affärsinitiativ** som registrerats de senaste **sju dagarna** och som inte behövde godkännande, plus den nya utgiften.
  2. Om summan passerar `HUMAN_APPROVAL_THRESHOLD` eller `MAX_SINGLE_TRANSACTION`, men den nya utgiften inte gör det själv, flaggas den som möjlig uppdelning (ER-04, §5).
  3. En flaggad utgift blockeras inte automatiskt, eftersom flera små köp kan vara helt legitima. Den behandlas som hela summan och kräver **båda grundarna** (D-019). Flaggan revideras.
  4. Köp som grundarna redan har godkänt räknas inte, eftersom de inte kan vara ett försök att slippa godkännande.
  5. Ledgern har inget motpartsfält än, så motpart används inte. Fönstret på sju dagar står i koden (`SPLIT_WINDOW`); att ändra det kräver ett nytt beslut.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-027 Kapitalbegreppen räknas från ledgern; reserven skyddas av budgetmotorn
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-024, D-026
- **Beslut:**
  1. Kapital finns bara om det finns i ledgern. `START_CAPITAL` i `risk_limits.toml` är en gräns, inte pengar; startkapitalet ska registreras som en `capital_in`-post, godkänd med hänvisning till beslutet.
  2. De sju begreppen i §23 räknas från ledgern i en valuta i taget: likvida medel (genomförda in- och utbetalningar), bundet kapital, totalt, skyddad reserv (`MINIMUM_RESERVE`), åtaget (väntade utbetalningar), disponibelt (likvida − reserv − åtaget, aldrig under 0) och återinvesterbart.
  3. Bundet kapital är 0 tills ledgern får tillgångsposter. En tillgång räknas aldrig som likvid (§23).
  4. Återinvesterbar vinst är 0 tills Tax Engine (4f) kan reservera skatten (ER-19). Vinst före skatt är inte disponibel för återinvestering.
  5. Budgetmotorn blockerar varje utgift som är större än det disponibla kapitalet. Ett godkännande från grundarna låser inte upp reserven; att använda den kräver att gränsen ändras, vilket kräver båda (D-019 punkt 3). Saknas `MINIMUM_RESERVE` blockeras alla utgifter (ER-02).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-26, registrerat av Yorgo)

### D-026 Departementsbudgetar och budgetmotorn
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-009, D-019, D-024 · **Ändrar:** ny konfigurationsfil `config/budgets.toml` (en ändring i gränserna, därför krävs båda grundarna enligt D-019 punkt 3)
- **Beslut:**
  1. Varje departement har i `config/budgets.toml` en budget, ett maxåtagande (väntade utgifter samtidigt), ett riskutrymme (low, medium eller high) och ett användningsområde (ER-17). Ett departement utan post får inga utgifter (ER-02).
  2. Föreslagna värden i SIM: Research 50 000 (åtagande 20 000, medium), Executive 20 000 (10 000, low), Finance 10 000 (5 000, low), Risk, Compliance och Audit 5 000 vardera (2 000, low). Summan är 95 000.
  3. Ingen budget får överstiga `MAX_DEPARTMENT_BUDGET`, och summan får inte överstiga `START_CAPITAL − MINIMUM_RESERVE`, så att budgetarna aldrig äter av den skyddade reserven (§5).
  4. Budgeten räknas på kostnader och avgifter i ledgern, väntade och genomförda, med korrigeringar. Budgetarna gäller tills vidare för hela miljöns livstid; perioder (till exempel per månad) kräver ett nytt beslut.
  5. `BudgetEngine.check()` körs före varje ekonomisk handling (ER-03) och blockerar vid överskriden budget, maxåtagande, `MAX_SINGLE_TRANSACTION`, `MAX_COMMITTED_CAPITAL`, riskutrymme, riskklass `critical`, saknad gräns och `API_SPEND`. Över `HUMAN_APPROVAL_THRESHOLD` är svaret nej tills båda grundarna har godkänt (D-019).
  6. `API_SPEND` är alltid spärrad tills Tax Engine (4f) kan visa realiserad nettovinst efter skatt (ER-22, D-009).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-024 Ledgern: vem skriver, fakta avvisas aldrig, nettovinst bara från genomförda poster
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-006, D-019, D-021
- **Beslut:**
  1. I Fas 4a skriver bara grundarna och uttryckligen angivna systemkomponenter (`system:<namn>`, till exempel `system:payments`) i ledgern. Agenter skriver inte där. Läsa får grundarna och agenter med `ledger.read` (CFO, Audit). Ingen ändring i `permissions.toml`.
  2. Ledgern registrerar det som har hänt. En kostnad som redan skett avvisas aldrig för att den bryter mot en gräns, eftersom det skulle gömma ett faktum. Att stoppa en handling innan den sker är budgetmotorns uppgift (ER-03, 4b).
  3. Godkännandestatus är `not_required`, `approved` (underlaget pekar på `approval:` eller `decision:`) eller `unapproved`. En utgående post över `HUMAN_APPROVAL_THRESHOLD`, eller vilken utgående post som helst när gränsen saknas, får inte vara `not_required` (ER-14, ER-02). `unapproved` visas som avvikelse i resultatet.
  4. Nettovinst = intäkter − återbetalningar − kostnader − avgifter, räknat bara på poster med status `settled`, i en valuta i taget. Kapitalrörelser räknas inte. Resultatet är preliminärt när något i urvalet väntar eller när ett initiativ har intäkter men inga kostnader eller avgifter (ER-09, ER-11).
  5. Audit räknar om resultatet med en separat SQL-fråga direkt mot tabellerna (ER-16). CFO saknar `audit.verify` och granskar därför inte sin egen rapport (§18).
  6. Idempotensnyckel krävs på varje post. Samma nyckel och samma innehåll ger den befintliga posten; annat innehåll eller ett externt ID som redan finns avvisas (ER-07, SR-12).
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-023 Uppgifter tilldelas bara nedåt i befälskedjan
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-020 · **Ändrar:** tilldelningsregeln i `TaskBoard.assign` (FR-07, Yorgos kod)
- **Beslut:**
  1. En agent med `task.assign` får bara ge en uppgift till en agent som har den som chef, chefs chef och så vidare (rapportvägarna i D-020). En departementschef fördelar alltså arbete inom sitt team (§8 nivå 3). CEO fördelar till departementscheferna och deras agenter (§8 nivå 1).
  2. CEO kan inte ge uppgifter till kontrollfunktionerna (CFO, CRO, Compliance, Audit), eftersom de rapporterar till grundarna och ska vara oberoende (§8 nivå 2).
  3. Vid byte av ägare gäller regeln både den gamla och den nya ägaren. Ingen tar en uppgift från ett annat team. Ägaren själv får lämna sin uppgift vidare nedåt (till exempel CEO till en departementschef).
  4. Grundarna får tilldela vem som helst.
  5. En juridisk hållning (SR-16) prövas före regeln, så att rätt skäl visas.
- **Motivering:** §51 kräver att uppgifter går till rätt ansvarig roll. Före ändringen kunde Research-chefen ge uppgifter till CFO och till sin egen chef, CEO.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-022 `manual`-provider: grundaren kör prompten i Claude och klistrar in svaret
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-25 · **Bygger på:** D-005, D-008, D-009, D-021
- **Beslut:**
  1. `kind = "manual"` är en tillåten leverantör i `config/providers.toml`. Den är avstängd som standard (bortkommenterad).
  2. Providern anropar inget API. Den lägger förfrågan i `<data_dir>/manual/<miljö>/` och väntar. En grundare (`founders`, D-021) läser den med `python -m aie manual show`, kör den själv i Claude och lämnar svaret med `python -m aie manual answer`. Nästa körning av samma förfrågan får svaret.
  3. Prompten lämnar datorn via grundaren, så providern räknas som extern och tar bara emot data som är klassad `public` (DR-13).
  4. Den har dagsgränser som alla andra leverantörer (ER-02). Svar med något som ser ut som en hemlighet avvisas (SR-10). Svaren och nekade försök revideras, men aldrig texten.
- **Motivering:** ROADMAP Fas 3 inför `manual`. D-005 tillät den men är ersatt av D-008, som inte nämner den. Grundarnas Claude-abonnemang används för hand och kostar inget extra, så D-009 (inga betalda API:er) gäller fortfarande.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-021 Grundarna står i konfigurationen; godkännandekön följer D-019
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Robin), 2026-10-23 · **Bygger på:** D-019, D-020
- **Beslut:**
  1. `config/system.toml` får den valfria nyckeln `founders`, en lista med grundarnas id (små bokstäver, siffror, `-` och `_`). Nu `["robin", "yorgo"]`. Godkännandekön startar inte med färre än två grundare.
  2. Det som ligger utanför en agents mandat eller över `HUMAN_APPROVAL_THRESHOLD` hamnar i grundarnas godkännandekö (migration 12, `approval_requests` och `approval_votes`). Kön räknar ut hur många som krävs enligt D-019: en grundare upp till gränsen, båda över den, och båda för ändringar i konstitution, gränser eller mandat.
  3. Varje grundare röstar högst en gång per förfrågan. Ett nej från en grundare avslår förfrågan och kräver en motivering.
  4. En tvist vars förslag bryter mot en hård gräns (§21) kan inte godkännas, inte ens av båda grundarna. Den kan bara avslås, eller så ändras gränsen först (D-019 punkt 3).
  5. Röster, godkännanden, avslag och nekade försök skrivs till revisionsloggen. Förfrågningar raderas aldrig, och en avgjord förfrågan ändras aldrig.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-020 Hierarkin i koden: nivåer per roll, fasta rapportvägar, skyddade styrverktyg
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-23 · **Bygger på:** D-017, D-019 · **Ändrar:** formatet för `permissions.toml` (D-017): ny obligatorisk nyckel `level`
- **Beslut:**
  1. Varje roll i `config/permissions.toml` har `level`: 1 är CEO, 2 kontrollfunktion, 3 departementschef och 4 arbetsagent (§8). Nivå 0 är grundarna och nivå 5 tillfälliga grupper. Ingen av dem är en roll.
  2. Registret kräver dessa rapportvägar:
     - CEO och kontrollfunktionerna (CFO, CRO, Compliance, Audit) rapporterar **direkt till grundarna**. Kontrollfunktionerna lyder inte under CEO, eftersom CEO annars kunde styra sin egen granskning (§8 nivå 2, §18).
     - En departementschef rapporterar till CEO.
     - En arbetsagent rapporterar till en chef på nivå 2 eller 3 i samma departement.
  3. Verktyg vars namn börjar med `governance.` (ändra konstitution, gränser eller mandat) kan stå i katalogen men aldrig ges till en roll. Ett sådant mandat är ett konfigurationsfel. Authorization Engine nekar dem alltid och loggar försöket (SR-04). Ändringarna görs bara av grundarna via PR, och enligt D-019 punkt 3 krävs båda.
  4. Ny roll `compliance` på nivå 2. Den behövs för SR-16 och flödet i D-011.
- **Godkänd av:** Yorgo ☑ (2026-10-26) · Robin ☑ (2026-10-25)

### D-019 Grundarnas beslutsrätt (besvarar Q-01)
- **Status:** Godkänd · **Föreslagen av:** Robin och Yorgo, 2026-10-23 · **Besvarar:** Q-01 · **Bygger på:** D-016
- **Beslut:**
  1. **En grundare räcker** för att godkänna en åtgärd vars belopp är högst `HUMAN_APPROVAL_THRESHOLD` i `config/risk_limits.toml`, och för en åtgärd utan belopp.
  2. **Båda grundarna krävs** för en åtgärd vars belopp är högre än `HUMAN_APPROVAL_THRESHOLD`.
  3. **Båda grundarna krävs alltid**, oavsett belopp, för ändringar i `CONSTITUTION.md`, i riskgränserna (`config/risk_limits.toml`) och i behörigheterna (`config/permissions.toml`).
  4. Gränsen står i konfigurationen, inte i det här beslutet. Att ändra den är en ändring i riskgränserna och kräver därför båda (punkt 3).
- **Följd:** `HUMAN_APPROVAL_THRESHOLD` är också gränsen för när en agent alls måste fråga en människa. Allt som eskaleras på grund av sitt belopp kräver därför båda grundarna. En grundare räcker för eskaleringar utan belopp eller under gränsen, till exempel en åtgärd utanför en agents mandat.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

---

## Fas 2 — föreslagna beslut

### D-018 ProviderRouter: `providers.toml`, kvoter i databasen, dataklasser i koden
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-23 · **Bygger på:** D-008, D-009
- **Beslut:**
  1. `config/providers.toml` listar leverantörerna i prioritetsordning: groq → openrouter → ollama → rule. Tillåtna typer är bara `groq`, `openrouter` (modellen måste sluta på `:free`), `ollama` och `rule`. Alla andra typer är ett konfigurationsfel tills D-009 öppnar för betalda API:er.
  2. Varje leverantör måste ha `daily_calls` och `daily_tokens` per UTC-dygn. En saknad gräns är ett fel (ER-02). Ett anrop räknas i databasen *innan* det skickas, och ett misslyckat anrop räknas också.
  3. En leverantör vars nyckel saknas i miljön hoppas över och står i listan över överhoppade. Nycklar står aldrig i filen (SR-10).
  4. Dataklasserna `public`, `internal`, `personal` och `secret` är fasta i koden. Externa leverantörer tar bara `public`, och konfigurationen kan inte ändra det (DR-13).
  5. Varje leverantör provas högst en gång per förfrågan. När ingen är kvar kastas `NoProviderAvailable` och arbetet köas. Det finns aldrig någon betald reserv.
  6. Audit-loggen får leverantör, modell, tokens, dataklass och kostnad 0 per anrop, men aldrig prompt eller svar.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-017 Behörighetsmodell: rollmandat i `permissions.toml`, default deny, styrd livscykel
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-23 · **Bygger på:** D-007
- **Beslut:**
  1. `config/permissions.toml` har en katalog `[tools]` över alla verktyg och ett mandat `[roles.<roll>]` per roll, med departement och en uttrycklig verktygslista. Ett verktyg som inte står i katalogen kan ingen roll få, så ett stavfel blir ett fel vid uppstart.
  2. Authorization Engine nekar allt som inte uttryckligen är tillåtet. Den kontrollerar i ordning: verktyget finns, agenten finns, agenten får agera, TESTING bara i sim (SR-13) och att verktyget ingår i mandatet.
  3. Varje beslut skrivs till audit-loggen. Går det inte att logga blir svaret nej (§59).
  4. Livscykelns övergångar är fasta i koden (`agents/lifecycle.py`). SUSPENDED går tillbaka via PROBATION, aldrig direkt till ACTIVE. RETIRED är slutgiltigt.
  5. En agent kan inte ändra sin egen status (SR-03). Varje ändring kräver en motivering och sparas i historiken.
  6. Mandaten ändras bara via PR, aldrig medan systemet kör.
- **Ännu inte med:** registret sparas i databasen och dataklassningen (DR-13) tillkommer när Fas 1 är klar. Detsamma gäller ProviderRouter.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

---

## Fas 1 — föreslagna beslut

### D-016 Under byggfaserna mergar författaren sin egen PR när alla tester är gröna
- **Status:** Godkänd · **Föreslagen av:** Robin och Yorgo, 2026-10-23 · **Ändrar:** D-004 (punkten "den andra grundaren granskar")
- **Beslut:** Under byggfaserna mergas en PR av den som skrev den när alla tester är gröna. Ingen granskning av den andra grundaren behövs. Besluten fattas gemensamt på plats.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-015 `log_level` är en valfri inställning i `system.toml`
- **Status:** Godkänd · **Föreslagen av:** Robin, 2026-10-23 · **Bygger på:** D-003, D-013
- **Beslut:**
  1. `config/system.toml` får nyckeln `log_level` med något av värdena `DEBUG`, `INFO`, `WARNING`, `ERROR` eller `CRITICAL` (versaler).
  2. Nyckeln är valfri. Saknas den gäller `INFO`, så att äldre konfigurationer fortfarande är giltiga.
  3. Ett annat värde är ett konfigurationsfel som stoppar uppstart (FR-02).
  4. Loggfilen `<log_dir>/aie.log` roteras vid 5 MB och högst tre gamla filer sparas. Det är fasta värden i koden; att göra dem konfigurerbara kräver ett nytt beslut.
- **Motivering:** Nivån behöver kunna sänkas till `DEBUG` vid felsökning utan kodändring. Rotationen hindrar att loggarna fyller disken när systemet körs länge.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-014 GitHub-repot är publikt
- **Status:** Godkänd · **Föreslagen av:** Robin, 2026-10-23 · **Ändrar:** D-004 (ordet "privat")
- **Bakgrund:** Repot `robin100a541-prog/AI-Eco-systems`, där `ai-enterprise/` ligger, är publikt på GitHub. D-004 utgår från ett privat repo.
- **Beslut:** Repot får vara publikt. Därför läggs aldrig hemligheter, personuppgifter (e-post, telefon, adress, personnummer), privata belopp eller kontouppgifter i repot. Det gäller även `docs/conversations/` och `docs/environment.md`, som alla kan läsa.
- **Väntar på:** Inget; godkänd av båda grundarna (2026-10-23, beslutat gemensamt på plats).
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-013 Format och valideringsregler för konfigurationen
- **Status:** Godkänd · **Föreslagen av:** Claude (session med Yorgo), 2026-10-21 · **Bygger på:** D-003, D-006, D-009
- **Beslut:**
  1. `config/risk_limits.toml` är en platt fil. Nyckeln `currency` gäller alla belopp i filen och måste vara samma som `base_currency` i `system.toml`.
  2. Belopp är heltal i minsta enhet (öre/cent), `>= 0`. Flyttal och `true`/`false` avvisas.
  3. `MAX_TOTAL_DRAWDOWN`, `REINVESTMENT_POLICY` och `API_REINVEST_SHARE` är **procentsatser** (0–100). Övriga gränser är belopp. Konstitutionen §25 anger inte enheten, så det här är ett förslag.
  4. `REINVESTMENT_POLICY` är tills vidare en enda procentsats av realiserad nettovinst. En rikare policy kräver ett nytt beslut.
  5. En saknad gräns är en varning i `sim` och ett fel i `prod`. Okänd miljö behandlas som `prod`. En saknad gräns blir `None` och betyder alltid "blockera" (ER-02).
  6. Nycklar som slutar på `_KEY`, `_TOKEN`, `_SECRET` eller `_PASSWORD`, eller heter `password`, `key`, `token` eller `secret`, avvisas i alla `config/*.toml`. Det gäller även filer som `.env` och `*.secret` i `config/` (SR-10).
  7. `config_version = 1` är den enda version som stöds.
- **Motivering:** Det ska vara omöjligt att av misstag stänga av en gräns, till exempel genom ett stavfel eller ett glömt värde, eller att blanda simulerade och verkliga pengar.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

---

## Fas 0 — föreslagna beslut

### D-001 Konstitutionen är styrande dokument
- **Status:** Godkänd · **Föreslagen av:** Claude (för Yorgo), 2026-10-21
- **Beslut:** `CONSTITUTION.md` (v1.0) är projektets grunddokument. Ändringar kräver nytt beslut och ny version.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-002 Programmeringsspråk: Python ≥ 3.11, endast standardbibliotek i MVP
- **Status:** Godkänd
- **Motivering:** Gratis, plattformsoberoende, `sqlite3`/`tomllib`/`decimal`/`unittest` täcker MVP. Noll tredjepartslicenser.
- **Alternativ som övervägts:** TypeScript/Node (fler beroenden), Go (mindre AI-ekosystem).
- **Konsekvens:** Nya beroenden kräver eget beslut med licens och kostnad.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-003 Lagring: SQLite, en fil per miljö; konfiguration i TOML
- **Status:** Godkänd
- **Motivering:** Ingen server, ingen kostnad, transaktionssäker, lätt att säkerhetskopiera. TOML läses av standardbiblioteket.
- **Avvikelse från konstitutionens förslag:** `config/*.yaml` → `config/*.toml` (konstitutionen tillåter anpassning, §45).
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-004 Samarbete: privat GitHub-repo är enda sanningskällan
- **Status:** Godkänd
- **Beslut:** Ett privat repo `ai-enterprise` på GitHub Free. Båda grundarna är medarbetare. Arbetsflöde: egen gren per uppgift → pull request → den andra grundaren granskar → merge till `main`. `main` ändras aldrig direkt.
- **Claude-projektet "Ai Ecosystem"** i Yorgos konto innehåller bara en kopia för bekvämlighet. Vid konflikt gäller repot.
- **Motivering:** GitHub Free tillåter obegränsade privata repon med obegränsat antal medarbetare utan kostnad. Två separata Claude-konton delar ingen historik (§46), git gör det.
- **Godkänd av:** Yorgo ☑ · Robin ☑ (2026-10-23, beslutat gemensamt på plats, registrerat av Robin)

### D-011 Agenterna undersöker själva nya kanaler och lösningar — människor godkänner
- **Status:** Föreslagen · **Föreslagen av:** Yorgo (idé), formulerat av Claude, 2026-10-21
- **Bakgrund:** Frågor som "vilka plattformar kan vi sälja på" och "hur hanteras skatten där" ska systemet kunna utreda självt.
- **Beslut:** Research-avdelningen får en återkommande uppgiftstyp **"Utred möjlighet"** (ny kanal, intäktsväg, verktyg, gratis-API, skatte- eller regelfråga). Resultatet blir alltid en ifylld post i ett register (för kanaler: `docs/channels.md`, i systemet en databastabell) med källor och datum. Flödet:
  1. Research undersöker (endast läsande webbåtkomst, gratis modeller).
  2. Compliance granskar villkor, AI-regler, automationsregler och skatt. Osäkerhet räknas som risk, inte som "OK" (§17).
  3. CFO räknar avgifter, skattespår och förväntat netto.
  4. Grundarna godkänner innan första användning av en ny kanal eller ny skatteväg.
- **Verifiering (§29):** ett svar från en agent registreras som *obekräftad hypotes* med källor. Öppna frågor som ännu inte utretts ligger i `research/QUESTIONS.md`. Svar som rör lag, skatt eller plattformsvillkor blir operativ regel först när Compliance kontrollerat källan **och** en grundare godkänt det.
- **Gränser:** agenterna får föreslå, men inte själva skapa konton, godkänna villkor, välja skattespår eller tolka lagen slutgiltigt. Skattefrågor som påverkar deklarationen bekräftas av Skatteverket eller en rådgivare.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-012 Allt från Claude-sessioner arkiveras i repot
- **Status:** Föreslagen · **Föreslagen av:** Yorgo, 2026-10-21
- **Beslut:** Varje Claude-session som påverkar projektet sparas som en fil i `docs/conversations/` (datum, grundare, ämne). Filen är ett arkiv, inte en regel — det som gäller står fortfarande i DECISIONS.md, ARCHITECTURE.md och REQUIREMENTS.md (§2, §46). Båda grundarna följer samma rutin.
- **Godkänd av:** Yorgo ☑ (begärt i chatten 2026-10-21) · Robin ☐

### D-010 Skatt hanteras utan att registrera aktiebolag; systemet räknar och reserverar skatt
- **Status:** Föreslagen · **Föreslagen av:** Claude på Yorgos begäran, 2026-10-21
- **Bakgrund:** Grundarna vill inte öppna ett företag men vill att skatt ska vara inkluderad. Skyldigheten att skatta försvinner inte, men det finns lagliga vägar där ni inte behöver starta aktiebolag eller registrera enskild firma. Vilken väg som gäller beror på **vad** AI:n faktiskt tjänar pengar på. Det avgör Skatteverket utifrån verksamheten, inte ett eget val. Detta är inte skatterådgivning; bekräfta med Skatteverket innan Fas 7.
- **Beslut (förslag):** Systemet får ett **skattespår per intäktstyp** och tilldelar varje intäkt ett spår i ledgern:

| Spår | När det passar | Vem sköter skatten | Ni behöver göra |
|---|---|---|---|
| **A. Investeringssparkonto (ISK)** | AI:n investerar i värdepapper | Banken rapporterar schablonintäkten; enskilda affärer deklareras inte | Var och en öppnar ett eget ISK (kan inte ägas gemensamt eller av företag). Kapitalet delas i två konton. |
| **B. Egenanställning** | AI:n utför uppdrag åt kunder (texter, kod, analyser) | Egenanställningsföretaget fakturerar, betalar arbetsgivaravgifter och drar skatt; ni får lön | Avtal med ett egenanställningsföretag (de tar provision — en kostnad som ska godkännas). Kontrollera att de accepterar typen av uppdrag. |
| **C. Enkelt bolag** | Löpande gemensam försäljning (t.ex. digitala produkter) | Ingen skatt på bolaget; var och en deklarerar sin andel på NE-bilaga | Inget bolag att "öppna" och ingen avgift. Registrering är frivillig. Bokföring krävs — **systemets ledger byggs för att uppfylla det**. |
| **D. Hobby (T2)** | Bara om verksamheten saknar vinstsyfte | Ni deklarerar överskott på T2 | Passar troligen inte: konstitutionens mål är vinst, och vinstsyftet är Skatteverkets främsta skiljelinje. |

- **Tillägg 2026-10-21 (Yorgos förslag): försäljningsplattformar som Gumroad och Etsy.** En plattform är en *försäljningskanal*, inte ett eget skattespår. Inkomsten är fortfarande er och deklareras via spår C (eller D om det verkligen är hobby). Men plattformarna förenklar mycket:

| | Gumroad | Etsy |
|---|---|---|
| Passar för | Digitala produkter (mallar, guider, kod, kurser) | Digitala nedladdningar och fysiska produkter med "designed by"-ursprung |
| Avgifter | 10 % + 0,50 USD per direktförsäljning; 30 % via Gumroads Discover; ingen månadsavgift | 0,20 USD per annons (förnyas var 4:e månad), 6,5 % transaktionsavgift + betalningsavgift; Offsite Ads 12–15 % vid sådan försäljning |
| Moms mot köpare | Gumroad är *merchant of record* och tar in och betalar moms/sales tax där de har skyldighet | Etsy tar in och betalar moms/sales tax som marknadsplats där det gäller (detaljer för EU ska kontrolleras) |
| AI-regler | Kontrolleras i villkoren innan start | AI-skapade varor tillåts som "Seller-prompted AI creations" men **AI-användning måste anges i annonsen**; "AI prompt bundles" är inte tillåtna |

  **Fiverr (tillagt på Yorgos förslag):** säljer *tjänster* (uppdrag åt kunder: texter, kod, design, analyser), inte färdiga produkter. Fiverr behåller 20 % av varje order. Fiverr tillåter AI som verktyg men kräver att frilansaren är fullt ansvarig för det som levereras; generiskt, oredigerat AI-material godkänns inte, och om kunden uttryckligen vill ha arbete utan AI måste arbetsflödet redovisas. Att ge en falsk bild av AI-användning kan leda till återbetalning och permanent avstängning. Det är **oklart om en AI får sköta kundkontakten automatiskt** — därför ska varje meddelande till kund och varje leverans godkännas av den grundare som äger kontot tills frågan är utredd (R-03 i `research/QUESTIONS.md`). Tjänster rapporteras enligt DAC7 från första euron.

  Viktigt: plattformar rapporterar säljares intäkter till skattemyndigheten enligt EU:s DAC7 (från inkomstår 2023). Säljare av varor undantas bara under 30 försäljningar *och* under 2 000 euro per år. Skatteverket får alltså uppgifterna — systemet ska därför alltid kunna visa samma siffror.
  Kontot måste ägas och verifieras av en av grundarna (inte av AI:n). Om ni driver det tillsammans som enkelt bolag registrerar ledgern fördelningen mellan er.
- **Konsekvenser för systemet:** Tax Engine (ny modul) som (1) märker varje intäkt med spår, (2) reserverar beräknad skatt automatiskt som ett åtagande så att pengarna inte kan investeras, (3) bevakar momsgränsen 120 000 kr/år, (4) arkiverar underlag i 7 år, (5) genererar underlag till varje grundares deklaration. Reserverad skatt räknas aldrig som disponibelt kapital.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-009 Betalda API:er får finansieras av realiserad vinst — enligt regel
- **Status:** Föreslagen · **Föreslagen av:** Claude på Yorgos begäran, 2026-10-21
- **Beslut:** Betalda API:er är en egen budgetkategori `API_SPEND`. Den är **0 kr tills** systemet har realiserad nettovinst (efter reserverad skatt). Därefter får högst `API_REINVEST_SHARE` av realiserad nettovinst användas till API:er. Varje nytt betalt API kräver ett affärsförslag (§12) som visar att det förväntas ge mer än det kostar, samt yttrande från CFO och CRO. Belopp över `HUMAN_APPROVAL_THRESHOLD` kräver grundarnas godkännande. Varje API-nyckel får en hård utgiftsgräns hos leverantören när sådan finns.
- **Parametrar som grundarna sätter:** `API_REINVEST_SHARE` (förslag 20 %), `API_MONTHLY_CAP`.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-008 Gratis språkmodeller från start, med flera leverantörer och lokal reserv
- **Status:** Föreslagen · **Ersätter:** D-005 · **Föreslagen av:** Claude på Yorgos begäran, 2026-10-21
- **Beslut:** Agenterna använder riktiga språkmodeller från Fas 2 via en `ProviderRouter` som bara anropar gratisalternativ:
  1. **Groq gratisplan** (primär): t.ex. `openai/gpt-oss-120b` och `openai/gpt-oss-20b`, Groqs tabell visar cirka 1 000 anrop/dag och 200 000 tokens/dag per modell, men anger att exakta gratisgränser kan skilja sig och visas i ert konto — `llm_smoke_test.py` skriver ut de faktiska kvothuvudena.
  2. **OpenRouter `:free`-modeller** (sekundär): 20 anrop/min, 50/dag utan köpta krediter.
  3. **Ollama lokalt** (reserv, MIT-licens): obegränsat men beror på hårdvara.
  4. Google Gemini gratisnivå används bara som tillägg; Google har sänkt gratisgränserna kraftigt och säger att nivån är avsedd för tidig testning.
- **Regler i koden:** varje leverantörs dagskvot räknas i databasen; när den tar slut går routern till nästa; när alla är slut pausar agenterna (de betalar aldrig). Kunddata, personuppgifter och hemligheter skickas aldrig till gratis-API:er — gratisnivåer kan ha villkor om att data används för att förbättra tjänsten (kontrolleras per leverantör innan den aktiveras).
- **Konsekvens:** Med några tusen anrop per dag arbetar agenterna i schemalagda arbetscykler, inte i oavbruten chatt.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-005 Ingen automatisk modellanvändning från kod i MVP
- **Status:** Ersatt av D-008
- **Beslut:** MVP använder `rule`-provider (deterministisk). `manual`-provider (grundare kör prompten i Claude och klistrar in svaret) tillåts från Fas 3. API och automatiserad Claude Code-körning är **inte** godkända.
- **Motivering:** Pro inkluderar inte API-krediter; API faktureras separat. Pro-gränser delas mellan chatt och Claude Code. Se ARCHITECTURE.md §3.3.
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-006 Belopp lagras som heltal i minsta enhet + valutakod; simulering använder valutan `SIM`
- **Status:** Föreslagen
- **Motivering:** Inga avrundningsfel (ER-01). `SIM` kan tekniskt inte summeras med verklig valuta (ER-15).
- **Godkänd av:** Yorgo ☐ · Robin ☐

### D-007 Agenter har inga egna verktyg — allt går via kontrollkedja och Tool Gateway
- **Status:** Föreslagen
- **Beslut:** Agenter returnerar `ActionRequest`. Ordning: KillSwitch/Mode → Authorization → Budget → Risk → HumanApproval → Tool Gateway. Default deny. Varje steg loggas.
- **Godkänd av:** Yorgo ☐ · Robin ☐

---

## Öppna frågor som kräver grundarbeslut

| ID | Fråga | Behövs före | Förslag från Claude |
|---|---|---|---|
| Q-01 | ~~Hur är beslutsmakten fördelad mellan Yorgo och Robin?~~ **Besvarad av D-019 (2026-10-23).** | Fas 3 | — |
| Q-02 | Vilka datorer/OS har ni? (Besvaras av `check_env.py`) | Fas 1 | — |
| Q-03 | Valuta för verkligt kapital (SEK?) | Fas 4 | SEK |
| Q-04 | Värden för de 10 parametrarna i §25 | Fas 7 (simulerade värden räcker till dess) | Sätts först efter Fas 6-resultat |
| Q-05 | Vilket skattespår (D-010) gäller för pilotens intäkter? Bekräftas med Skatteverket (gratis via telefon eller skriftlig fråga) innan riktiga pengar används. | Fas 7 | Välj spår när pilotens affärsområde (Q-08) är känt. |
| Q-06 | Vem av er skapar gratiskonton hos Groq och OpenRouter, och har någon dator hårdvara för Ollama? | Fas 2 | Båda kör `llm_smoke_test.py`. |
| Q-07 | Var körs produktionsdatabasen när systemet är i drift — hos vem av er, och hur säkerhetskopieras den? | Fas 7 | — |
| Q-08 | Vilket affärsområde ska piloten testa? | Fas 6 | Väljs utifrån simuleringsresultat. |
