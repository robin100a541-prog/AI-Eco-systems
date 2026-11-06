# Fika Club Tote Bag, Swedish Coffee Break Canvas Bag, Gift for Coffee Lover

**Status: UTKAST.** Inget är publicerat, och inget utkast finns i Printify.

- **Tema:** nisch: svensk fika, presenter
- **Produkt:** tote, sökt i Printifys katalog som "tote bag"
- **Design:** typografi: FIKA / CLUB (egen design, PNG 3600 × 3600 px, 300 dpi). Filen är `design.png`, och förhandsvisningen `preview.png`.

## Annons (utkast)
- **Titel:** Fika Club Tote Bag, Swedish Coffee Break Canvas Bag, Gift for Coffee Lover
- **Taggar:** fika tote, swedish gift, coffee lover gift, canvas tote, scandinavian bag, coffee break
- **Beskrivning, med AI-upplysning:** AI-assisted design: made with the help of AI and checked by hand. Original artwork, produced by our print partner Printify.
- **Produktionspartner:** Printify

## Pris och marginal per order
| | Normal | Pessimistisk |
|---|---|---|
| Pris + frakt som kunden betalar | 27.49 USD | 27.49 USD |
| Printify: baspris + frakt | 16.50 USD | 20.35 USD |
| Etsys avgifter (annons, 6,5 %, 4 % + 3 SEK) | 3.67 USD | 3.67 USD |
| Offsite Ads (15 % på en fjärdedel av ordren) | 0.00 USD | 1.04 USD |
| Vinst före skatt | 7.32 USD | 2.43 USD |
| Skatt på vinsten (spår C, 40 %) | 2.93 USD | 0.98 USD |
| **Vinst efter skatt** | **4.39 USD** (16.0 %) | **1.45 USD** (5.3 %) |

- **Kostnadernas källa:** antagande utan källa: ingen verifierad siffra hittad
- **Systemets skattereserv:** 40 % av bruttointäkten (`basis = "revenue"`), 11.00 USD per order. Den hålls undan tills skatten är känd, och den används i spärren nedan.

## Spärren "simulera före start" (D-058)
**INTE REDO** (5 körningar × 90 dagar per scenario, skriptade agenter).

- normal: median efter skatt och grundarnas tid -101317 SIM, netto per dag 1279 SIM
- pessimistic: median efter skatt och grundarnas tid -41596 SIM, netto per dag 164 SIM
- zero_sales: median efter skatt och grundarnas tid -34130 SIM, netto per dag -22 SIM
- skäl: normalt scenario: 5 av 5 körningar saknar vinst efter kostnader, avgifter och skatt
- skäl: normalt scenario: 1 av 5 körningar gick inte med vinst de sista 30 dagarna
- skäl: normalt scenario: medianmarginalen efter skatt är -12.8 %; minst 10 % krävs
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
