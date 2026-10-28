# D-052 Betald skatt är en egen posttyp; skatteunderlaget väljs i tax.toml (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, F3+F4), 2026-10-28
- **Bygger på:** D-010, D-024, D-032, D-034, D-051
- **Gäller:** ER-19, ER-21, ER-08, §40

## Problemet (verifierat i main `133c69a`)
1. Skatteavsättningen räknades per spår och år men summerades till ett tal. Det fanns inget sätt att bokföra betald skatt. Om en grundare bokförde betalningen som en kostnad eller ett uttag minskade kassan, men avsättningen låg kvar. Skatten räknades då två gånger: en gång som utbetalning och en gång som åtagande.
2. Underlaget var alltid bruttointäkten. Det är försiktigt, men det går inte att välja vinst som underlag när Skatteverket har bekräftat det.

## Förslag
1. **Ny posttyp `tax_payment` i ledgern** (migration 27). Den är en utbetalning (minskar kassan), men varken kostnad eller avgift. Den påverkar alltså inte nettovinsten före skatt (ER-09) eller departementens budgetar. Ledgern byggs om i en transaktion enligt SQLites dokumenterade sätt, och alla poster, id:n, statusar, skattespår och spärrar finns kvar.
2. **`TaxEngine.pay(grundare, spår, år, belopp, underlag)`** bokför betalningen som `settled` med underlaget och `decision:D-052`, och kopplar den till spår och år i `tax_payments`, som är append-only.
   - Avsättningen för just det spåret och året minskar med betalningen och blir aldrig negativ.
   - Bara grundarna bokför betald skatt.
3. **`liability_minor()`** är hela skatten, betald eller inte, och **`reserved_minor()`** är det som återstår att betala. Departementens bas (D-051) räknar med hela skulden, så en betalning ändrar inte basen.
4. **`basis` i `tax.toml`:**
   - `revenue` är standard: bruttointäkt.
   - `profit`: intäkter minus återbetalningar, avgifter och kostnader i de initiativ vars intäkter har spåret. Kostnader utan spårad intäkt minskar inget.

   Systemet byter aldrig underlag självt. Bytet görs först när Skatteverket har bekräftat skattebehandlingen (Q-05).

## Kostnad och risk
- **Kostnad:** ingen.
- **Risk:** ombyggnaden av ledgertabellen är den känsligaste ändringen i arbetsorder 02. Den testas på en databas med schemaversion 26 med poster, rättelser, statusar och skattespår. Alla rader är oförändrade efteråt, `foreign_key_check` är tom, och spärrarna och främmande nycklar fungerar. Misslyckas något rullas hela migrationen tillbaka. Det sågs när det första försöket med `RENAME` stoppades.
- **Granskning:** ska granskas oberoende före Fas 7 (F7).

## Tester
- `tests/unit/test_tax_payment.py`: 8 tester. De visar att:
  - avsättningen blir noll och kassan minskar en gång
  - år och spår inte blandas
  - en överbetalning aldrig ger negativ avsättning
  - bara grundare kan betala, med underlag, och inget kan skrivas om
  - basen står still vid betalning
  - `revenue` är standard och ett okänt underlag avvisas
  - `profit` drar av avgifter och kostnader
  - migrationen bevarar en befintlig ledger
