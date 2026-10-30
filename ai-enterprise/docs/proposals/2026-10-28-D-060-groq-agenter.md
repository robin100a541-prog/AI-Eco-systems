# D-060 Simulering med Groq-agenter: bara simulerade data, ingen reserv och paus när kvoten är slut (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 8), 2026-10-28
- **Bygger på:** D-008, D-009, D-042, D-043, DR-13, SR-10, SR-11
- **Gäller:** FR-20

## Problemet
De skriptade agenterna visar att spärrarna håller, men inte hur en riktig språkmodell beter sig i
arbetscykeln. Ollama kräver en dator som orkar köra en modell. Groqs gratisnivå finns redan i `providers.toml`.
Men DR-13 tillåter bara `public`-data till externa leverantörer, och agenternas förfrågningar var märkta `internal`.

## Förslag
1. **`python -m aie simulate start|resume --agents groq`** använder bara leverantörer av typen `groq` ur `providers.toml`, med nyckeln i `GROQ_API_KEY`.
   - Ingen annan leverantör används, inte ens `rule`.
   - Saknas nyckeln vägrar kommandot att starta och hänvisar till `docs/setup.md`.
2. **Bara simulerade data.** I läget `groq` märks förfrågan `public`. Det är tillåtet bara när miljön är `sim` och valutan är `SIM`, annars `SimulationError`. Allt i förfrågan kommer från scenariot och simuleringens egen databas. `LLMGateway` avvisar som förut en prompt som innehåller en hemlighet (SR-10).
3. **Kvoten:**
   - Före varje simulerad dag kontrolleras att dagens kvot räcker till dagens agentanrop: 2, eller 5 en dag med motstridiga bedömningar.
   - Räcker den inte pausas körningen före dagen, med `simulation.paused_quota` i revisionsloggen.
   - Inget halvt dygn sparas, och `simulate resume` fortsätter senare.
4. **Ingen betald reserv** (D-008, D-009). Kostnaden loggas som 0.
5. **Bedömningar** (`simulate evaluate`, `assess run`) körs inte med `groq`, eftersom en pausad körning ger en halv bedömning.
6. **Yorgo kör det själv** med sin gratisnyckel (Fas 0.10). Claude skapar inget konto och hanterar ingen nyckel.

## Att avgöra
- Om simulerade data får märkas `public` och skickas till Groq. Förslaget är ja, eftersom simuleringen inte innehåller några riktiga uppgifter.

## Kostnad och risk
- **Kostnad:** ingen. Gratisnivån och kvoterna i `providers.toml` ligger under Groqs gratisgränser.
- **Risk:**
  - Groq ser scenariot och simuleringens siffror. Därför märks läget tydligt och är spärrat utanför sim.
  - Modellens svar kan vara fel. De är hypoteser (§29) och passerar samma parser och spärrar som allt annat (D-043).

## Tester
`tests/unit/test_groq_agents.py` har 4 tester. Nätverket är mockat. Testerna visar att:
- förfrågningarna är `public`, bara går till Groq, kostar 0 och aldrig loggar nyckeln
- ingen reserv tar över, och kommandot inte startar utan nyckel
- körningen pausas när kvoten tar slut och fortsätter efteråt
- `public`-märkningen bara fungerar i sim, och bedömningar vägrar `groq`
