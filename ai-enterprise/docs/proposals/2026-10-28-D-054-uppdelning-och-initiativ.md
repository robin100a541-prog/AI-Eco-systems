# D-054 Uppdelade köp räknas också per departement och dag; utgifter bara för godkända initiativ (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`. Kravet kommer från Yorgo i arbetsorder 02 (F6).
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, F6), 2026-10-28
- **Bygger på:** D-028 (godkänt; ändras inte, det här kommer i tillägg), D-049, D-053
- **Gäller:** ER-04, ER-03, §5, §21

## Problemet (verifierat i main `8583613`)
1. D-028 räknar bara köp i **samma initiativ** under sju dagar. Den som delar upp ett köp och ger varje del ett nytt initiativnamn kringgår kontrollen. Fem köp om 250 i fem initiativ på samma dag gav ja, trots att summan 1 250 var över tröskeln 1 000.
2. Budgetmotorn tog emot vilket initiativnamn som helst. Det fanns inget register över vilka initiativ som finns och är godkända.

## Förslag
1. **Utöver D-028:** utgifter i **samma departement samma dag**, i minst två olika initiativ, som tillsammans passerar `HUMAN_APPROVAL_THRESHOLD` flaggas som möjlig uppdelning. Utgiften kräver då en grundare. Bara utgifter som inte redan är godkända räknas, precis som i D-028.
2. **Initiativspärr:** `BudgetEngine(initiatives=...)` frågar initiativregistret (PR 4) före varje utgift. Ett initiativ som inte finns, eller inte är godkänt, ger nej. Kan registret inte svara blir svaret också nej (§59). Innan registret är kopplat görs ingen initiativkontroll.
3. Ett godkännande (D-053) kan lösa uppdelningsflaggan, men aldrig en hård gräns som `MAX_SINGLE_TRANSACTION` (§21).

## Två tester har ändrats, med skäl
- **`test_budget.py`:** hjälpfunktionen gav varje post ett nytt initiativnamn just för att inte se ut som uppdelade köp. Med punkt 1 räcker det inte, så budgettesternas poster märks nu som godkända av en grundare. Budgeten räknar godkända och icke godkända utgifter likadant, så testernas syfte är oförändrat.
- **`test_split.py`:** köpet i ett annat initiativ görs en dag tidigare. Det visar fortfarande att D-028 inte räknar andra initiativ. Samma dag räknas det enligt punkt 1, vilket testas i `test_split_department.py`.

## Kostnad och risk
- **Kostnad:** ingen.
- **Risk:** fler utgifter kräver en grundare samma dag. Det är avsikten med ER-04.

## Tester
`tests/unit/test_split_department.py`: 6 tester. De visar att:
- olika initiativnamn samma dag flaggas
- andra departement och små summor inte flaggas
- ett godkännande inte kringgår hårda gränser
- okända och icke godkända initiativ ger nej
- ett trasigt register ger nej
- utan register ändras ingenting
