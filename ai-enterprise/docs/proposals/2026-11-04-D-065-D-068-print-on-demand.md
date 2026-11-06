# D-065–D-068 Print-on-demand: kedjan, kalkylen, reglerna och kontona (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det (D-049) och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 04), 2026-11-04
- **Bygger på:** grundarbeslutet 2026-11-04 (Yorgo: print-on-demand inför Q4), D-008, D-009, D-049, D-056, D-058, D-062
- **Prompten:** `docs/prompts/04-pod-q4.md`

## D-065 Kedjan Printify → Etsy → Pinterest och Instagram
1. **Kedjan:** Printify är leverantör på gratisplanen, och Etsy är säljsida. Pinterest och Instagram står för marknadsföringen. Inga fasta kostnader.
2. **Verktyg:** varje externt anrop är ett eget verktyg bakom Authorization Engine. Nödstoppet och skyddat läge gäller därför. Verktygen är `printify.read`, `printify.draft`, `etsy.read`, `pinterest.trends`, `pinterest.pin` och `instagram.publish`. De ligger i `permissions.toml` i en egen PR med `founder-approved`.
3. **Nycklar och tokens:** de läses bara från miljövariabler och GitHub-hemligheter, eller från token-filer utanför repot. De skrivs aldrig ut och committas aldrig.
4. **Printify-klienten:**
   - urllib med Bearer-token, egen User-Agent och tidsgräns
   - högst 3 återförsök vid 429/5xx, där `Retry-After` följs
   - minst 0,65 s mellan anrop, eftersom katalogen tillåter högst 100 per minut
   - den kan aldrig anropa publicering
5. **Daglig läsning av katalogen** i `printify-catalog.yml`:
   - körs bara på schema och knapp, aldrig på PR:er
   - körs bara i huvudrepot, så hemligheten når aldrig en fork
6. **Undantag från D-056:** API-klienterna i `src/aie/pod/` får nämna sin plattform. Avgifter, regler och val av plattform ligger fortfarande i registret och `config/`.

## D-066 Q4-idéer med verkliga kostnader och spärren
1. **Kalkylen per order** (`aie.pod.costs`) följer Etsys avgifter, verifierade 2026-11-04:
   - 0,20 USD per annons
   - 6,5 % av pris och frakt
   - 4 % + 3,00 SEK av pris, frakt och moms, för en säljare med svensk bank
   - 15 % Offsite Ads på de order som kommer via annonser

   Till det kommer Printifys baspris och frakt. Skatten visas på två sätt: på vinsten (spår C, 40 %), och som systemets reserv på bruttointäkten.
2. **Två varianter av kalkylen:**
   - **Normal:** antagna kostnader.
   - **Pessimistisk:** baspris + 20 %, frakt + 30 %, och en fjärdedel av ordren via Offsite Ads.

   Varje idé går dessutom genom spärren D-058: normalt, pessimistiskt och noll försäljning.
3. **Kostnaderna är märkta antaganden** tills Printifys API ger riktiga siffror:
   - frakten kommer från `printify.read`
   - baspriset finns inte i katalogen, utan bara på en produkt (`cost`), och kräver alltså ett opublicerat utkast (D-069)
4. **Utkast:** idéerna sparas i `products/q4/`. Inget publiceras.

## D-067 Egna motiv och Etsys regler kontrolleras i koden
1. **Spärrlistan:** `config/ip_blocklist.toml` innehåller varumärken, figurer, kända personer, kopiering och skyddsmärken. En träff stoppar utkast, design och annons. Det är en spärr mot uppenbara fel, och Compliance granskar ändå före publicering.
2. **Etsys krav** står i `config/pod.toml [etsy.listing_rules]`:
   - Printify ska anges som produktionspartner.
   - AI-användning ska stå i annonsen.
   - Titeln får ha högst 140 tecken, och annonsen högst 13 taggar på högst 20 tecken var.
3. **Motiven:** tills R-12 är besvarat ritar systemet själv, med typografi i en egen pixelfont och geometriska mönster. Tryckfilerna är PNG med 300 dpi, eftersom Printify tar PNG och JPEG men inte nämner SVG.

## D-068 Konton, OAuth och de väntande klienterna
1. **Klienterna för Etsy, Pinterest och Instagram:**
   - är byggda och testade mot mockar
   - är **avstängda** i `pod.toml` tills konto, nyckel och D-069 finns
2. **`python -m aie connect etsy|pinterest|instagram`:**
   - OAuth 2 med PKCE (S256) och kontroll av `state`
   - en lokal callback på 127.0.0.1, eller inklistrad adress när tjänsten kräver https (Etsy och Meta)
   - token sparas utanför repot med rättighet 600
3. **Pinterest:** trenderna används direkt och sparas inte, eftersom riktlinjerna förbjuder att API-data sparas. Trends API riktar sig till byråer, enterprise och partner, så det är inte säkert att vi får tillgång.
4. **Instagram:**
   - bara JPEG från en publik adress, och R-13 gäller hur vi skapar JPEG
   - Metas gräns anges till både 50 och 100 per dygn, och klienten stannar alltid vid 50
5. **Dygnsgränser:** varje skrivande anrop reserveras atomärt i `pod_actions` (migration 38) innan det skickas.

## Kostnad och risk
- **Kostnad:** 0 kr. Printify Premium (39 USD/mån) är inte påslaget och kräver ett eget beslut.
- **Risk:**
  - Kostnaderna och efterfrågan är antaganden tills API:t och utfallen finns. Därför är de märkta, och spärren gäller.
  - Ett konto på en plattform kan stängas (D-059).
  - En kontroll av rättigheter missar alltid något. Därför granskar Compliance.

## Tester
Alla utan nätverk:
- `test_printify.py`: 9 tester
- `test_printify_workflow.py`: 2 tester
- `test_pod_rules.py`: 3 tester
- `test_pod_channels.py`: 9 tester
- `test_pod_q4.py`: 6 tester
- registertestet är uppdaterat
