# 7a: affärsmöjligheter (produktavdelningen)

Riktig körning på Groq 2026-10-30: https://github.com/robin100a541-prog/AI-Eco-systems/actions/runs/41094907918
(`aie pilot discover`, commit 89cd329). Ingen vinnare är vald; Robin och Yorgo väljer bland de tre bästa.

## Topp 3

**Ingen bra idé hittad ännu.** Ingen av de 11 idéerna klarade minimikraven. Ingen idé hade en marknadssignal
med siffra (konkurrent, pris eller försäljning) som handlade om samma sak som idén.

### Varför: researchen når inte marknadsplatserna
- **Etsy** svarar 403 på alla sökningar.
- **itch.io** och **Fiverr** förbjuder hämtning i robots.txt, och systemet följer det.
- **Gumroad Discover** byggs med JavaScript (tom sida) eller svarar 404.
- **Reddit** förbjuder hämtning i robots.txt.
- Det som gick att läsa var Stack Exchange-API:t (videofrågor med antal visningar) och Hacker News. Där finns
  frågor och åsikter, men nästan inga priser eller försäljningssiffror för produkter som liknar idéerna.

### Grundarbeslut som behövs (ett av dem)
1. **Marknadsdata via API:** Etsy Open API (gratis nyckel, kräver en grundares konto) eller Gumroads API ger
   priser och antal recensioner lagligt. Nyckeln läggs som GitHub-hemlighet.
2. **Manuellt urval:** en grundare sparar 10–20 produktsidor för hand (till exempel bästsäljande LUT-paket på
   Etsy) i en fil. Research-agenten läser dem som källor. Det går fort och följer reglerna.
3. **Sänk inte ribban.** En idé utan marknadssignal blir inte en topp 3 (Robins regel 7).

## Bedömningsmall

| Kriterium | Vikt | Poäng 0–5 |
|---|---|---|
| demand | 3 | antal belagda signaler som idén bygger på (högst 5) |
| competition | 1 | konkurrenter bland signalerna: 0 → 2 (obevisat), 1–3 → 5, 4–8 → 3, fler → 1 |
| price | 1 | netto per försäljning: under 3 USD → 1, under 8 USD → 3, annars 5 |
| founder_fit | 2 | grundarnas färdigheter i idén (2 per träff) + 1 om språket är grundarnas, högst 5 |
| time_to_first_sale | 1 | dagar till första försäljning: ≤14 → 5, ≤30 → 4, ≤60 → 2, annars 1 |
| max_loss | 1 | förskott 0 → 5, inom MAX_SINGLE_EXPERIMENT_LOSS → 3, annars 0 och diskvalificerad |
| expected_value | 2 | förväntat netto 90 dagar delat med tröskeln, högst 5 |

En idé är kvalificerad bara om tre krav är uppfyllda:
- minst 2 belagda signaler,
- minst en av dem är en marknadssignal med siffra om samma sak som idén,
- förväntat värde är minst 150 USD på 90 dagar.

Alla belopp räknas i kod. Modellen gav bara pris och uppskattad försäljning.

## Alla idéer

Netto är per försäljning. Förväntat värde gäller 90 dagar och bygger på modellens försäljningsuppskattning.

| # | Idé | Typ | Plattform | Pris USD | Netto | Förv. värde | Signaler | Poäng | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | DaVinci Resolve 18 Masterclass – Video Editing & Color Grading | course | gumroad | 199.99 | 179.49 | 7179.60 | S1, S3 | 78 | ingen marknadssignal om samma sak |
| 2 | Motion Graphics for Beginners – After Effects & DaVinci Resolve | course | gumroad | 149.99 | 134.49 | 4707.15 | S7, S8 | 75 | ingen marknadssignal om samma sak |
| 3 | Football Match Highlight Intro Pack – Motion Graphics | motion-graphics | etsy | 59.99 | 53.84 | 3768.80 | S2 | 73 | ingen marknadssignal; 1 signal |
| 4 | DaVinci Resolve Color Grading Presets – 10 Pack | preset | gumroad | 19.99 | 17.49 | 2448.60 | S1 | 73 | ingen marknadssignal; 1 signal |
| 5 | Real-Estate Property Tour Motion Graphics Bundle | motion-graphics | etsy | 49.99 | 44.79 | 3583.20 | S13, S14 | 71 | ingen marknadssignal om samma sak |
| 6 | Social Media Video Strategy Guide – Swedish & English | guide | payhip | 34.99 | 33.24 | 3656.40 | S3 | 69 | ingen marknadssignal; 1 signal |
| 7 | Fastighetsbolaget Video Marketing Guide – Swedish | guide | payhip | 39.99 | 37.99 | 2279.40 | S5 | 65 | ingen marknadssignal; 1 signal |
| 8 | DaVinci Resolve 18 Cinematic LUT Pack – Swedish & English | lut | gumroad | 29.99 | 26.49 | 3178.80 | S1 | 62 | ingen marknadssignal; 1 signal |
| 9 | Arabic-Friendly Cinematic LUTs for DaVinci Resolve | lut | gumroad | 24.99 | 21.99 | 1979.10 | S1 | 62 | ingen marknadssignal; 1 signal |
| 10 | Real-Estate Video Production & Editing Service | service | fiverr | 299.99 | 239.99 | 11999.50 | S13, S14 | 60 | ingen marknadssignal om samma sak |
| 11 | One-Hour Quick Edit & Color Grade Service | service | fiverr | 49.99 | 39.99 | 7998.00 | S17, S22 | 60 | ingen marknadssignal om samma sak |

Modellens försäljningsuppskattningar (till exempel 50 masterclass-försäljningar på 90 dagar) saknar belägg. Därför
väger demand och marknadssignalen tyngst.

## Belägg (signaler med källa, citat ordagrant ur sidan)

SE = `https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=votes&q=<sökord>&site=video&pagesize=25`,
HN = `https://hn.algolia.com/api/v1/search?query=<sökord>&hitsPerPage=20`.

| Id | Typ | Citat | Pris | Antal | Källa (sökord, hämtning) |
|---|---|---|---|---|---|
| S1 | question | "Color correction/grading then editing in Premiere" | | 727 | SE davinci resolve luts (#1) |
| S2 | question | "What is the standard format for transparent fire and glow effects in VFX?" | | 132 | SE davinci resolve luts (#1) |
| S3 | question | "how to automate interviews" | | 195 | SE davinci resolve luts (#1) |
| S4 | price | "When they run the budget speed-editor promos you get the studio license card for free." | 0.00 | | HN davinci resolve luts (#3) |
| S5 | question | "I find the big downside of color grading is it makes you really want a camera that records RAW video." | | | HN davinci resolve luts (#3) |
| S6 | price | "Price -$2199.95 SRP (body), available late October." | 2199.95 | | HN cinematic luts (#7) |
| S7 | reviews | "it's really the best motion graphics package out there" | | | HN motion graphics pack (#11) |
| S8 | question | "After Effects is too expensive and complex for high schools" | | | HN motion graphics pack (#11) |
| S9 | sales | "If you would consider contracting the work out, my contact information is in my profile" | | | HN motion graphics pack (#11) |
| S10 | competitor | "Animation support with simple DX for animations, scrubbing, state and screen transitions" | | | HN video transitions pack (#15) |
| S11 | competitor | "Video component and a whole Netflix clone Hypen app example" | | | HN video transitions pack (#15) |
| S12 | competitor | "letting you build shared component packs and primitives" | | | HN video transitions pack (#15) |
| S13 | price | "They're only like $3 a piece" (böcker om optioner, inte video) | 3.00 | | HN real estate video template (#19) |
| S14 | question | "real estate video template" | | | HN real estate video template (#19) |
| S15 | price | "scrollkit got $200,000 from the Knight Foundation" | 200000.00 | | HN content creator templates (#27) |
| S16 | reviews | "templates exist because in serious publishing businesses, there are not the resources to re-invent the HTML wheel" | | | HN content creator templates (#27) |
| S17 | question | "What options are there for cloud based FFMPEG processing?" | | | SE video editing service (#33) |
| S18 | question | "Extract audio from video preserving audio quality" | | | SE video editing service (#33) |
| S19 | question | "Which software a dubbing studio use for subtitles and closed captioning workflow?" | | | SE video editing service (#33) |
| S20 | question | "Replacement for Windows Live Movie Maker for combining images and audio (Windows 10)?" | | | SE video editing service (#33) |
| S21 | question | "Schedule a live stream of a pre-recorded video" | | | SE video editing service (#33) |
| S22 | question | "I was wondering if any of you would be interested in an one button automatic video editing service." | | | HN video editing service (#35) |
| S23 | competitor | "We launched a free video editing service." | 0.00 | | HN video editing service (#35) |
| S24 | question | "The assumption I have is that the current video editing software is too much hassle for everyone." | | | HN video editing service (#35) |
| S25 | question | "Let me know if I am wrong or right!" | | | HN video editing service (#35) |
| S26 | competitor | "We have both video record and upload options." | 0.00 | | HN video editing service (#35) |

## Researchlogg (sammanfattad)

40 hämtningar planerades över 9 sökord och 4 källor:
- **Etsy:** 403 på alla 9.
- **itch.io:** robots.txt nej på alla 9.
- **Stack Exchange:** för få träffar på 7 av 9 sökord.
- **Hacker News:** 13 signaler avvisades för att citatet inte fanns ordagrant i sidan. Kontrollen fungerar.

Hela loggen finns i körningen ovan.

Efterfrågan bygger på offentliga sidor vid hämtningen och modellens uppskattningar. Den är inte verifierad
förrän riktig försäljning finns (D-063).
