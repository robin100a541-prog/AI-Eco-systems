# Beslut som väntar på godkännande (2026-10-26)

Ett underlag för Yorgo och Robin att gå igenom tillsammans. **Inget här är godkänt.** Själva besluten
står i [DECISIONS.md](../DECISIONS.md). Där fyller ni i *Godkänd av* när ni har bestämt er. Alla sju
kräver båda grundarna.

Ett nej eller en ändring görs alltid på samma sätt: ni skriver ett nytt beslut som ersätter det gamla
(reglerna i DECISIONS.md), och sedan ändras koden i en PR. Koden finns redan i `main`. Ett nej betyder
alltså att koden ändras eller kopplas ur, inte att något försvinner av sig självt.

| Beslut | Kort | Rekommendation |
|---|---|---|
| D-032 | Tax Engine: skattespår och skattereserv. **Innehåller en behörighetsändring.** | Godkänn |
| D-033 | Momsgränsen: varning vid 80 %, stopp vid gränsen | Godkänn |
| D-034 | Skatteunderlag: inget raderas, export per grundare | Godkänn |
| D-038 | Lärdomsregister: fem steg, regel kräver båda | Godkänn |
| D-039 | Versionerade strategier: återställning utan att historiken försvinner | Godkänn |
| D-040 | SR-17: avstängning bara med dokumenterade skäl | Godkänn |
| D-041 | `aie start` startar inte utan spärrarna | Godkänn |
| D-042 | Simulering: startkapital, seedad marknad, scenarier, bara i sim (tillagt 2026-10-27) | Godkänn |
| D-043 | Arbetscykeln: agenterna föreslår, spärrarna avgör (tillagt 2026-10-27) | Godkänn |
| D-044 | Agenternas verktyg i simuleringen. **Behörighetsändring** (tillagt 2026-10-27) | Godkänn |

---

## D-032 Tax Engine: skattespår per intäkt och försiktig skattereserv

> ⚠️ **BEHÖRIGHETSÄNDRING:** `config/permissions.toml` får ett nytt verktyg, `tax.assign`, och **CFO**
> får det. Med verktyget kan CFO märka en intäkt med skattespår. Inga andra roller får det. Det ändrar
> inte vilket spår Skatteverket godtar, och CFO kan inte flytta pengar med det.

**Vad det innebär.** Varje intäkt märks med ett av de fyra spåren i D-010 (ISK, egenanställning, enkelt
bolag, hobby) och fördelas mellan er. Systemet reserverar en uppskattad skatt som ett åtagande, så att
pengarna inte kan spenderas. En intäkt utan spår reserveras med den högsta satsen. Satserna i
`config/tax.toml` är **simulerade**. Spåren själva (D-010, Q-05) är fortfarande öppna tills ni har stämt
av med Skatteverket.

**Om ni säger nej eller vill ändra.**
- Andra satser eller en annan fördelning i enkelt bolag (nu 50/50): ändra `tax.toml` i en PR. Inget nytt beslut behövs, eftersom satserna är simulerade.
- Inte låta CFO märka spår: ta bort `tax.assign` från CFO. Då märker bara ni grundare.
- Nej till hela beslutet: budgetmotorn kopplas ur Tax Engine. Då räknas ingen skatt som åtagande, och återinvesterbar vinst blir 0 igen (D-027).

**Rekommendation: godkänn.** Reserven gör systemet försiktigare, inte mindre försiktigt. CFO är den
naturliga rollen för att märka spår, och ni kan alltid ändra märkningen med en motivering.

## D-033 Momsgränsen

**Vad det innebär.** Systemet följer årets försäljning mot momsgränsen (120 000 kr, simulerat i `SIM`).
Vid 80 % får ni och CFO en varning. Vid gränsen stoppas *ny* försäljning tills ni **båda** har röstat
för att fortsätta, till exempel efter en momsregistrering. Försäljning som redan har skett registreras
som vanligt.

**Om ni säger nej eller vill ändra.**
- En annan varningsnivå: ändra `vat_warning_percent` i `tax.toml`.
- Att en grundare räcker: det kräver ett nytt beslut som ersätter punkt 3.
- Nej till hela beslutet: spärren kopplas ur, och då finns ingen automatisk bevakning av momsgränsen (ER-20 är då inte uppfyllt).

**Rekommendation: godkänn.** Att passera momsgränsen påverkar er båda, så två röster är rimligt.

## D-034 Skatteunderlag

**Vad det innebär.** Ingenting i ledgern eller skattetabellerna kan raderas, så underlaget finns kvar i
minst 7 år. Varje grundare kan exportera ett deklarationsunderlag per år som en JSON-fil. Exporten
loggas med en kontrollsumma, så att man kan visa att filen inte har ändrats.

**Om ni säger nej eller vill ändra.**
- Ett annat format (till exempel CSV) eller andra fält: en ändring i koden, inget nytt beslut.
- Att underlag ska kunna raderas efter 7 år: det kräver ett nytt beslut, och raderingsskyddet i databasen måste ändras.

**Rekommendation: godkänn.** Det uppfyller ER-21 och går att visa upp mot Skatteverkets uppgifter (DAC7).

## D-038 Lärdomsregister

**Vad det innebär.** Lärdomar sparas med källa och går upp i fem steg: hypotes, preliminär, testad,
reproducerbar och regel. Varje steg kräver mer: en oberoende granskare, ett test, två test, och för en
regel att ni **båda** röstar för. Bara godkända regler får ändra gemensamma regler. En obekräftad
hypotes kan aldrig bli en regel av sig själv.

**Om ni säger nej eller vill ändra.**
- Att en grundare räcker för en regel, eller att färre test räcker: ett nytt beslut, plus en liten kodändring.
- Nej till hela beslutet: då saknas ett lärdomsregister, och acceptanskriterierna 3 och 5 i §53 är inte uppfyllda. Fas 5 öppnas igen.

**Rekommendation: godkänn.** Det följer §29 och §53 rakt av.

## D-039 Versionerade strategier

**Vad det innebär.** Strategier och agentversioner (modell, instruktioner) sparas som numrerade
versioner med motivering. Att återställa en gammal version skapar en ny version, så att historiken
aldrig försvinner. En ändring som ska gälla som regel för alla måste bygga på en godkänd regel (D-038)
och göras av en grundare.

**Om ni säger nej eller vill ändra.**
- Andra krav på vem som får ändra strategier: ett nytt beslut.
- Nej till hela beslutet: då kan strategiförändringar inte återställas, och acceptanskriterium 4 i §53 är inte uppfyllt.

**Rekommendation: godkänn.**

## D-040 SR-17: avstängning bara med dokumenterade skäl

**Vad det innebär.** En agent som arbetar kan bara stängas av eller avvecklas genom ett ärende som anger
skäl ur §33 och visar underlag som systemet kontrollerar. Det kan vara en verifierad incident där agenten
var involverad, eller ett försök att använda ett verktyg utanför sitt mandat. Det agenten har *kommit
fram till* (rapporter, beslut, tvister) räknas aldrig. Avstängning beslutas av en grundare och
avveckling av er båda. Agenten kan yttra sig i ärendet.

> Obs: beslutet ändrar Yorgos registerkod (`AgentRegistry.set_guard`). När spärren är kopplad, som den
> är i `aie start`, går det inte längre att stänga av en arbetande agent direkt.

**Om ni säger nej eller vill ändra.**
- Att en grundare räcker även för avveckling, eller att agenten inte ska yttra sig: ett nytt beslut.
- Nej till hela beslutet: spärren kopplas ur, och då är SR-17 inte uppfyllt.

**Rekommendation: godkänn.** Det skyddar revisions- och riskagenter mot att stängas av för obekväma fynd (§31).

## D-041 `python -m aie start` startar inte utan spärrarna

**Vad det innebär.** När systemet startar kopplas allt ihop: nödstopp, skyddat läge, stop-loss,
skattereserv, momsgräns, incidenter, prognoser, lärdomar, strategier och SR-17. Saknas en
konfigurationsfil för spärrarna, eller är den fel, startar systemet inte. Medan systemet kör körs
kontrollerna regelbundet. Stop-loss börjar mätas först när kapital finns i ledgern.

**Om ni säger nej eller vill ändra.**
- Att systemet ska starta med varning när en fil saknas: ett nytt beslut. Det bryter mot försiktighetsprincipen i §59, så det avråder jag från.
- Att stop-loss ska mätas även utan kapital: en liten kodändring. Då löser stop-loss ut direkt på ett tomt system.

**Rekommendation: godkänn.** Det är förutsättningen för Fas 6b, eftersom agentkörningar ska ske med alla spärrar på.

---

## D-042 Simulering (tillagt 2026-10-27)

**Vad det innebär.** En simulering startas bara i `sim` med `SIM`, av en grundare och i en tom datamapp.
Startkapitalet blir `START_CAPITAL`. Marknaden har en fast seed, så samma scenario ger samma resultat.
Varje order bokförs som en vanlig ledgerpost, och spärrarna pausar försäljningen. Simuleringen får
märka skattespår i sim, vilket ändrar D-032 punkt 3.

**Om ni säger nej eller vill ändra.**
- Andra scenarier eller värden: ändra filerna i `config/scenarios/`.
- Att simuleringen inte ska få märka skattespår: intäkterna blir utan spår och reserveras med den högsta satsen.

**Rekommendation: godkänn.**

## D-043 Arbetscykeln (tillagt 2026-10-27)

**Vad det innebär.** Varje simulerad dag får agenterna läget och svarar med förslag i ett fast format.
Varje förslag kontrolleras av samma spärrar som i riktig drift, och bara det som får ja genomförs.
Ett affärsförslag måste ha alla 11 fält i §12. När CFO och CRO är oense hålls initiativet tills CEO har
avgjort. I CI är agenterna skriptade. Lokala modeller kan användas manuellt, och externa modeller
används aldrig.

**Om ni säger nej eller vill ändra.**
- Andra åtgärdstyper eller roller: ett nytt beslut, plus en kodändring.
- Nej till hela beslutet: då finns ingen arbetscykel, och Fas 6 kan inte testas mot agenter.

**Rekommendation: godkänn.**

## D-044 Agenternas verktyg i simuleringen (tillagt 2026-10-27)

> ⚠️ **BEHÖRIGHETSÄNDRING** i `config/permissions.toml`: fyra nya verktyg, `sim.spend`, `sales.list`,
> `forecast.make` och `proposal.submit`.
> - Research-chefen får alla fyra.
> - Forskaren får `forecast.make` och `proposal.submit`.
> - CEO och CFO får `forecast.make`.
> - Kontrollfunktionerna får inga nya verktyg.

**Vad det innebär.** Utan verktygen kan agenterna inte göra något i simuleringen. Verktygen flyttar
inga riktiga pengar. Varje utgift går genom budgetmotorn och bokförs i `SIM`.

**Om ni säger nej eller vill ändra.**
- Färre roller: ta bort verktyget från rollen i `permissions.toml`. Då nekas rollens åtgärder.
- Nej till hela beslutet: verktygen tas bort, och arbetscykeln kan bara skriva rapporter.

**Rekommendation: godkänn.**

---

**Kom ihåg:** överlämningen i `TODO.md` gällde bara 2026-10-26. Från 2026-10-27 gäller den vanliga
fördelningen igen. Skattefrågorna (D-010, Q-05) är fortfarande öppna och förblir simulerade tills ni har
stämt av med Skatteverket.
