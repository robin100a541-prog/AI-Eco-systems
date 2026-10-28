# D-053 Godkända utgifter: ett godkännande per utgift, giltigt i 7 dagar, förbrukas en gång (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, F5), 2026-10-28
- **Bygger på:** D-019, D-026, D-049
- **Gäller:** ER-14, ER-03, §21

## Problemet (verifierat i main `fb6765f`)
`BudgetEngine.check()` svarade alltid nej över `HUMAN_APPROVAL_THRESHOLD`, och det fanns inget sätt att ge ett godkännande till just den utgiften. Godkännandekön i `governance/escalation.py` gäller beslut och tvister och är inte kopplad till budgetmotorn. En utgift som en grundare ville godkänna kunde alltså aldrig genomföras, varken i simuleringen eller på riktigt.

## Förslag
1. **`SpendApprovals`** (migration 28): en förfrågan gäller ett departement, ett initiativ, en valuta och ett högsta belopp, och har ett skäl. En grundare godkänner eller avslår (D-049: en räcker), och en förfrågan får högst ett beslut. Allt är append-only.
2. **`BudgetEngine.check(..., approval_id=N)`** godtar godkännandet bara om det är godkänt och oanvänt, högst **7 dagar gammalt** (`VALID_DAYS`), gäller samma departement, initiativ och valuta, och täcker beloppet.
3. Godkännandet ersätter **bara** kravet på en grundare. Budgettak, reserv, `MAX_SINGLE_TRANSACTION`, stop-loss, nödstopp och skyddat läge gäller ändå (§21). Ett godkännande som inte kan användas förbrukas inte.
4. När svaret blir ja **förbrukas** godkännandet. Ett unikt index i databasen gör att det sker exakt en gång, även vid samtidiga försök.
5. **I simuleringen** blir en utgift över tröskeln en förfrågan ("pending"). När en grundare har godkänt den, med `python -m aie spend approve N --as <grundare>`, genomförs utgiften nästa dag om alla gränser fortfarande tillåter det. Ledgerposten pekar på `approval:spend-N`.

## Att avgöra
Giltighetstiden **7 dagar**. Den är ett förslag och kan bli kortare, till exempel 3 dagar för riktiga pengar.

## Kostnad och risk
- **Kostnad:** ingen.
- **Risk:** låg. Ett godkännande kan aldrig ge mer än det godkända beloppet, aldrig användas två gånger och aldrig ta bort en hård gräns.

## Tester
- `tests/unit/test_spend_approvals.py`: 7 tester. De visar att:
  - en utgift utan godkännande får nej
  - ett giltigt godkännande ger ja exakt en gång
  - fel departement, fel initiativ, för stort belopp eller för gammalt godkännande ger nej
  - hårda gränser gäller trots godkännande
  - bara grundare beslutar, en gång
  - två samtidiga anslutningar kan inte förbruka samma godkännande
  - flödet fungerar i simuleringen
- Testerna är körda tre gånger i rad, alla gröna.
