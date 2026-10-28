# Produktutkast (arbetsorder 02, PR 11)

**Status: UTKAST. Ingenting är publicerat, inget konto är skapat och inga villkor är godkända.**

Det här är tre kandidater som utkast. Allt som görs på riktigt görs manuellt av en grundare, enligt checklistan i varje utkast.

**Vem som har gjort vad:**
- Claude har skrivit utkasten i en session med Yorgo.
- Systemets bedömning före start (D-058) har kört dem med skriptade agenter.
- Inga språkmodellsagenter i systemet har varit inblandade.

## Resultat: ingen kandidat klarar PR 6:s spärr i dag
Bedömningen är körd med repots config: 500 kr kapital, 100 kr per timme för grundarnas tid, skattespår C som antagande, 5 körningar × 90 dagar per scenario och skriptade agenter. Utskriften är kopierad från körningen 2026-10-28:

| Kandidat | Plattform | Pris | Antagen efterfrågan | Resultat | Varför |
|---|---|---|---|---|---|
| [hushallsbudget-mall](hushallsbudget-mall/README.md) | Etsy | 5 USD | 15 besökare/dag, 2 % | **INTE REDO** | normalt scenario: median −72 838 SIM efter skatt och grundarnas tid; pessimistiskt −112 834 |
| [frilans-fakturamall](frilans-fakturamall/README.md) | Gumroad | 9 USD | 8 besökare/dag, 3 % | **INTE REDO** | normalt scenario: median −25 010 SIM; pessimistiskt −117 410 |
| [kalkylark-stadning](kalkylark-stadning/README.md) | Fiverr | 25 USD | 5 besökare/dag, 2 % | **INTE REDO** | 4 timmar per vecka för grundarna (5 714 SIM per dag) är mer än intäkten |

**Gemensamt skäl:** grundarnas tid räknas som kostnad. Med de antagna volymerna är nettot per dag, före grundarnas tid, mindre än tiden kostar. Det gäller i båda scenarierna.

**Vad som skulle krävas.** Jag körde samma bedömning med fler besökare och samma konvertering, för att hitta en gräns. Alla rader nedan är fortfarande antaganden.

| Kandidat | Besökare/dag | Ungefär order/dag | Resultat |
|---|---|---|---|
| frilans-fakturamall | 32 | 0,96 | inte redo: pessimistiskt 5 av 5 utan vinst |
| frilans-fakturamall | 48 | 1,44 | inte redo: pessimistiskt 4 av 5 utan vinst |
| hushallsbudget-mall | 90 | 1,80 | inte redo: pessimistiskt 5 av 5 utan vinst |
| hushallsbudget-mall | 150 | 3,00 | inte redo: pessimistiskt 1 av 5 utan vinst |
| kalkylark-stadning | 30 | 0,60 | inte redo: pessimistiskt 5 av 5 utan vinst |

**Slutsats:** ingen av kandidaterna får godkännas eller få utgifter nu. Spärren gör att det inte går (D-058).

Det enda sättet att få veta den verkliga efterfrågan är ett manuellt försök. Det ska kosta 0 kr i pengar och vara tidsbegränsat. Mät efterfrågan, importera utfallen (`python -m aie results import`, D-062) och bedöm igen. Med minst 7 dagar med utfall ersätter de uppmätta värdena antagandena.

Ett sådant försök är ett beslut för grundarna. Det kostar tid, och det kräver konto och godkända villkor, som bara en grundare får hantera.

## Filer
- `initiatives.toml`: kandidaterna som initiativ i registret, med status `idea`. Efterfrågan är märkt som antagande.
- `<kandidat>/README.md`: produktutkast, annonstext, pris, valideringsplan, kriterier, regel för att fortsätta, ändra eller sluta, och grundarnas checklista.

## Provkör bedömningen själv
```bash
# i en egen datamapp, med miljön sim
cp products/initiatives.toml config/registry/produkter.toml   # bara i en lokal kopia; committa inte
python -m aie registry import --as yorgo
python -m aie assess run frilans-fakturamall --as yorgo
```
