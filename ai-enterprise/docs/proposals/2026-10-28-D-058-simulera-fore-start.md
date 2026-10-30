# D-058 Simulera före start: inget initiativ godkänns, listas eller får utgifter utan godkänd bedömning (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 6), 2026-10-28
- **Bygger på:** D-042, D-043, D-047, D-048, D-054, D-056
- **Gäller:** §54, §26, FR-15, FR-16

## Problemet
D-048 bedömde ett scenario som en grundare hade skrivit för hand. Det fanns ingen koppling mellan
bedömningen och det som faktiskt godkändes. Ett initiativ kunde godkännas, och få utgifter, utan att
någon hade simulerat just det, och utan pessimistiskt scenario.

## Förslag
1. **`python -m aie assess run <initiativ>`** bygger scenarierna automatiskt från registret: initiativets pris, styckkostnad och efterfrågan, och plattformens avgifter. Varje scenario körs `min_runs` gånger med olika seed, med samma agenter och spärrar som vanligt.

   | Scenario | Efterfrågan | Returer | Krav |
   |---|---|---|---|
   | normalt | som registrerat | som registrerat | D-048 |
   | pessimistiskt | × 0,25 | × 2 | vinst efter alla kostnader, avgifter, skatt och grundarnas tid i varje körning |
   | noll försäljning | 0 | – | förlusten i pengar högst `MAX_SINGLE_EXPERIMENT_LOSS`, och ingen nödbroms |

2. **Kostnader som marknadsmodellen inte har** dras av och redovisas: grundarnas tid (timmar per vecka × `founder_hour_value_minor`, 100 kr per timme som antagande), plattformens månadsavgift och startavgift.
3. **Antaganden** står i `simulation.toml` under `[assessment]` och listas i varje rapport: växelkurs, okända avgifter, skattespår C och efterfrågan som antagande. Rapporten säger uttryckligen att resultatet bara gäller antagandena. En **känslighetsanalys** sorterar pris, konvertering, besökare, returer, procentavgift och styckkostnad efter påverkan.
4. **Bedömningen sparas** med exakt de parametrar den gällde (SHA-256 av initiativets och plattformens data, migration 31). En grundare godkänner den, och bara om den är redo.
5. **Hård spärr** i registret och budgetmotorn:
   - Ett initiativ blir `approved` eller `active`, och får utgifter, bara med en godkänd bedömning med exakt samma parametrar.
   - En plattform blir `approved` eller `active` bara med minst en sådan bedömning för ett initiativ på den.
   - Ändras parametrarna går initiativet tillbaka till `reviewed` och måste bedömas om.
   - Spärren kan inte stängas av.
6. **Automatisk paus:** ett aktivt initiativ vars netto i ledgern de senaste 14 dagarna är lägre än det pessimistiska scenariots netto per dag × 14 pausas av systemet och får en incident. Bara en grundare kan aktivera det igen.
7. **I simuleringen** registreras scenariots initiativ med en bedömning av typen `scenario`, eftersom scenariokörningen själv är testet. Den typen kan bara finnas i simuleringens egen databas, aldrig i prod.

## Att avgöra
- Antagandena: växelkursen 1 USD ≈ 11 kr, 100 kr per timme för grundarnas tid, och 5 % och 5 kr för okända avgifter.
- Om 14 dagar är rätt tid före automatisk paus.

## Kostnad och risk
- **Kostnad:** ingen. Allt körs lokalt.
- **Risk:** en bedömning är aldrig bättre än antagandena. Därför märks de och visas i varje rapport.

## Tester
- `tests/unit/test_assessment.py`: 6 tester. De visar att:
  - ett starkt initiativ blir redo och först då kan godkännas
  - grundarnas tid och låg efterfrågan ger inte redo, och det kan inte godkännas
  - scenarierna kommer från registret, med märkta antaganden, noll försäljning och sorterad känslighetsanalys
  - bedömningen bara körs i sim
  - 14 dagar under prognosen ger paus och incident, men inte tidigare
  - på eller över prognosen fortsätter initiativet
- `tests/unit/test_registry.py` har fått 3 nya tester:
  - utan godkänd och redo bedömning godkänns inget
  - ändrade parametrar gör bedömningen ogiltig
  - scenariobedömningar finns bara i sim
