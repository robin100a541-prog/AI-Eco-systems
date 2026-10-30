# D-062 Utfall från verkligheten: import med källa, före antaganden, prognos mot utfall (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 10), 2026-10-28
- **Bygger på:** D-006, D-048, D-058, §29
- **Gäller:** FR-16, FR-20

## Problemet
Varje bedömning bygger på antaganden om efterfrågan, konvertering och avgifter. Det fanns inget sätt att
föra in vad som faktiskt hände när grundarna har sålt något på riktigt. Därför kunde ingen jämföra prognosen med utfallet.

## Förslag
1. **`python -m aie results import <fil.csv> --as <grundare>`** importerar en rad per dag och initiativ: besökare, order, intäkt, återbetalningar, avgifter och kostnader, i SEK eller USD och i minsta enhet.
2. **Källa krävs** på varje rad: en länk, ett kvitto eller en fil. Ordet "antagande" godtas inte som källa.
3. **Hela filen avvisas** om en rad är fel. Det gäller till exempel en dag i framtiden, ett okänt initiativ, decimaltal, negativa tal eller fler order än besökare.
4. **Bara grundare** importerar. En agent kan aldrig skriva in utfall.
5. **Append-only, migration 32 `real_results`:**
   - Samma rad sparas en gång.
   - En rättelse är en ny rad med en egen källa.
   - Filens SHA-256 och importen loggas.
6. **Märkning:** allt som importeras märks **verifierat i verkligheten**.
7. **Före antaganden:**
   - Med minst 7 dagar ersätter de uppmätta värdena besökare per dag, konvertering och återbetalningar i `assess run` (D-058).
   - Är plattformens avgift okänd ersätts även den, med avgiften per order.
   - Kända avgifter skrivs inte över.
   - Det som inte är uppmätt förblir ett märkt antagande, till exempel skattespåret.
8. **`python -m aie results report <initiativ>`** visar utfallet (verifierat) mot prognosen (simulerat). Prognosen kommer från den senaste godkända bedömningen och registret.
9. **Mallen `docs/templates/utfall.csv`** har bara rubrikraden, så att inga exempelsiffror kan importeras av misstag.

## Att avgöra
- Om 7 dagar räcker för att ersätta ett antagande.
- Om utfall i en annan valuta än SEK och USD ska tillåtas.

## Kostnad och risk
- **Kostnad:** ingen.
- **Risk:** en felaktig källa ger felaktiga "verifierade" siffror. Därför krävs en källa på varje rad, importen loggas, och inget kan skrivas om i efterhand.

## Tester
`tests/unit/test_results.py` har 7 tester. De visar:
- att importen är idempotent och append-only
- att en dålig rad avvisar hela filen, i 8 fall
- att bara grundare importerar
- att minst 7 dagar ersätter antaganden, även i USD
- att färre dagar och kända avgifter inte ändras
- att rapporten visar prognos mot utfall
- att kommandot fungerar, från ett okänt initiativ till lyckad import, lista och rapport
