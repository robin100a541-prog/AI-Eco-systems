# kalkylark-stadning: städa och strukturera ett kalkylark (Fiverr, tjänst)

**Status: UTKAST.** Inget är publicerat.

**Bedömning före start (D-058): INTE REDO.** Grundarnas tid, 4 timmar per vecka, är mer än intäkten vid antagen efterfrågan. Detaljerna står i `../README.md`.

## Tjänst
Kunden skickar ett kalkylark. Vi levererar ett städat ark med:
- dubbletter borttagna
- enhetliga datum och tal
- trasiga formler rättade
- tydliga rubriker
- en kort lista över vad som ändrats

Varje leverans görs för just den beställningen. Inget genereras i bulk, eftersom Fiverr förbjuder samma AI-innehåll till flera kunder (`docs/channels.md`).

**Gränser:**
- högst 2 000 rader
- inga personnummer eller känsliga personuppgifter; sådana beställningar avböjs
- ingen makroprogrammering

**Vem som gör vad (§6, inga falska identiteter):**
- Kontot ägs av en grundare.
- Agenterna får göra utkastet till det städade arket och till svaren.
- **Grundaren skickar alla meddelanden och leveranser själv**, tills Compliance har bekräftat vad Fiverr tillåter (R-03).

## Tjänstebeskrivning (utkast)
> **Jag städar och strukturerar ditt kalkylark (Excel eller Google Sheets)**
>
> Dubbletter, blandade datumformat, trasiga formler, otydliga rubriker? Skicka arket, så får du tillbaka en städad version och en lista över varje ändring.
>
> Gäller ark upp till 2 000 rader. Jag tar inte emot ark med personnummer eller andra känsliga personuppgifter.
>
> *Jag använder AI-verktyg som hjälp i arbetet. Varje leverans granskas och anpassas av mig för din beställning.*

**AI-märkningen.** Fiverr har inget uttryckligt krav på att ange AI, men kunder som inte vill ha AI förväntas säga det. Därför står det öppet i beskrivningen.

## Pris
- **Pris:** 25 USD per beställning.
- **Fiverrs avgift:** Fiverr behåller 20 %, alltså 5 USD. Det ger 20 USD netto, före skatt.
- **Grundarnas tid:** cirka 30 minuter per beställning för granskning och leverans.
- **Skattespår:** B eller C. Det är en öppen fråga (Q-05).
- **DAC7:** Fiverr rapporterar tjänsteleverantörer från första euron.

## Valideringsplan
- **Tid:** 30 dagar, högst 4 timmar per vecka.
- **Kostnad i pengar:** 0 kr.
- **Mätning:** varje dag förs visningar av tjänsten, beställningar, intäkt, återbetalningar och avgifter in i CSV-filen, med källa. Visningarna räknas som besökare. Därefter körs `results import`.
- **Mät tiden för varje beställning för sig.** Det är den största kostnaden, och om den är lägre än antaget ändras bedömningen mest.

## Mätbara kriterier och regel
| Utfall (verifierat) | Beslut |
|---|---|
| ≥ 1 beställning per dag och högst 30 minuter per beställning | **Fortsätt:** kör `assess run` med utfallen och den uppmätta tiden i `founder_hours_per_week`. |
| 0,3–1 beställning per dag, eller mer än 30 minuter per beställning | **Ändra:** ett försök till med högre pris (40 USD) eller mindre omfattning. Max ett försök. |
| < 0,3 beställningar per dag efter 30 dagar, ett klagomål om AI eller en varning från Fiverr | **Sluta:** pausa tjänsten och sätt initiativet till `retired`. Skriv en lärdom. |

Gränsen 1 beställning per dag kommer från bedömningen. Vid 0,6 beställningar per dag klarade ingen av de pessimistiska körningarna sig.

## Checklista för grundarna (manuellt; agenterna gör inget av detta)
1. [ ] Besluta att göra försöket och skriv beslutet. Det kostar tid, 4 timmar per vecka.
2. [ ] Compliance: läs Fiverrs regler om integritet, autenticitet och automatiserade meddelanden (R-03). Skriv in dem i `docs/channels.md` med datum.
3. [ ] **En grundare** skapar Fiverr-kontot i eget namn, godkänner villkoren och verifierar identiteten.
4. [ ] Publicera tjänsten med beskrivningen ovan.
5. [ ] Varje beställning: grundaren läser beställningen, granskar agenternas utkast, levererar och skickar alla meddelanden själv.
6. [ ] Varje dag: skriv in utfallen och tiden med källa. Varje vecka: kör `results import`.
7. [ ] Efter 30 dagar: kör `results report kalkylark-stadning` och följ regeln.
8. [ ] Riktiga pengar räknas inte in i systemet före Fas 7 (§55).
