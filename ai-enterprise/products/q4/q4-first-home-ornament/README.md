# Our First Home 2026 Ornament, New Home Christmas Keepsake, Housewarming Gift

**Status: UTKAST.** Inget är publicerat, och inget utkast finns i Printify.

- **Tema:** jul, ny bostad
- **Produkt:** ornament, sökt i Printifys katalog som "ornament"
- **Design:** typografi: OUR FIRST / HOME / 2026 (egen design, PNG 1200 × 1200 px, 300 dpi). Filen är `design.png`, och förhandsvisningen `preview.png`.

## Annons (utkast)
- **Titel:** Our First Home 2026 Ornament, New Home Christmas Keepsake, Housewarming Gift
- **Taggar:** first home ornament, new home gift, housewarming gift, 2026 ornament, christmas keepsake, new homeowner
- **Beskrivning, med AI-upplysning:** AI-assisted design: made with the help of AI and checked by hand. Original artwork, produced by our print partner Printify.
- **Produktionspartner:** Printify

## Pris och marginal per order
| | Normal | Pessimistisk |
|---|---|---|
| Pris + frakt som kunden betalar | 20.99 USD | 20.99 USD |
| Printify: baspris + frakt | 13.00 USD | 16.10 USD |
| Etsys avgifter (annons, 6,5 %, 4 % + 3 SEK) | 2.92 USD | 2.92 USD |
| Offsite Ads (15 % på en fjärdedel av ordren) | 0.00 USD | 0.79 USD |
| Vinst före skatt | 5.07 USD | 1.18 USD |
| Skatt på vinsten (spår C, 40 %) | 2.03 USD | 0.48 USD |
| **Vinst efter skatt** | **3.04 USD** (14.5 %) | **0.70 USD** (3.3 %) |

- **Kostnadernas källa:** antagande utan källa: ingen verifierad siffra hittad
- **Systemets skattereserv:** 40 % av bruttointäkten (`basis = "revenue"`), 8.40 USD per order. Den hålls undan tills skatten är känd, och den används i spärren nedan.

## Spärren "simulera före start" (D-058)
**INTE REDO** (5 körningar × 90 dagar per scenario, skriptade agenter).

- normal: median efter skatt och grundarnas tid -85454 SIM, netto per dag 818 SIM
- pessimistic: median efter skatt och grundarnas tid -44395 SIM, netto per dag 107 SIM
- zero_sales: median efter skatt och grundarnas tid -34130 SIM, netto per dag -22 SIM
- skäl: normalt scenario: 5 av 5 körningar saknar vinst efter kostnader, avgifter och skatt
- skäl: normalt scenario: medianmarginalen efter skatt är -15.5 %; minst 10 % krävs
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
