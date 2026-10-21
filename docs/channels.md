# Kanalregister — försäljningskanaler och intäktsvägar

Beslut: D-011. Varje kanal utvärderas med mallen nedan innan den får användas. I drift fylls mallen i av **Research**-avdelningen, granskas av **Compliance** och **CFO**, och godkänns av grundarna. Fram till Fas 3 fylls den i av grundarna tillsammans med Claude.

Status: `IDÉ` → `UNDERSÖKT` → `GRANSKAD` (Compliance + CFO) → `GODKÄND` (grundare) → `AKTIV` / `PAUSAD` / `AVVECKLAD`

## Mall

| Fält | Innehåll |
|---|---|
| Kanal | Namn + URL |
| Vad säljs | Produkt / tjänst / uppdrag |
| Avgifter | Alla avgifter, med källa och datum |
| Moms mot köpare | Sköter plattformen moms? (merchant of record / marknadsplats / nej) |
| Skattespår (D-010) | A ISK · B egenanställning · C enkelt bolag · D hobby |
| DAC7 | Rapporteras ni till Skatteverket? Från vilken nivå? |
| AI-regler | Tillåtet? Krav på att ange AI? Förbjudna varianter? |
| Automationsregler | Får program publicera/svara? Finns API? Kräver API godkännande? |
| Kontoägare | Vilken grundare äger och verifierar kontot |
| Risker | Kontoavstängning, återbetalningar, IP-intrång, beroende av plattformen |
| Minsta test | Billigaste sättet att testa efterfrågan |
| Avbrottskriterier | När kanalen pausas |
| Källor | Länkar + datum då de lästes |
| Öppna frågor | Det som inte kunde verifieras |

---

## Gumroad — `UNDERSÖKT` (2026-10-21)
- **Säljs:** digitala produkter.
- **Avgifter:** 10 % + 0,50 USD per direktförsäljning; 30 % via Discover; ingen månadsavgift.
- **Moms:** Gumroad är merchant of record och tar in/betalar moms där de har skyldighet.
- **Skattespår:** C (eventuellt D).
- **AI-regler:** ej kontrollerat. **Automation:** ej kontrollerat.
- **Källor:** https://gumroad.com/pricing (2026-10-21)

## Etsy — `UNDERSÖKT` (2026-10-21)
- **Säljs:** digitala nedladdningar, design som tillverkas av tredje part.
- **Avgifter:** 0,20 USD/annons (förnyas var 4:e mån), 6,5 % transaktion, betalningsavgift, Offsite Ads 12–15 % vid sådan försäljning.
- **Moms:** Etsy tar in moms som marknadsplats där det gäller; EU-detaljer ej bekräftade.
- **Skattespår:** C. **DAC7:** ja, om ≥ 30 försäljningar eller ≥ 2 000 euro/år.
- **AI-regler:** tillåtet som "Seller-prompted AI creations"; AI-användning **måste anges** i annonsen; AI-promptpaket förbjudna.
- **Automation:** ej kontrollerat (Etsy har API; villkor för appgodkännande ska läsas).
- **Källor:** https://etsy.com/legal/creativity, https://checkoutpage.com/blog/etsy-fees (2026-10-21)

## Fiverr — `UNDERSÖKT` (2026-10-21)
- **Säljs:** uppdrag/tjänster (text, kod, design, analys).
- **Avgifter:** ofta angivet 20 % av säljarens intäkt — **ej bekräftat i primärkälla**.
- **Skattespår:** B (egenanställning) eller C. **DAC7:** tjänsteleverantörer rapporteras från första euron.
- **AI-regler:** AI-genererat innehåll tillåtet; säljaren måste ha rättigheterna, följa AI-verktygens villkor och leverera **anpassat arbete för varje beställning**. Förbjudet: samma AI-innehåll till flera kunder ("bulk"), vilseledande innehåll, deepfakes och falska konton. Uttryckligt krav på att ange AI saknas, men kunder som inte vill ha AI förväntas säga det.
- **Automation och identitet:** ej verifierat — Fiverrs regler om integritet och autenticitet kunde inte läsas. **Måste kontrolleras innan start**, särskilt om agenter får skriva kundmeddelanden.
- **Konstitutionen (§6):** inga falska identiteter. Förslag: kontot ägs av en grundare; agenter skriver utkast och gör arbetet; grundaren skickar meddelanden tills Compliance har bekräftat vad Fiverr tillåter.
- **Källor:** https://help.fiverr.com/hc/en-us/articles/32243564776593 (2026-10-21)
