# frilans-fakturamall: mallpaket för svenska frilansare (Gumroad)

**Status: UTKAST.** Inget är publicerat.

**Bedömning före start (D-058): INTE REDO.** Detaljerna står i `../README.md`.

## Produkt
Ett kalkylark för Google Sheets och Excel, med fyra flikar:
1. **Offert:** kundens uppgifter, rader med arbete och material, moms 25/12/6/0 %, giltighetstid.
2. **Faktura:** fakturanummer i följd, förfallodag, OCR- eller referensfält och summa med moms. Raden om F-skatt kan slås av och på.
3. **Tidrapport:** datum, kund, uppgift och timmar. Summan per kund och månad förs automatiskt till fakturan.
4. **Instruktioner:** hur mallen fylls i.

Mallen är **ingen rådgivning**. Användaren ansvarar själv för att fakturan uppfyller mervärdesskattelagens krav.

Allt skapas av en grundare eller av agenterna som ett utkast i repot. Grundaren granskar varje formel för hand innan något säljs.

## Annonstext (utkast)
> **Offert, faktura och tidrapport för frilansare — svensk mall för Google Sheets och Excel**
>
> Fyra flikar som hänger ihop: skriv tiden i tidrapporten, så hamnar summan på fakturan. Moms 25, 12, 6 eller 0 %, löpande fakturanummer och förfallodag.
>
> Du får: en .xlsx-fil, en länk för att kopiera mallen i Google Sheets och en instruktion på svenska.
>
> Mallen är ett hjälpmedel, inte skatte- eller redovisningsrådgivning. Kontrollera att din faktura uppfyller kraven för din verksamhet.
>
> *Mallen och texten är skapade med hjälp av AI och granskade av en människa.*

**AI-märkningen.** Gumroads AI-regler är inte kontrollerade (`docs/channels.md`). Märkningen är med ändå, eftersom den ärligt beskriver hur produkten är gjord (§6). Compliance ska läsa Gumroads regler före publicering. Det är punkt 2 i checklistan.

## Pris
- **Pris:** 9 USD.
- **Gumroads avgift:** 10 % + 0,50 USD per direktförsäljning. Det ger 1,40 USD i avgift och 7,60 USD netto per order, före skatt.
- **Moms:** Gumroad är merchant of record och tar in moms (`docs/channels.md`).
- **Skattespår:** C, men det är en öppen fråga (Q-05).

## Valideringsplan
- **Tid:** 30 dagar från publicering, högst 1 timme per vecka för grundarna.
- **Kostnad i pengar:** 0 kr. Ingen annonsering och ingen betald plats.
- **Trafik:** bara organisk trafik och delningar som grundarna gör själva under eget namn. Inga falska konton och inga köpta omdömen (§6).
- **Mätning:** varje dag förs besökare, order, intäkt, återbetalningar och avgifter från Gumroads statistik in i `docs/templates/utfall.csv`, med en länk eller skärmdump som källa. Därefter körs `python -m aie results import`.

## Mätbara kriterier och regel
Efter 30 dagar, eller tidigare om stoppregeln slår till:

| Utfall (verifierat) | Beslut |
|---|---|
| ≥ 2 order per dag i snitt och återbetalningar under 5 % | **Fortsätt:** kör `assess run`. Med minst 7 dagars utfall ersätter de uppmätta värdena antagandena. Godkänns bara om bedömningen blir redo. |
| 0,5–2 order per dag | **Ändra:** ett försök till på 30 dagar, med ett annat pris (12 USD) eller en annan målgrupp. Max ett försök. |
| < 0,5 order per dag efter 30 dagar, eller återbetalningar ≥ 10 %, eller ett klagomål om felaktigt innehåll | **Sluta:** avpublicera och sätt initiativet till `retired`. Skriv en lärdom. |

Gränsen 2 order per dag kommer från bedömningen. Vid 1,44 order per dag klarade 4 av 5 pessimistiska körningar sig inte (`../README.md`).

## Checklista för grundarna (manuellt; agenterna gör inget av detta)
1. [ ] Besluta att göra försöket. Det kostar 0 kr men tid. Skriv beslutet i `DECISIONS.md` eller som en kommentar till PR:en.
2. [ ] Compliance: läs Gumroads villkor och AI-regler och skriv in dem i `docs/channels.md` med datum.
3. [ ] Granska varje formel i mallen och prova med tre påhittade fakturor.
4. [ ] **En grundare** skapar Gumroad-kontot i eget namn, godkänner villkoren och verifierar kontot. Lägg inte in något betalkort.
5. [ ] Publicera produkten med annonstexten ovan, efter en sista manuell granskning.
6. [ ] Skriv in dagens utfall varje dag i en CSV-fil enligt `docs/templates/utfall.csv`, med källa.
7. [ ] Kör `python -m aie results import utfall.csv --as <grundare>` minst en gång i veckan.
8. [ ] Efter 30 dagar: kör `python -m aie results report frilans-fakturamall` och följ regeln ovan.
9. [ ] Riktiga pengar på kontot räknas inte in i systemet förrän Fas 7:s villkor är uppfyllda (§55).
