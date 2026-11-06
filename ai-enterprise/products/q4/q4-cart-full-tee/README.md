# Cart Full Wallet Empty T-Shirt, Funny Shopping Season Tee, Gift for Shopper

**Status: UTKAST.** Inget är publicerat, och inget utkast finns i Printify.

- **Tema:** Black Friday
- **Produkt:** tee, sökt i Printifys katalog som "unisex heavy cotton tee"
- **Design:** typografi: CART FULL / WALLET EMPTY (egen design, PNG 4500 × 5400 px, 300 dpi). Filen är `design.png`, och förhandsvisningen `preview.png`.

## Annons (utkast)
- **Titel:** Cart Full Wallet Empty T-Shirt, Funny Shopping Season Tee, Gift for Shopper
- **Taggar:** shopping shirt, funny shopper tee, wallet empty, sale season shirt, funny gift, shopaholic
- **Beskrivning, med AI-upplysning:** AI-assisted design: made with the help of AI and checked by hand. Original artwork, produced by our print partner Printify.
- **Produktionspartner:** Printify

## Pris och marginal per order
| | Normal | Pessimistisk |
|---|---|---|
| Pris + frakt som kunden betalar | 29.99 USD | 29.99 USD |
| Printify: baspris + frakt | 16.00 USD | 19.70 USD |
| Etsys avgifter (annons, 6,5 %, 4 % + 3 SEK) | 3.95 USD | 3.95 USD |
| Offsite Ads (15 % på en fjärdedel av ordren) | 0.00 USD | 1.13 USD |
| Vinst före skatt | 10.04 USD | 5.21 USD |
| Skatt på vinsten (spår C, 40 %) | 4.02 USD | 2.09 USD |
| **Vinst efter skatt** | **6.02 USD** (20.1 %) | **3.12 USD** (10.4 %) |

- **Kostnadernas källa:** antagande: övre gräns för Bella+Canvas 3001 (10,98 USD) och Gildan 5000 (8,80 USD) i tredjepartskällor 2026, inte Printifys API
- **Systemets skattereserv:** 40 % av bruttointäkten (`basis = "revenue"`), 12.00 USD per order. Den hålls undan tills skatten är känd, och den används i spärren nedan.

## Spärren "simulera före start" (D-058)
**INTE REDO** (5 körningar × 90 dagar per scenario, skriptade agenter).

- normal: median efter skatt och grundarnas tid -65081 SIM, netto per dag 1002 SIM
- pessimistic: median efter skatt och grundarnas tid -43233 SIM, netto per dag 357 SIM
- zero_sales: median efter skatt och grundarnas tid -34130 SIM, netto per dag -22 SIM
- skäl: normalt scenario: 5 av 5 körningar saknar vinst efter kostnader, avgifter och skatt
- skäl: normalt scenario: medianmarginalen efter skatt är -6.3 %; minst 10 % krävs
- skäl: pessimistiskt scenario: 5 av 5 körningar saknar vinst efter alla kostnader, avgifter, skatt och grundarnas tid
- antagande: skattespår C antas (Q-05 är öppen)
- antagande: 1 USD-cent = 11 öre i SIM (antagande om växelkurs)
- antagande: efterfrågan är ett antagande, inte uppmätt

## Valideringsplan
- **Antagen efterfrågan:** 10 besökare per dag, 1.5 % konvertering. Källa: antagande: ingen uppmätt efterfrågan; ersätts av Etsys signaler och sedan av verkliga utfall (results import).
- **Försöket:** 30 dagar på Etsy, 0 kr i fasta kostnader. Det börjar först när D-069 är godkänt och spärren säger redo, eller när grundarna uttryckligen beslutar ett försök.
- **Mät:** visningar, favoriter, order och återbetalningar per dag. Importera dem med `python -m aie results import` (D-062). Efter 7 dagar ersätter de uppmätta värdena antagandena i spärren.
- **Fortsätt:** om spärren blir redo med verkliga utfall.
- **Ändra:** pris, titel eller taggar efter 30 dagar, om det finns minst 1 order per 100 visningar men marginalen är för låg.
- **Sluta:** under 1 order per 300 visningar efter 30 dagar, en reklamation om rättigheter, eller en varning från Etsy. Avpublicera och skriv en lärdom.
