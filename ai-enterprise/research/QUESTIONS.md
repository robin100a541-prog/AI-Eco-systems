# Forskningskö — öppna frågor (D-011)

Frågor som systemets Research- och Compliance-agenter ska utreda när de finns (Fas 5+). Fram till dess kan grundarna eller Claude utreda dem manuellt.

Status: `Öppen` → `Utreds` → `Obekräftad hypotes` → `Verifierad (källa + Compliance)` → `Godkänd regel (grundare)`.
Frågor om lag, skatt eller plattformsvillkor får aldrig bli regel utan grundargodkännande.

| ID | Fråga | Varför den spelar roll | Typ | Status | Källor hittills |
|---|---|---|---|---|---|
| R-01 | Vilket skattespår (ISK / egenanställning / enkelt bolag) gäller för de intäkter piloten faktiskt ger? | Fel spår ⇒ skattetillägg | Skatt | Öppen | Skatteverkets sidor i ARCHITECTURE.md |
| R-02 | Hur exakt hanterar Etsy moms för köpare i EU när säljaren är privatperson i Sverige? | Avgör om vi själva måste momsregistrera | Skatt/kanal | Öppen | Etsy beskrivs som marknadsplats som tar in moms där det gäller (sekundärkälla) |
| R-03 | Tillåter Fiverr att en AI sköter kundmeddelanden och leveranser automatiskt? | Brott ⇒ permanent avstängning | Villkor | Öppen | Fiverrs AI-riktlinjer nämner inte automatiserad kommunikation |
| R-04 | Vilka regler har Gumroad för AI-genererade produkter? | Kontot kan stängas | Villkor | Öppen | — |
| R-05 | Godtar egenanställningsföretag uppdrag som utförs med AI och uppdrag via Fiverr? | Avgör om spår B fungerar ihop med Fiverr | Skatt/kanal | Öppen | — |
| R-06 | Vilka villkor om dataanvändning har Groqs och OpenRouters gratisnivåer? | Avgör vilken data som får skickas | Villkor | Öppen | — |
| R-07 | Vilka licenser har de öppna modellerna vi tänker använda (gpt-oss, Qwen m.fl.)? Får de användas kommersiellt? | Licensbrott | Licens | Öppen | — |
| R-08 | Momsgränsen 120 000 kr/år: hur räknas plattformsförsäljning där plattformen redan tagit in moms? | Felaktig momsredovisning | Skatt | Öppen | Skatteverkets hobbysida nämner gränsen |
| R-09 | Vilka API:er (betalda) skulle ge mest värde per krona när vinst finns (D-009)? | Rätt första investering | Ekonomi | Öppen | — |
| R-10 | Vilka produkter/tjänster har verifierbar efterfrågan på Gumroad, Etsy och Fiverr med låg startkostnad? | Val av pilot (Q-08) | Marknad | Öppen | — |
| R-11 | Finns ett kostnadsfritt sök-API vars villkor tillåter automatiserad användning för marknadsresearch, utan betalkort, med kända gränser? Kandidater att läsa villkoren för (inget är verifierat): MediaWiki-API:t (Wikipedia), DuckDuckGo Instant Answer, Brave Search API:s gratisnivå, Bing Web Search. | Utan ett sök-API kan Research bara läsa kända sidor (`config/research.toml`, D-057) och inte själv hitta nya plattformar | Verktyg/villkor | Öppen | — (2026-10-28: inget lästs; inget kopplat in) |

## Säljkanaler
Utvärderade kanaler (Gumroad, Etsy, Fiverr) finns i [`docs/channels.md`](../docs/channels.md).
