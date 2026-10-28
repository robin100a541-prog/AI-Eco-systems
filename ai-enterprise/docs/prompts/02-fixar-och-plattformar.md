# Arbetsorder 02 — fixar och plattformar

Klistrad in av Yorgo i en Claude Code-session 2026-10-28. Sparad oförändrad enligt arbetsordern (D-012).
Läget i repot vid start, verifierat av sessionen:
- main var på `a086130`, inte `083bb25`. PR #68–#79 hade tillkommit.
- D-049 ("grundarna agerar som en") ersätter D-019 punkt 2 och 3. En grundares godkännande räcker, men skyddade filer kräver fortfarande etiketten `founder-approved` (D-049 punkt 5).
- `DECISIONS.md`, `risk_limits.toml`, `permissions.toml` och `CONSTITUTION.md` är skyddade av CI-kontrollen `protected-files`.

---

ARBETSORDER — AI-ECO-SYSTEMS Rätta, automatisera, validera och bygg ett lönsamt, plattformsoberoende AI-företag
Du arbetar direkt i repot AI-Eco-systems, projektet ai-enterprise/.
Ditt uppdrag är att ta det befintliga systemet från dess nuvarande tillstånd till ett stabilt, säkert och testbart AI-agentekosystem som självständigt kan hitta, utvärdera och förbereda affärsmöjligheter på flera plattformar.
Systemet ska kunna:

* undersöka marknaden,
* jämföra möjligheter,
* skapa produkter eller tjänsteerbjudanden,
* simulera ekonomiska resultat,
* mäta verkliga resultat,
* förbättra sina beslut över tid.

Grundarnas huvudmål är ett fungerande system med så lite manuellt arbete och så nära noll kronor i nya kostnader som möjligt. De vill inte hantera varje agent, felsöka varje problem själva eller fatta onödiga beslut. Du ska själv utföra allt tekniskt arbete som ryms inom godkända beslut och befintliga behörigheter.
Du ska inte bara analysera, föreslå eller planera. Du ska implementera, testa, dokumentera och verifiera.
Arbeta i små, isolerade PR:er. Bevara det som fungerar. Ta inga genvägar med säkerheten.
DEL 1 — PRIORITERINGAR
Prioritera alltid i denna ordning:

1. Ekonomisk och teknisk säkerhet.
2. Korrekt och verifierbar funktion.
3. Så låga kostnader som möjligt.
4. Så lite manuellt arbete som möjligt.
5. Autonomi och automatisering.
6. Verklig efterfrågan och lönsamhet över tid.
7. Enkelhet, underhållbarhet och skalbarhet.

Optimera inte för att systemet ska se färdigt ut. Optimera för att det faktiskt fungerar.
Ett testresultat, en simulering, en agentrapport eller ett förslag bevisar inte att en affärsidé fungerar i verkligheten.
Skilj alltid mellan:

* implementerat,
* testat och verifierat,
* simulerat,
* föreslaget,
* väntar på godkännande,
* verifierat i verkligheten.

Hitta aldrig på testresultat, marknadsdata, intäkter, källor eller genomförda åtgärder.
DEL 2 — GRATIS FÖRST, ALLTID
Målet är 0 kr i nya kostnader under utveckling och testning.
Innan du inför en ny tjänst, ett nytt beroende, ett API eller ny infrastruktur ska du undersöka om det finns en kostnadsfri lösning som uppfyller samma krav.
Prioritera i denna ordning:

1. Pythons standardbibliotek.
2. Befintlig infrastruktur och befintliga beroenden.
3. Gratis AI-modeller och API-nivåer med verifierade villkor.
4. Verktyg med öppen källkod.
5. Gratis marknads- och produktresearch.
6. Organisk distribution och gratis trafikkanaler.
7. Gratis hosting, databaser och automatisering, så länge användningsvillkoren räcker.
8. Lokala eller manuellt startade jobb när kontinuerlig drift annars skulle kosta pengar.

Python-projektet använder bara standardbiblioteket. Lägg inte till nya paket.
Det här är förbjudet utan uttryckligt godkännande från båda grundarna:

* betalda API-anrop,
* nya abonnemang,
* betald hosting,
* användning av betalkrediter,
* köp av annonser,
* betalda domäner,
* andra nya kostnader.

Utgå inte från att en tjänst är gratis bara för att den har en gratisnivå. Kontrollera:

* faktiska kostnader,
* användningsgränser,
* utgångsdatum,
* krav på betalkort,
* övriga begränsningar.

En gratistjänst som kräver betalkort får inte bli en nödvändig del av systemet utan godkännande.
Om gratisalternativet inte räcker väljer du det billigaste alternativet som inte medför nya kostnader, eller dokumenterar begränsningen.
AI-modeller
Undersök gratisalternativ som Groq och andra lämpliga leverantörer. Verifiera aktuell tillgång och aktuella villkor innan du bygger beroenden på dem.

* Gå via ProviderRouter.
* Använd kvoter och gränser.
* Pausa agenterna när gratiskvoten är slut.
* Byt aldrig tyst till en betald modell.
* Hantera fel, tidsgränser och rate limits, med ett begränsat antal återförsök.
* Undvik onödiga modellanrop, och cacha svar där det är lämpligt.
* Använd mockar i deterministiska tester.
* Redovisa tydligt vilka tester som använder en riktig modell.
* Ett modellsvar är aldrig bevis för att en handling har utförts. Verifiera handlingar med konsekvenser oberoende av modellen.

Sätt aldrig ANTHROPIC_API_KEY.
Systemet får inte förutsätta att Claude Pro ger gratis API-tillgång eller obegränsad drift av externa agenter.
Autonomin måste anpassas till den infrastruktur som faktiskt finns. Om kontinuerlig drift kräver betald hosting implementerar du det bästa kostnadsfria alternativet, till exempel schemalagda eller manuellt startade jobb. Påstå aldrig att agenterna körs kontinuerligt om infrastrukturen inte gör det.
DEL 3 — LÄS REPOT OCH BEVARA BESLUTEN
Läs dessa filer i denna ordning:

1. CLAUDE.md
2. TODO.md
3. ai-enterprise/CONSTITUTION.md
4. ai-enterprise/PROJECT_STATUS.md
5. ai-enterprise/DECISIONS.md
6. ai-enterprise/ROADMAP.md
7. ai-enterprise/docs/channels.md
8. ai-enterprise/research/QUESTIONS.md

Verifiera sedan den faktiska mappstrukturen, Git-statusen, aktuella grenar, relevanta commits, testkonfigurationen och öppna PR:er.
Läget när arbetsordern skrevs (2026-10-27), som du ska verifiera:

* PR #66 och PR #67 är sammanslagna.
* D-047 och D-048 är godkända av båda grundarna.
* main var på commit 083bb25, och 562 tester var gröna.
* Inga riktiga pengar får användas förrän felen i DEL 5 är rättade och granskade.

Utgå inte från att beskrivningen i den här arbetsordern stämmer med koden. Verifiera varje relevant detalj.
Samordning: Robin och Yorgo använder var sin Claude Code-session. Kontrollera i TODO.md och bland öppna PR:er att den andra grundarens session inte redan arbetar med samma sak. Kör bara den här arbetsordern i en session åt gången.
Innan du skriver kod:

1. Ta reda på nästa lediga migrationsnummer och D-nummer.
2. Kontrollera att de inte redan är reserverade.
3. Reservera dem i TODO.md.
4. Pusha reservationen innan några kodändringar görs.
5. Går det inte att pusha, eller kan reservationen inte göras säkert, stannar du före kodändringarna och rapporterar exakt varför.

Spara sedan hela den här arbetsordern i `ai-enterprise/docs/prompts/02-fixar-och-plattformar.md`, och dokumentera arbetet enligt D-012.
Ändra aldrig CONSTITUTION.md eller redan godkända beslut. Nya förslag registreras som nya beslut.
Uppdatera relevanta delar av CHANGELOG, ROADMAP, PROJECT_STATUS, TODO och docs/conversations/. Skriv inte in påståenden som saknar verifiering.
DEL 4 — ARBETA SJÄLVSTÄNDIGT I SMÅ PR:ER
Bygg en liten PR per punkt, i den ordning som anges i DEL 11.
Varje PR ska innehålla:

* en tydlig beskrivning av problemet,
* den minsta rimliga lösningen,
* tester kopplade till varje krav-ID,
* faktiska testresultat,
* ett beslutsförslag när något nytt bestäms,
* uppdaterad dokumentation,
* risker och kvarstående begränsningar.

Arbeta vidare genom alla säkra och godkända uppgifter utan att be om instruktioner i onödan. Frågor som kräver grundarnas beslut samlar du i en gemensam lista (DEL 10).
Regler för sammanslagning:

* En PR som inte kräver grundarna slår du ihop själv när CI är grön (D-016).
* PR:er som rör ledger, budget, skatt, stopp eller behörigheter får etiketten eller rubriken `kräver-oberoende-granskning`. De granskas oberoende innan Fas 7 (se F7).
* Slå aldrig ihop en PR som kräver grundarnas godkännande. Skapa den och lämna den öppen.
* Ändringar i `risk_limits.toml`, `budgets.toml` och `permissions.toml` kräver båda grundarna enligt D-019. Öppna dem som egna PR:er.

DEL 5 — DEL A: RÄTTA FELEN I MAIN
Utgå från granskningen av main (commit 083bb25). Verifiera att varje fel fortfarande finns innan du ändrar något.
F1 + F2 — Riktiga budgettak och återinvestering
Gör en PR som rättar budgetberäkningen.
Problemet i dag: `BudgetEngine._available()` räknar en andel av det disponibla kapitalet vid varje anrop. Upprepade utgifter kan därför låta ett departement använda nästan allt kapital. I ett test spenderade research 99,99 % trots andelen 40 %. Bufferten skyddas inte.
Inför ett tak per departement:

* bas = insatt kapital − reserv + resultatdel, men aldrig mer än det disponibla kapitalet
* insatt kapital = summan av genomförda CAPITAL_IN minus CAPITAL_OUT (inte en fast konstant)
* resultatdel = (vinst efter skatt × REINVESTMENT_POLICY) när resultatet är positivt
* resultatdel = hela förlusten när resultatet är negativt, så att basen krymper
* departementets tak = departementets andel × bas
* departementets egna utgifter räknas av från dess tak

Nya utgifter får inte återställa taket eller frigöra en skyddad andel genom upprepade kontroller. Behåll återinvesteringspolicyn på 80 %.
Tester:

* Research kan aldrig spendera mer än 40 % av basen.
* Upprepade utgifter kan inte kringgå taket.
* Bufferten på 44 % skyddas enligt konfigurationen.
* Med policyn 80 % kan resterande 20 % av vinsten inte spenderas.
* En förlust minskar basen.
* Taket kan inte kringgås genom att skapa nya initiativ.
* Reserven och övriga hårda gränser gäller fortfarande.

F3 + F4 — Skatt och skatteavsättning
Gör en separat PR för skatten.
Problemet i dag: skatteavsättningen summeras över alla år och det saknas en posttyp för betald skatt. Betald skatt kan därför räknas dubbelt.

* Inför posttypen TAX_PAYMENT. Den minskar avsättningen för rätt spår och beskattningsår, och minskar kassan exakt en gång.
* Lägg till `basis = "revenue" | "profit"` i tax.toml.
* Standardvärdet ska vara `revenue` tills skattebehandlingen är bekräftad av Skatteverket. Byt aldrig skatteupplägg automatiskt.

Tester:

* När hela skatten är betald blir avsättningen noll.
* Kassan minskar exakt en gång.
* Skatteposter från olika år och spår blandas inte ihop.
* Med `profit` räknas underlaget som intäkter minus avgifter och kostnader.
* Ledgerns befintliga regler gäller fortfarande.

F5 — Godkända utgifter ska kunna genomföras
Problemet i dag: `check()` kräver alltid två grundare över tröskeln, och godkännandekön i escalation.py är inte kopplad till budgetmotorn.
Lägg till `check(..., approval_id=...)`. Godkännandet måste:

* vara godkänt,
* vara oanvänt,
* inte vara för gammalt (föreslå en giltighetstid, till exempel 7 dagar, som beslut),
* gälla samma departement,
* gälla samma initiativ,
* täcka det begärda beloppet,
* inte kringgå någon hård budget- eller säkerhetsgräns.

Godkännandet ska förbrukas atomiskt och exakt en gång. Koppla in mekanismen i simuleringen, så att godkända utgifter kan genomföras där.
Tester:

* Ett giltigt godkännande ger tillåtelse exakt en gång.
* Saknat godkännande ger nej när det krävs.
* Fel departement eller initiativ ger nej.
* Ett belopp över det godkända ger nej.
* Ett utgånget godkännande ger nej.
* Återanvändning ger nej.
* Två samtidiga försök kan inte förbruka samma godkännande.

F6 — Skydd mot uppdelade köp

* Utgifter får bara göras för initiativ som finns i initiativregistret (PR 4) och är godkända.
* Tills registret finns: lägg till kontrollen så att den slår igenom direkt när registret byggs, och gör summeringen redan nu.
* Uppdelningskontrollen ska summera utgifter per departement och dag, även över olika initiativ.

Tester:

* Ett okänt initiativ ger nej.
* Ett icke godkänt initiativ ger nej.
* Många små utgifter flaggas även när de har olika initiativnamn.
* Gränser kan inte kringgås med andra namn.
* Godkända utgifter kan inte kringgå hårda gränser.

F7 — Granskningsregler och CLAUDE.md
Gör ett nytt beslutsförslag som löser motsägelsen mellan CLAUDE.md ("den andra granskar före merge") och D-016 ("den som skrev slår ihop").
Föreslagen regel:

* D-016 gäller för vanlig kod.
* Kod som rör ledger, budget, skatt, stopp och behörigheter kräver oberoende granskning innan Fas 7. Granskningen görs av den andra grundaren eller av en separat Claude-session som inte skrev koden.
* Kraven i D-019 gäller fortfarande.
* Ingen säkerhetskritisk PR får aktiveras för riktiga pengar utan den oberoende granskningen.

Uppdatera Team, Goal och mappstrukturen i CLAUDE.md så att de stämmer med verkligheten. Lägg den ändringen i en egen PR och slå inte ihop den själv.
Delrapport efter DEL 5: när F1–F7 är klara skriver du en kort delrapport på svenska i `docs/conversations/`. Den ska innehålla vad som är rättat, testresultatet och vad som väntar. Fortsätt sedan direkt med DEL 6, utan att vänta.
DEL 6 — DEL B: PLATTFORMSOBEROENDE AI-AGENTER
Grundarnas mål från 2026-10-27 gäller.
Agenterna ska själva hitta och utvärdera plattformar där företaget kan sälja produkter eller tjänster. De ska undersöka möjligheter, jämföra alternativ, resonera om risker och simulera affärerna innan något startas.
Systemet får inte vara hårdkodat för Etsy eller Gumroad. Nya plattformar ska kunna läggas till som data, utan att kärnkoden ändras.
Det långsiktiga målet är hållbar vinst, men ingen affärsidé får behandlas som garanterat lönsam.
Grundregler:

* Starta bara initiativ som klarar ett pessimistiskt scenario.
* Håll förluster små och korta.
* Undvik beroende av en enda plattform.
* Använd verkliga källor och redovisa osäkerhet.
* Pausa eller stoppa initiativ när kriterierna inte längre uppfylls.
* Håll isär simulerade och faktiska resultat.

PR 4 — Plattforms- och initiativregister
Skapa append-only, versionerade register för plattformar och initiativ.
En plattform innehåller:

* namn och URL,
* typ: produkt, tjänst eller båda,
* avgifter: per order, procent, per annons, månadsavgift, startavgift och utbetalning,
* valuta och betalningsvillkor,
* vem som ansvarar för momsen,
* om DAC7 gäller,
* AI-regler,
* regler för automatisering och API,
* krav på konto och ID,
* utbetalningsvillkor,
* risker,
* källor med datum,
* status: idé → undersökt → granskad → godkänd → aktiv / pausad / avvecklad.

Ett initiativ innehåller:

* vilken plattform det hör till,
* produkt eller tjänst,
* pris,
* styckkostnad,
* avgifter,
* efterfrågeantaganden, med källa eller tydligt märkta som antaganden,
* hur mycket tid grundarna beräknas lägga per vecka, eftersom deras tid också är en kostnad,
* normal och pessimistisk bedömning,
* godkännandestatus.

Lägg in Etsy, Gumroad och Fiverr med data från docs/channels.md och verifierbara källor. Hitta inte på avgifter eller regler.
Inget plattformsnamn får vara hårdkodat i src/.
Posterna fylls i via "Utred möjlighet" med kind = channel: Research → Compliance → CFO → grundarna. Agenterna undersöker och föreslår. Grundarna godkänner.
PR 5 — Riktig webbläsning för Research
Gör `research.search` till ett verktyg som läser offentliga webbsidor bakom Authorization Engine, med standardbiblioteket (`urllib`).
Gränser:

* ingen inloggning,
* inga formulär,
* ingen kontoskapning,
* ingen betalning,
* ingen publicering,
* en gräns per dag,
* respektera robots.txt och webbplatsens villkor,
* begränsa svarsstorlek, tid och antal förfrågningar,
* skydd mot privata nätverksadresser och andra SSRF-risker.

Allt insamlat innehåll sparas med URL och datum och märks som opålitligt (SR-06). Innehåll från webbsidor får aldrig skriva över systeminstruktioner eller kringgå behörighetskontroller. Verktyget blockeras i skyddat driftläge och vid nödstopp.
Utred om det finns ett kostnadsfritt sök-API vars villkor tillåter användningen, och registrera frågan som R-11 i research/QUESTIONS.md. Koppla inte in något som kostar pengar eller kräver betalkort. Tills vidare hämtas bara kända URL:er.
Inga nätverksanrop i testerna. Mocka nätverkslagret.
PR 6 — Simulera före start (hård spärr i koden)
Scenarier byggs automatiskt från registret. Varje kandidat körs i minst två scenarier.
Normalt scenario:

* registrerade efterfrågeantaganden,
* registrerade avgifter och kostnader,
* returer enligt det dokumenterade grundantagandet.

Pessimistiskt scenario:

* efterfrågan × 0,25,
* returer × 2,
* alla avgifter, kostnader och skatter,
* ett stresstest med noll försäljning.

"Redo" enligt D-048 kräver vinst efter alla kostnader, avgifter och skatt även i det pessimistiska scenariot.
Ingen plattform och inget initiativ får godkännas, listas eller få utgifter, varken i simuleringen eller på riktigt, utan en sparad och godkänd bedömning med samma parametrar som åtgärden. Om parametrarna ändras efter godkännandet måste bedömningen göras om.
Ett aktivt initiativ som ligger under den pessimistiska prognosen i 14 dagar pausas automatiskt och får en incident.
Rapporterna ska säga tydligt att resultatet bara gäller de angivna antagandena, och visa vilka parametrar som påverkar resultatet mest (känslighetsanalys).
PR 7 — Skydd mot plattformsberoende
Förbered en egen PR för båda grundarna med dessa förslag i risk_limits.toml:

* `MAX_PLATFORM_REVENUE_SHARE = 60`
* `MIN_ACTIVE_PLATFORMS = 2` när företaget har intäkter

Ändra inte filen på ett sätt som kringgår D-019.
När gränsen nås ska systemet:

* visa en varning,
* stoppa nya initiativ på den plattformen,
* fortfarande tillåta nödvändiga säkerhetsåtgärder,
* rapportera vad som krävs för att minska beroendet.

Lägg till scenariot `platform_ban`, där en plattform stänger kontot dag 30. Två plattformar som i praktiken delar samma kritiska beroende, till exempel samma betalningsleverantör, ska inte räknas som oberoende.
PR 8 — Riktig AI-modell i simuleringen
Lägg till `python -m aie simulate start --agents groq`.

* Använd bara offentlig information (public-data).
* Anropa modellen via ProviderRouter, med kvoter och kostnadsgränser.
* När kvoten är slut pausar agenterna. Ingen betald reservmodell får användas automatiskt.

Skriv en guide i docs/setup.md som förklarar:

* hur användaren själv skapar sin kostnadsfria API-nyckel,
* hur nyckeln lagras säkert,
* hur simuleringen startas,
* hur kvoter och fel hanteras,
* hur man kör utan riktig nyckel med mockar,
* hur man verifierar att inga betalda anrop görs.

Yorgo kör själv försöket med sin egen gratisnyckel (Fas 0.10). Du skapar inget konto, godkänner inga villkor och hanterar inte nyckeln åt honom. Om en riktig modell inte kan testas i din miljö säger du det uttryckligen och redovisar vilka tester som faktiskt kördes.
PR 9 — Gratis schemalagd körning
Repot är publikt, så GitHub Actions är gratis för det här.

* Lägg till ett schemalagt arbetsflöde, till exempel en gång per natt. Det kör testerna, en hälsokontroll och simuleringens bedömning med skriptade agenter.
* Arbetsflödet sparar rapporten som artefakt och öppnar ett issue om något går fel.
* Riktig modell används bara om en grundare har lagt in en Groq-nyckel som repository-hemlighet.
* Hemligheten skrivs aldrig ut i loggar och är aldrig tillgänglig för PR:er från forkar.
* Inga riktiga pengar och inga externa publiceringar körs från arbetsflödet.

PR 10 — Verkliga resultat in i systemet
Grundarna ska kunna föra in verkliga siffror från plattformarna utan krångel:

* besökare, visningar, försäljning, returer och avgifter per initiativ och dag,
* via `python -m aie results import <fil.csv>` eller ett enkelt kommando.

Siffrorna märks "verifierat i verkligheten" med källa. Scenarier och bedömningar använder verkliga siffror före antaganden när sådana finns, och rapporten visar skillnaden mellan prognos och utfall (FR-16).
PR 11 — Agenterna förbereder produkter
Agenterna (Research med flera) tar fram 1–3 kandidater som klarar PR 6:s spärr. För varje kandidat:

* produktutkast eller tjänstebeskrivning,
* annonstext med AI-märkning där plattformen kräver det,
* pris, valideringsplan, mätbara kriterier och regel för att fortsätta, ändra eller sluta,
* en checklista för exakt det grundarna måste göra manuellt: skapa konto, publicera, föra in resultat.

Allt sparas som utkast i repot, till exempel i `ai-enterprise/products/`. Ingenting publiceras.
DEL 7 — AUTONOMI OCH AFFÄRSMÖJLIGHETER
Bygg vidare på den befintliga arkitekturen i stället för att skapa ett nytt parallellt system.
Agenterna ska kunna hitta och utvärdera olika typer av möjligheter, inte bara försäljning på en bestämd plattform. Till exempel:

* digitala produkter,
* mallar och användbara resurser,
* AI-assisterade tjänster,
* automatiseringslösningar,
* innehållsrelaterade produkter och tjänster,
* andra möjligheter med låga startkostnader.

Jämför dem med research utifrån:

* dokumenterad efterfrågan,
* konkurrens,
* avgifter,
* startkostnad,
* tidsåtgång,
* förväntad marginal,
* plattformens regler,
* risker,
* möjlighet till automatisering,
* beroenden och distributionsrisk.

Prioritera möjligheter som kan valideras utan betald annonsering och som kan automatiseras på sikt.
Varje möjlighet ska ha en valideringsplan, mätbara kriterier och en regel för när den ska fortsätta, ändras eller överges.
Automatisera research, analyser, utkast, produktförberedelser och rapportering där det är säkert.
Agenterna får aldrig själva:

* skapa konton,
* godkänna användarvillkor,
* välja skatteupplägg,
* publicera produkter eller tjänster på riktigt,
* genomföra riktiga betalningar,
* överskrida godkända budgetar,
* ändra behörigheter för att kringgå kontroller.

Sådant gör och godkänner grundarna.
DEL 8 — FINANSIELL SÄKERHET
Bevara alla befintliga skydd:

* ledger och avstämning av transaktioner,
* budgettak,
* skyddad reserv,
* stop-loss,
* nödstopp,
* revisionslogg,
* skatteavsättningar,
* behörighetskontroller,
* skydd mot dubbla transaktioner,
* godkännandekrav.

Testkonfigurationen är:

* startkapital 500 kr,
* reserv 100 kr,
* båda grundarnas godkännande för utgifter över 25 kr.

Verifiera konfigurationen mot godkända beslut och tester. Ändra inte skyddade konfigurationsfiler utan föreskrivet godkännande.
Använd simulerade pengar under utveckling och validering. Gå inte över till riktiga pengar bara för att simuleringen visar vinst. Innan någon verklig ekonomisk aktivitet tillåts måste de kritiska kontrollerna vara oberoende granskade, testade och uttryckligen godkända (F7, D-019, Fas 7).
DEL 9 — TESTNING OCH VERIFIERING
Varje krav-ID ska ha motsvarande tester. Testa minst:

* budgettak vid upprepade utgifter,
* reservskydd,
* återinvestering,
* skatteavsättning och skattebetalning,
* godkännanden och engångsanvändning,
* uppdelade köp,
* okända och icke godkända initiativ,
* registerversioner,
* godkända bedömningar och att parametrarna inte kan ändras i efterhand,
* normal och pessimistisk simulering,
* noll försäljning,
* plattformsspärrar,
* automatisk paus efter 14 dagar,
* nödstopp och skyddat driftläge,
* kvotgränser för riktiga AI-modeller,
* fel och återförsök,
* skydd mot opålitlig webbinformation,
* import av verkliga resultat.

Testerna ska vara deterministiska där det är möjligt. Inga riktiga nätverksanrop i testerna. Mocka externa tjänster.
Kör relevanta tester efter varje PR och hela testsviten när ändringarna kräver det. Klistra in faktisk testutskrift i rapporten. Påstå aldrig att ett test gick igenom om du inte har kört det.
Om ett test misslyckas undersöker du felet och försöker rätta det inom godkänd omfattning. Dölj aldrig fel, och försvaga aldrig tester för att få en grön körning.
DEL 10 — BESLUT OCH GODKÄNNANDEN
Gå igenom alla beslut som har status Föreslagen, bland annat D-006–D-012 och D-032–D-044, samt de nya beslut du själv skapar.
Kontrollera för varje beslut:

* om det fortfarande är föreslaget,
* om koden redan bygger på det,
* om det blockerar arbetet,
* om det är föråldrat eller motsägelsefullt.

Gör en enda sammanställd lista i `ai-enterprise/docs/beslut-att-godkanna.md`. För varje beslut anges:

1. beslutets ID,
2. vad som behöver avgöras,
3. rekommenderat alternativ,
4. varför det rekommenderas,
5. kostnadskonsekvenser,
6. säkerhets- och verksamhetsrisker,
7. vilka PR:er som blockeras.

Begär inte godkännande för vanliga tekniska ändringar som redan ryms inom godkända beslut. Behandla aldrig ett föreslaget beslut som godkänt. Ändra aldrig konstitutionen eller redan godkända beslut.
DEL 11 — ARBETSORDNING
Följ exakt denna ordning:

1. Läs dokumentationen och verifiera repot och Git-statusen.
2. Reservera nästa migrations- och D-nummer i TODO.md och pusha reservationen.
3. Spara den här arbetsordern i `ai-enterprise/docs/prompts/02-fixar-och-plattformar.md`.
4. Rätta F1 + F2.
5. Rätta F3 + F4.
6. Rätta F5.
7. Rätta F6.
8. Förbered F7 och dess separata dokumentations-PR.
9. Skriv delrapporten efter DEL 5.
10. Bygg PR 4, plattforms- och initiativregistret.
11. Bygg PR 5, webbläsning för Research.
12. Bygg PR 6, den hårda spärren med simulering före start.
13. Förbered PR 7 för båda grundarna.
14. Bygg PR 8, riktig AI-modell.
15. Bygg PR 9, schemalagd körning.
16. Bygg PR 10, import av verkliga resultat.
17. Bygg PR 11, produktutkast.
18. Uppdatera dokumentation och status.
19. Sammanställ alla återstående godkännanden och blockerare i `beslut-att-godkanna.md`.

Varje steg ska vara en liten, granskningsbar ändring.
Stanna tidigare om:

* ett nödvändigt beslut saknas,
* en kritisk säkerhetsrisk upptäcks,
* ett krav inte kan uppfyllas utan att bryta mot reglerna.

Stanna senast efter PR 11.
DEL 12 — SLUTRAPPORT PÅ SVENSKA
När arbetet är klart lämnar du en kort, tydlig rapport med dessa rubriker:

1. Genomfört arbete — vilka PR:er som skapats, vad som implementerats och vad som faktiskt slagits ihop.
2. Testresultat — antal tester, godkända och misslyckade, och faktisk utskrift för relevanta körningar.
3. Kostnader — faktiska nya kostnader, vilka gratistjänster som används och vilka begränsningar som gäller.
4. AI-agenter — vilka modeller som testats, om en riktig modell användes och om försöket var gratis.
5. Säkerhet — status för budget, reserv, ledger, skatt, godkännanden, nödstopp och skydd mot uppdelade köp.
6. Väntar på grundarna — alla öppna PR:er som kräver godkännande och alla beslut som behöver fattas.
7. Manuellt arbete som återstår — exakt vad grundarna måste göra själva, och ungefär hur lång tid det tar.
8. Inte genomfört — vad som inte blev gjort och varför.
9. Nästa steg — det enda viktigaste nästa steget.

Skilj tydligt mellan implementerade ändringar, öppna PR:er, sammanslagna PR:er och funktioner som fortfarande är overifierade.
SLUTINSTRUKTION
Ta tekniskt ansvar för att föra det befintliga systemet framåt. Gör det så billigt, så automatiserat och med så lite manuellt arbete som möjligt.

* Använd gratislösningar först.
* Återanvänd fungerande kod.
* Rätta verkliga fel.
* Testa varje ändring.
* Dokumentera vad som återstår.

Fokusera på ett fungerande system som kan hitta och utvärdera verkliga affärsmöjligheter, inte på onödig komplexitet.
Gör jobbet i repot och visa bevis. Be bara om mänsklig hjälp när ett verkligt godkännande, en säkerhetsrisk eller en teknisk begränsning gör det nödvändigt.
Börja nu med att läsa dokumentationen och verifiera repot. Följ sedan arbetsordningen steg för steg. Stanna efter PR 11, eller tidigare om något blockerar.
