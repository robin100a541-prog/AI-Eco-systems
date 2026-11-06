# D-069 Autonomi för print-on-demand: vad agenterna får göra utan att fråga (förslag)

- **Status:** Föreslagen. **Kräver en grundares godkännande** (D-049). Tills dess är allt nedan avstängt i `config/pod.toml`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 04, punkt 6), 2026-11-04
- **Bygger på:** D-049, D-053, D-055, D-058, D-065–D-068, SR-07, SR-08, ER-03

## Förslag
När en grundare har godkänt beslutet får agenterna, **utan att fråga**:

| Åtgärd | Verktyg | Gräns | Villkor |
|---|---|---|---|
| Skapa utkast i Printify (opublicerade produkter, bilduppladdning) | `printify.draft` | ingen gräns per dag, men Printifys gräns gäller | motivet klarar `aie.pod.rules` |
| Publicera nya Etsy-annonser (via Printifys publicering till den kopplade butiken) | `etsy.publish`, ett nytt verktyg i en egen PR | **högst 5 nya per dag** (`max_new_listings_per_day`) | bara produkter som är **redo** enligt spärren (D-058) |
| Publicera marknadsföringsinlägg (pins och Instagram-inlägg) | `pinterest.pin`, `instagram.publish` | **högst 10 per dag totalt** (`max_pins_per_day` och `max_posts_per_day`); Instagram aldrig över 50 | länken går till vår egen Etsy-annons, och bilden är vårt eget motiv |
| Göra utgifter | budgetmotorn | **under `HUMAN_APPROVAL_THRESHOLD`** och inom budget | allt annat går till grundarna som förut (D-053) |

**Alltid:**
- **Loggen:** varje åtgärd loggas i revisionsloggen, och reserveras i `pod_actions` (migration 38) innan den skickas.
- **Daglig rapport:** den visar vad som publicerades, vad som stoppades och varför.
- **Spärrarna:** nödstoppet (SR-07), skyddat läge (SR-08) och stop-loss gäller för varje verktyg. Ett stopp stoppar alla externa anrop.
- **Kundmeddelanden på Etsy** finns inte i Etsys API. Systemet notifierar grundarna, i `QUESTIONS-FOR-FOUNDERS.md` och i den dagliga rapporten, och svarar aldrig själv.
- **Inga nya fasta kostnader:** Printify Premium, Etsy Plus och betalda annonser kräver egna beslut.

## Vad som ändras när beslutet är godkänt
1. I `config/pod.toml` sätts `draft_enabled = true`, och `enabled = true` för de tjänster vars konton är kopplade. Det görs i en egen PR.
2. Verktyget `etsy.publish` läggs till i `permissions.toml`. Filen är skyddad och kräver `founder-approved`.
3. Den dagliga cykeln börjar skapa utkast och publicera inom gränserna.

## Att avgöra
- Gränserna 5 annonser och 10 inlägg per dag.
- Om Offsite Ads ska tillåtas. Etsy kan kräva det för större butiker. Kalkylen räknar med en fjärdedel av ordren i det pessimistiska fallet.
- Om ett utkast får skapas innan spärren säger redo. Förslaget är ja: utkastet ger Printifys verkliga baspris (`cost`), som behövs för att spärren ska få riktiga siffror.

## Kostnad och risk
- **Kostnad:** 0 kr i fasta kostnader. Per såld vara tar Etsy och Printify sina avgifter, och de finns i kalkylen.
- **Risk:**
  - Felaktiga annonser kan ge reklamationer eller varningar från Etsy. Det motverkas av gränserna per dag, reglerna och spärren, och av att varje annons loggas.
  - Ett konto som stängs (D-059).
