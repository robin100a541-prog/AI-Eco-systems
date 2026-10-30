# hushallsbudget-mall: hushållsbudget i kalkylark (Etsy)

**Status: UTKAST.** Inget är publicerat.

**Bedömning före start (D-058): INTE REDO.** Detaljerna står i `../README.md`.

## Produkt
En hushållsbudget för Google Sheets och Excel på svenska, med:
- en flik per månad med inkomster och utgifter i kategorier, till exempel boende, mat och transport
- en årsöversikt med diagram
- sparmål med en mätare
- en lista över fasta kostnader som förs till varje månad

Den innehåller inga bankkopplingar och inga personuppgifter. Allt skrivs in av köparen. Mallen är ett hjälpmedel och ingen ekonomisk rådgivning.

## Annonstext (utkast)
> **Hushållsbudget på svenska — kalkylark för Google Sheets och Excel (digital nedladdning)**
>
> En flik per månad, årsöversikt med diagram och sparmål. Skriv in dina inkomster och utgifter, så räknar arket ut resten. Fasta kostnader fylls i en gång och följer med varje månad.
>
> Du får: en .xlsx-fil och en länk för att kopiera mallen i Google Sheets. Ingen fysisk produkt skickas.
>
> Mallen är ett hjälpmedel, inte ekonomisk rådgivning.
>
> **AI-användning:** mallen och texten är skapade med hjälp av AI (seller-prompted) och granskade och testade av en människa.

**AI-märkningen.** Etsy kräver att AI-användning anges i annonsen. Etsy förbjuder AI-promptpaket, och det här är inget sådant (`docs/channels.md`, läst 2026-10-21).

## Pris
- **Pris:** 5 USD.
- **Etsys avgifter enligt `docs/channels.md`:**
  - 0,20 USD per annons, som förnyas var fjärde månad
  - 6,5 % i transaktionsavgift
  - en betalningsavgift med okänt belopp. Bedömningen antar 500 SIM per order.
  - Offsite Ads på 12–15 % vid sådan försäljning
- **Moms:** Etsy tar in moms som marknadsplats där det gäller. Detaljerna för EU är inte bekräftade.
- **DAC7:** Etsy rapporterar från 30 försäljningar eller 2 000 euro per år.

## Valideringsplan
- **Tid:** 30 dagar, högst 1 timme per vecka.
- **Kostnad i pengar:** 0 kr. Annonsavgiften på 0,20 USD dras från den första försäljningen. Om Etsy kräver förskottsbetalning görs inget försök utan ett nytt beslut.
- **Annonsering:** ingen. Offsite Ads stängs av om Etsy tillåter det. Det är inte verifierat, se checklistan.
- **Mätning:** som i `frilans-fakturamall`. Varje dag förs besökare, order och avgifter från Etsy Stats in i CSV-filen, med källa, och sedan körs `results import`.

## Mätbara kriterier och regel
| Utfall (verifierat) | Beslut |
|---|---|
| ≥ 3 order per dag i snitt och återbetalningar under 5 % | **Fortsätt:** kör `assess run` med utfallen. Godkänns bara om bedömningen blir redo. |
| 1–3 order per dag | **Ändra:** ett försök till med 7 USD eller ett paket med två mallar. Max ett försök. |
| < 1 order per dag efter 30 dagar, en varning från Etsy eller ett klagomål om AI-märkningen | **Sluta:** avpublicera och sätt initiativet till `retired`. Skriv en lärdom. |

Gränsen 3 order per dag kommer från bedömningen. Vid 3 order per dag klarade 1 av 5 pessimistiska körningar sig fortfarande inte.

## Checklista för grundarna (manuellt; agenterna gör inget av detta)
1. [ ] Besluta att göra försöket och skriv beslutet.
2. [ ] Compliance: läs Etsys avgifter för betalningar och Offsite Ads, och om man kan välja bort Offsite Ads. Skriv in det i `docs/channels.md` med datum.
3. [ ] Granska och prova mallen i både Google Sheets och Excel.
4. [ ] **En grundare** skapar Etsy-kontot i eget namn, godkänner villkoren och verifierar identiteten.
5. [ ] Publicera med annonstexten och AI-märkningen ovan.
6. [ ] Varje dag: skriv in utfallen med källa i CSV-filen. Varje vecka: kör `results import`.
7. [ ] Efter 30 dagar: kör `results report hushallsbudget-mall` och följ regeln.
8. [ ] Riktiga pengar räknas inte in i systemet före Fas 7 (§55).
