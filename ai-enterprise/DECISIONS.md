# DECISIONS — beslutslogg

Regler: nya beslut läggs **överst i sin sektion** med nästa lediga ID. Ett beslut ändras aldrig i efterhand — det ersätts av ett nytt beslut som hänvisar till det gamla ("Ersätter D-00X"). Status: `Föreslagen` → `Godkänd` / `Avvisad` / `Ersatt`.

Ett beslut räknas som **Godkänt** först när den/de som har beslutsrätt har skrivit sitt namn och datum i fältet *Godkänd av*. Eftersom beslutsfördelningen mellan grundarna ännu inte är fastställd (Q-01) kräver Fas 0-besluten tills vidare **båda** grundarnas godkännande.

---

## Fas 3 — beslut

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
