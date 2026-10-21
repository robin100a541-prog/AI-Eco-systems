# REQUIREMENTS — AI Enterprise System

Version: 0.1 (Fas 0) · Skapad: 2026-10-21 · Källa: CONSTITUTION.md v1.0

Varje krav har ett unikt ID. Kolumnen **§** pekar på avsnittet i konstitutionen. Kolumnen **Fas** anger när kravet först ska vara uppfyllt och verifierat (se ROADMAP.md).

Prioritet: **M** = måste (blockerar fasens godkännande), **B** = bör.

ID-prefix: `FR` funktionella krav · `SR` säkerhetskrav · `ER` ekonomiska krav · `DR` utvecklingskrav.

---

## 1. Funktionella krav (FR)

| ID | Krav | § | Fas | Prio |
|---|---|---|---|---|
| FR-01 | Systemet kan startas, stoppas och återstartas med dokumenterade kommandon. | 44, 49 | 1 | M |
| FR-02 | Konfiguration läses från filer, valideras vid start och ogiltig konfiguration stoppar uppstart. | 39, 49 | 1 | M |
| FR-03 | Alla data (agenter, uppgifter, beslut, ledger, lärdomar) lagras beständigt och överlever omstart. | 30, 49 | 1 | M |
| FR-04 | Händelser och fel loggas strukturerat med tidsstämpel och källa. | 35, 49 | 1 | M |
| FR-05 | Agentregister: varje agent har ID, roll, departement, chef, mandat och livscykelstatus. | 9, 50 | 2 | M |
| FR-06 | Livscykel PROPOSED→CREATED→TESTING→ACTIVE→PROBATION→SUSPENDED→RETIRED med definierade tillåtna övergångar. | 32 | 2 | M |
| FR-07 | Uppgifter kan skapas, tilldelas, följas upp och avslutas; varje uppgift har ägare och status. | 50 | 2 | M |
| FR-08 | Standardiserat rapportformat som skiljer på hypotes, prognos, plan, försök, genomfört, observerat, verifierat, bokfört, realiserad intäkt och realiserad nettovinst. | 7 | 2 | M |
| FR-09 | Hierarki nivå 0–5 (grundare, CEO, kontrollfunktioner, departementschefer, arbetsagenter, tillfälliga grupper). | 8 | 3 | M |
| FR-10 | Beslutsprocessens 11 steg lagras som en strukturerad beslutspost (mål, underlag, alternativ, ekonomi/risk, samråd, invändningar, beslut, behörighetskontroll, utförande, utfall, lärdom). | 20 | 3 | M |
| FR-11 | Samråd: ett beslut kan kräva yttranden från namngivna roller (t.ex. CFO, CRO) beroende på belopp/riskklass. | 20 steg 5 | 3 | M |
| FR-12 | Oenighet registreras med exakt omtvistat påstående och typ (mål/data/risk/metod) och eskaleras om den kvarstår. | 21 | 3 | M |
| FR-13 | Eskalering till rätt beslutsnivå, inklusive mänskligt godkännande. | 8, 21 | 3 | M |
| FR-14 | Tillfälliga projektgrupper kan skapas och upplösas; resultat och lärdomar överförs till beständigt minne. | 8 nivå 5 | 3 | B |
| FR-15 | Incidentrapport med samtliga 16 obligatoriska fält. | 28 | 5 | M |
| FR-16 | Prognoser loggas och jämförs automatiskt med utfall. | 20 steg 10, 53 | 5 | M |
| FR-17 | Lärdomsregister med verifieringsstatus (obekräftad hypotes → godkänd operativ regel); bara godkända regler får ändra gemensamma regler. | 29 | 5 | M |
| FR-18 | Strategier och agentversioner är versionshanterade och kan återställas. | 53 | 5 | M |
| FR-19 | Prestationsmätning per agent utifrån rollspecifika mått (inte enbart intäkt). | 31 | 5 | M |
| FR-20 | Affärssimulering med simulerat kapital, scenarier, misslyckanden och budgetöverskridanden. | 54 | 6 | M |
| FR-21 | Daglig rapport (11 punkter i §57); saknade data anges uttryckligen. | 57 | 6 | M |
| FR-22 | Periodisk företagsrapport jämförbar mellan perioder och initiativ. | 58 | 6 | B |
| FR-23 | Affärsförslag har de 11 obligatoriska fälten (kundproblem … avbrottskriterier). | 12 | 6 | M |
| FR-25 | Uppgiftstypen "Utred möjlighet": Research fyller i en strukturerad registerpost (kanal, verktyg, skatte-/regelfråga) med källor och datum; posten går Research → Compliance → CFO → grundare (D-011). | 12, 17 | 3 | M |
| FR-25 | Forskningskö: öppna frågor (kanaler, skatt, villkor, API:er) blir uppgifter för Research/Compliance; svar lagras med källor och verifieringsstatus; lag-/skatte-/villkorsfrågor kräver Compliance + grundargodkännande innan de blir regel (D-011). | 12, 17, 29 | 5 | M |
| FR-26 | Varje Claude-session sparas i `docs/conversations/` (D-012). | 30, 46 | 0 | M |
| FR-24 | Övervakning upptäcker loopar, upprepat arbete och kostnad utan värde. | 16 | 6 | B |

## 2. Säkerhetskrav (SR)

| ID | Krav | § | Fas | Prio |
|---|---|---|---|---|
| SR-01 | Behörigheter upprätthålls av kod (Authorization Engine), aldrig enbart av promptinstruktioner. | 9, 35 | 2 | M |
| SR-02 | Minsta behörighet: varje agent har en explicit vitlista av verktyg; allt annat nekas (default deny). | 36 | 2 | M |
| SR-03 | En agent kan inte ändra sitt eget mandat eller få utökad behörighet via en annan agent. | 8, 36 | 2 | M |
| SR-04 | CEO-agenten kan inte ändra konstitution, konfiguration för gränser eller egna befogenheter. | 8 | 3 | M |
| SR-05 | Kontrollfunktioner (CFO, CRO, Compliance, Audit) kan stoppa åtgärder inom sitt område; ingen operativ chef kan ensam häva ett obligatoriskt stopp. | 8 | 3 | M |
| SR-06 | Externt innehåll (webb, dokument, kundmeddelanden) märks som opålitlig data och kan aldrig ge behörighet. | 37 | 3 | M |
| SR-07 | Nödstopp (kill switch): stoppar transaktioner och externa handlingar, återkallar behörigheter, bevarar alla data, raderar inget. | 38 | 4 | M |
| SR-08 | Skyddat driftläge aktiveras automatiskt vid villkoren i §59 (inkl. "kan inte avgöra om tillåtet" ⇒ blockera). | 59 | 4 | M |
| SR-09 | Revisionslogg (audit log) är append-only; viktiga beslut, verktygsanrop och ändringar registreras. | 39, 40 | 1 (grund), 4 | M |
| SR-10 | Hemligheter lagras aldrig i git eller loggar; läses från miljövariabler/lokal fil som är gitignorerad. | 35 | 1 | M |
| SR-11 | Test och produktion separeras tekniskt; simulerat läge kan inte röra verkligt kapital. | 25, 35 | 4 | M |
| SR-12 | Återförsök är begränsade i antal och kostnad; idempotensnycklar skyddar mot dubbel genomföring. | 41 | 4 | M |
| SR-13 | Ny eller ersättande agent får inte tillgång till verkligt kapital innan den passerat tester. | 32, 34 | 2 | M |
| SR-14 | Avveckling av agent återkallar behörigheter men raderar aldrig gemensamt minne, ledger eller andra agenters data. | 34 | 2 | M |
| SR-15 | Kritiska förändringar kan inte distribueras automatiskt av den agent som skrivit dem. | 13 | 7 | M |
| SR-16 | Juridisk/avtalsmässig konflikt ⇒ åtgärden avbryts och skickas till Compliance. | 6 | 3 | M |
| SR-18 | Publicering på extern plattform (Etsy, Gumroad m.fl.) går via Tool Gateway; plattformens regler kontrolleras av kod, t.ex. att AI-användning anges i varje Etsy-annons och att förbjudna varutyper blockeras. Första publiceringen per kanal kräver grundargodkännande. | 6, 37 | 7 | M |
| SR-17 | Agenter avvecklas inte enbart för obekväma slutsatser; avveckling kräver dokumenterade kriterier. | 33 | 5 | M |

## 3. Ekonomiska krav (ER)

| ID | Krav | § | Fas | Prio |
|---|---|---|---|---|
| ER-01 | Alla belopp lagras som exakta decimaltal (aldrig flyttal) med explicit valuta. | 25 | 4 | M |
| ER-02 | De 10 parametrarna i §25 måste vara satta innan verkligt kapital hanteras; saknad parameter ⇒ berörd handling blockeras. | 25 | 4 | M |
| ER-03 | Central budgetkontroll före varje ekonomisk handling (budget, beloppsgräns, reserv, riskklass, godkännandekrav). | 5, 20 steg 8 | 4 | M |
| ER-04 | Uppdelning av köp för att undgå gränser upptäcks (aggregering per initiativ/motpart/tidsfönster). | 5 | 4 | M |
| ER-05 | Skyddad reserv kan inte disponeras i normal drift och kan inte ändras av operativ agent. | 5, 23 | 4 | M |
| ER-06 | Ledger: varje post har de 12 obligatoriska fälten i §40 och unikt ID. | 40 | 4 | M |
| ER-07 | Dubbelregistrering förhindras (unikt externt ID / idempotensnyckel). | 40 | 4 | M |
| ER-08 | Korrigeringar görs med spårbara korrigeringsposter; befintliga poster ändras aldrig. | 40 | 4 | M |
| ER-09 | Nettovinst = realiserade intäkter − relevanta kostnader, beräknad enbart från ledgerposter; beräkningsmetoden dokumenteras. | 22 | 4 | M |
| ER-10 | Kapitalbegrepp hålls isär: totalt, likvida, bundet, reserv, åtaget, disponibelt, återinvesterbart. | 23 | 4 | M |
| ER-11 | Prognos ≠ mottagen betalning; orealiserat värde redovisas aldrig som realiserad vinst. Resultat märks "preliminärt" när kostnader saknas. | 11, 22, 23 | 4 | M |
| ER-12 | Varje ekonomiskt initiativ får en riskklass före godkännande. | 24 | 4 | M |
| ER-13 | Stop-loss: när gräns nås blockeras nya åtaganden, exponering beräknas, ansvariga informeras, nytt godkännande krävs. Befintliga förpliktelser hanteras, ignoreras inte. | 26 | 4 | M |
| ER-14 | Belopp över HUMAN_APPROVAL_THRESHOLD kräver godkännande av grundare. | 25 | 4 | M |
| ER-15 | Simulerade pengar har egen valuta/flagga och kan aldrig blandas med verkliga i samma beräkning. | 25, 54 | 4 | M |
| ER-16 | Audit-agenten kan återberäkna rapporterade siffror direkt från ledgern. | 18 | 4 | M |
| ER-17 | Varje departement har budget, användningsområde, maxåtagande och riskutrymme i konfiguration. | 5 | 4 | M |
| ER-18 | Varje intäkt märks med skattespår (ISK / egenanställning / enkelt bolag / hobby) enligt D-010. | 6, 22 | 4 | M |
| ER-19 | Beräknad skatt reserveras automatiskt som åtagande och räknas aldrig som disponibelt kapital. | 22, 23 | 4 | M |
| ER-20 | Momsgränsen (120 000 kr/år) bevakas; varning vid 80 %, blockering av ny försäljning vid gränsen tills grundarna beslutat. | 6 | 4 | M |
| ER-21 | Underlag arkiveras i minst 7 år och kan exporteras som deklarationsunderlag per grundare. | 6, 30 | 4 | M |
| ER-23 | Plattformsförsäljning bokförs brutto med plattformens avgifter och eventuell moms som separata poster; utbetalningar stäms av mot plattformens rapport (DAC7-underlag). | 22, 40 | 4 | M |
| ER-22 | Budgetkategorin `API_SPEND` är 0 kr tills realiserad nettovinst efter skatt finns; därefter högst `API_REINVEST_SHARE` (D-009). | 5, 42 | 4 | M |

## 4. Utvecklingskrav (DR)

| ID | Krav | § | Fas | Prio |
|---|---|---|---|---|
| DR-01 | Inga kostnader utöver två Claude Pro-abonnemang och framtida startkapital. Nya betaltjänster kräver uttryckligt beslut i DECISIONS.md. | 42 | 0 | M |
| DR-02 | Varje verktyg/bibliotek har dokumenterad licens och kostnad innan det införs (TOOLS-registret i ARCHITECTURE.md). | 43 | 0 | M |
| DR-03 | Claude Pro antas inte ge API-åtkomst. Modellåtkomst från kod verifieras innan den används. | 43 | 0 | M |
| DR-04 | Gemensam versionshanterad källa (git) är den enda källan till sanning; konversationer är inte dokumentation. | 2, 30, 46 | 0 | M |
| DR-05 | DECISIONS.md, ARCHITECTURE.md, PROJECT_STATUS.md, CHANGELOG.md uppdateras vid varje relevant ändring. | 46 | alla | M |
| DR-06 | Varje fas avslutas med körda tester och dokumenterad verifiering av acceptanskriterier. | 60 | alla | M |
| DR-07 | Lokal körning på grundarnas egna datorer är standard. | 44 | 0 | M |
| DR-08 | Komponenterna i §39 är separat testbara moduler med tydliga gränssnitt. | 39 | 1+ | M |
| DR-09 | Ingen hierarki mellan Yorgo och Robin antas förrän den beslutats uttryckligen. | 2 | 0 | M |
| DR-10 | Arbetsuppgifter beskrivs enligt §47 (mål, tillstånd, filer, implementering, kommandon, förväntat resultat, tester, kriterier, risker, verifiering). | 47 | alla | M |
| DR-11 | Inga påståenden om körda tester, filer eller funktioner utan bevis. | 7, 60 | alla | M |
| DR-12 | Agenterna använder gratis språkmodeller (Groq, OpenRouter `:free`, Ollama) via ProviderRouter; kvoter räknas, och när de tar slut köas arbetet i stället för att betala (D-008). | 42, 43 | 0 (verifiering), 2 | M |
| DR-13 | Data klassas; endast `public` får skickas till externa gratis-API:er. | 36, 37 | 2 | M |

---

## Spårbarhet

Varje test i `tests/` ska i docstring ange vilket krav-ID det verifierar (t.ex. `"""Verifies ER-07."""`). Fasgodkännande = alla M-krav för fasen har minst ett gröna test eller en dokumenterad manuell verifiering.
