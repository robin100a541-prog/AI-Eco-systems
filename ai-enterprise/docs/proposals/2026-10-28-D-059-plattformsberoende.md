# D-059 Skydd mot plattformsberoende (förslag)

- **Status:** Godkänd av Robin 2026-10-30 (D-049), med ändrade värden, se "Grundarnas beslut".
  Gränsvärdena läggs i `config/risk_limits.toml` i en egen PR (PR 7b), som en grundare godkänner.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 7), 2026-10-28
- **Bygger på:** D-054, D-056, D-058, ER-02
- **Gäller:** §25, FR-20

## Problemet
Om nästan alla intäkter kommer från en plattform kan ett stängt konto ta bort hela verksamheten på en dag.
Två plattformar som använder samma betalningsleverantör är inte heller oberoende. Det fanns ingen gräns
för detta, och inget scenario som provade det.

## Förslag
1. **Två nya gränser** i `risk_limits.toml`. De föreslagna värdena kommer från arbetsorder 02:
   - `MAX_PLATFORM_REVENUE_SHARE = 60`: högsta andel av intäkterna för en plattform, i procent.
   - `MIN_ACTIVE_PLATFORMS = 2`: minsta antal oberoende godkända eller aktiva plattformar när företaget har intäkter.
2. **Grupper.** Plattformar som delar ett kritiskt beroende räknas som en, även via en tredje plattform.
   Beroendet står i plattformens `dependencies` i registret, till exempel samma betalningsleverantör.
3. **Andelen** räknas på realiserade intäkter minus återbetalningar de senaste 90 dagarna. Initiativet
   kopplas till plattformen via registret.
4. **På eller över gränsen:**
   - **Varning:** `dependency.warning` skrivs i revisionsloggen vid varje `tick`.
   - **Inga nya initiativ:** nya initiativ på plattformar i gruppen kan inte godkännas eller aktiveras.
   - **Säkerhetsåtgärder** är alltid tillåtna: pausa och avveckla. Redan godkända initiativ kan aktiveras.
5. **Rapport:** `python -m aie registry dependency` visar andelen per grupp och hur mycket intäkt från andra
   plattformar som behövs för att komma under gränsen. Den varnar också när det finns för få oberoende plattformar.
6. **ER-02:**
   - När det finns intäkter och en gräns saknas, stoppas nya initiativ.
   - Utan intäkter finns ingen andel att mäta, och inget stoppas. Simuleringar före första intäkten fungerar därför som förut.
7. **Scenario `platform_ban`:**
   - Plattform A stänger kontot dag 30.
   - Därefter säljer inget där, och systemet pausar plattformen i registret, så att inga utgifter går dit.
   - Plattform B har en egen betalningsleverantör och säljer vidare.
   - Scenarier kan nu ha `[[platforms]]` med beroenden, och initiativ kan ha `platform`.
8. **Registrets CLI byggs med hela systemet.** Samma spärrar gäller där som i simuleringen.

## Grundarnas beslut (Robin, 2026-10-30)
- **Fas 7-pilot:** `MIN_ACTIVE_PLATFORMS = 1` och `MAX_PLATFORM_REVENUE_SHARE = 100`. Piloten säljer på en plattform, så gränserna får inte stoppa den.
- **När Fas 8 startar** blir värdena `MIN_ACTIVE_PLATFORMS = 2` och `MAX_PLATFORM_REVENUE_SHARE = 60`, via en PR med `founder-approved` (punkt i ROADMAP, Fas 8).
- 90 dagars fönster behålls.

## Att avgöra (ursprungligt)
- Gränsvärdena 60 % och 2 plattformar (PR 7b).
- Om 90 dagar är rätt fönster.
- Om ett redan godkänt initiativ ska få aktiveras när gruppen är över gränsen. Förslaget är ja: att stoppa
  det skulle minska intäkten men inte beroendet.

## Kostnad och risk
- **Kostnad:** ingen.
- **Risk:** en plattforms `dependencies` är bara så bra som registret. Ett beroende som ingen har skrivit in syns inte.

## Tester
`tests/unit/test_dependency.py` har 10 tester. De visar att:
- plattformar med ett gemensamt beroende bildar en grupp
- utan intäkter stoppas och varnas inget
- på gränsen stoppas nya initiativ bara på den plattformen
- pausa, avveckla och aktivera befintliga initiativ alltid går
- ett gemensamt beroende räknas ihop
- en saknad gräns stoppar nya initiativ när det finns intäkter (ER-02)
- gamla intäkter faller ur fönstret
- rapporten säger vad som behöver göras
- `platform_ban` fungerar i en hel körning på 60 dagar
- scenariot valideras

`tests/unit/test_config.py` kontrollerar de nya gränstyperna.
