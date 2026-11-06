# Nordic Snowflake Pattern Mug, Scandinavian Winter Coffee Cup, Christmas Gift

**Status: UTKAST.** Inget är publicerat, och inget utkast finns i Printify.

- **Tema:** jul, nordiskt mönster
- **Produkt:** mug, sökt i Printifys katalog som "ceramic mug"
- **Design:** mönster: snowflake (egen design, PNG 2700 × 1050 px, 300 dpi). Filen är `design.png`, och förhandsvisningen `preview.png`.

## Annons (utkast)
- **Titel:** Nordic Snowflake Pattern Mug, Scandinavian Winter Coffee Cup, Christmas Gift
- **Taggar:** snowflake mug, nordic mug, scandinavian gift, winter mug, christmas mug, geometric pattern
- **Beskrivning, med AI-upplysning:** AI-assisted design: made with the help of AI and checked by hand. Original artwork, produced by our print partner Printify.
- **Produktionspartner:** Printify

## Pris och marginal per order
| | Normal | Pessimistisk |
|---|---|---|
| Pris + frakt som kunden betalar | 26.49 USD | 26.49 USD |
| Printify: baspris + frakt | 14.50 USD | 18.15 USD |
| Etsys avgifter (annons, 6,5 %, 4 % + 3 SEK) | 3.56 USD | 3.56 USD |
| Offsite Ads (15 % på en fjärdedel av ordren) | 0.00 USD | 1.00 USD |
| Vinst före skatt | 8.43 USD | 3.78 USD |
| Skatt på vinsten (spår C, 40 %) | 3.38 USD | 1.52 USD |
| **Vinst efter skatt** | **5.05 USD** (19.1 %) | **2.26 USD** (8.5 %) |

- **Kostnadernas källa:** antagande: över de 4,25–6,21 USD som tredjepartskällor anger för en 11 oz mugg, inte Printifys API
- **Systemets skattereserv:** 40 % av bruttointäkten (`basis = "revenue"`), 10.60 USD per order. Den hålls undan tills skatten är känd, och den används i spärren nedan.

## Spärren "simulera före start" (D-058)
**INTE REDO** (5 körningar × 90 dagar per scenario, skriptade agenter).

- normal: median efter skatt och grundarnas tid -67356 SIM, netto per dag 1361 SIM
- pessimistic: median efter skatt och grundarnas tid -40360 SIM, netto per dag 297 SIM
- zero_sales: median efter skatt och grundarnas tid -34130 SIM, netto per dag -22 SIM
- skäl: normalt scenario: 5 av 5 körningar saknar vinst efter kostnader, avgifter och skatt
- skäl: normalt scenario: medianmarginalen efter skatt är -7.7 %; minst 10 % krävs
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
