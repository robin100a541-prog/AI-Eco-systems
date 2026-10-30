# D-061 Nattlig körning i GitHub Actions (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 9), 2026-10-28
- **Bygger på:** D-016, D-048, D-050, D-060, SR-10, SR-11

## Problemet
Testerna körs bara när någon öppnar en PR. Ingen kontrollerar varje dag att systemet startar, att
revisionsloggen håller och att bedömningen av scenarierna inte har ändrats av en sammanslagning.

## Förslag
`.github/workflows/nightly.yml` körs varje natt klockan 02:41 UTC och med knappen "Run workflow". Den kör stegen i den här ordningen:
1. **Bara sim:** körningen stoppas om `config/` inte är miljön `sim` med valutan `SIM`.
2. **Tester:** hela sviten.
3. **Hälsokontroll:** `check-config`, `init` och `status`, som kontrollerar revisionskedjan.
4. **Bedömning** med skriptade agenter av scenarierna `normal` och `platform_ban` (`simulate evaluate`). Lokalt tar steget ungefär 1 minut.
5. **Groq, valfritt:** en kort simulering på 3 dagar med Groq-agenter (D-060).
   - Steget körs bara i huvudrepot, aldrig i en fork, och bara om repository secret `GROQ_API_KEY` finns. Utan hemlighet hoppas steget över.
   - Nyckeln finns bara i det steget och skrivs aldrig ut.
   - Steget får misslyckas utan att natten räknas som misslyckad, eftersom gratiskvoten kan vara slut.
6. **Sammanfattning och artefakt:** sammanfattningen visas i körningen. Utskrifterna, rapporterna och loggarna laddas upp som artefakt och sparas i 14 dagar.
7. **Vid fel:** ett ärende "Nattkörningen misslyckades" öppnas. Finns det redan ett öppet ärende får det en kommentar.

**Behörigheter:**
- Jobbet har bara `contents: read`.
- Bara felrapporten har `issues: write`.
- Inget pushas, ingen PR öppnas och inget publiceras.
- Inga riktiga pengar används.

## Att avgöra
- Om Groq-steget ska köras varje natt. Det använder 6 anrop av gratiskvoten. Knappen har ett val för att hoppa över det.

## Kostnad och risk
- **Kostnad:** ingen. GitHub Actions ingår i det publika repot, och Groq använder gratisnivån.
- **Risk:** ett ärende per misslyckad natt kan bli brus. Därför kommenterar körningen ett ärende som redan är öppet i stället för att öppna ett nytt.

## Tester
- **`tests/unit/test_nightly_workflow.py`:** 5 tester som läser arbetsflödet och kontrollerar att:
  - det inte körs på PR:er
  - bara felrapporten kan skriva
  - hemligheten bara finns i Groq-steget och aldrig används i en fork
  - kontrollen av sim kommer först och inget publiceras
  - fel ger ett ärende, och rapporterna laddas upp
- **`tests/unit/test_cycle.py`:** ett nytt test visar att en start med `--agents groq` utan nyckel inte lämnar någon körning efter sig. Felet hittades när steget provkördes lokalt.
