# Frågor till grundarna

Nattboten (`docs/BOT.md`) skriver hit allt den inte får avgöra själv: beslut, pengar, juridik,
konton, plattformar, skyddade filer och uppgifter som misslyckats tre gånger. Boten gissar aldrig.

**Så svarar ni:** skriv ert svar under *Svar* och sätt status till `Besvarad`. Boten läser filen i
början av varje körning och använder svaret. Nya frågor läggs överst under *Öppna*.

## Mall

```
### Q-BOT-NNN Kort rubrik
- **Datum:** ÅÅÅÅ-MM-DD
- **Status:** Öppen | Besvarad | Stängd
- **Uppgift:** vilken uppgift som väntar (ROADMAP-rad eller TODO-rad)
- **Fråga:** vad som behöver avgöras
- **Varför det spelar roll:** vad som blockeras och vad som händer om det blir fel
- **Alternativ:**
  1. ...
  2. ...
- **Botens rekommendation:** alternativ och skäl
- **Vad boten har provat** (bara vid tre misslyckanden): försök, fel och testutdata
- **Svar (grundare, namn och datum):**
```

## Öppna

### Q-BOT-013 Utvecklaragenten behöver hjälp: BL-017
- **Datum:** 2026-11-03
- **Status:** Öppen
- **Uppgift:** BL-017
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: check_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):**


## Besvarade

### Q-BOT-012 Utvecklaragenten behöver hjälp: ruff:RUF022:src/aie/agents/__init__.py:20
- **Datum:** 2026-11-03
- **Status:** Besvarad
- **Uppgift:** ruff:RUF022:src/aie/agents/__init__.py:20
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: check_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Struken. Ruff-varningar är inga uppgifter för utvecklaragenten längre (#158): picker hämtar dem inte, punkter med ruff-kontroll tas inte och arbetsflödet installerar inte ruff. Grundarna hade redan släppt två sådana som lågt värde (Q-BOT-003, -004), men varje nytt radnummer blev en ny uppgift. Yorgo, 2026-11-03.

### Q-BOT-011 Utvecklaragenten behöver hjälp: BL-014
- **Datum:** 2026-11-03
- **Status:** Besvarad
- **Uppgift:** BL-014
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: check_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Löst av Yorgo (#160). Punkten var fel: den bad om `details = {}` som standardvärde, och ett föränderligt standardvärde delas mellan alla anrop. Standardvärdet förblir `None`; docstringen för `AuditLog.append` beskriver nu `details`, och kontrollen är rättad. Yorgo, 2026-11-03.

### Q-BOT-010 Utvecklaragenten behöver hjälp: BL-015
- **Datum:** 2026-11-03
- **Status:** Besvarad
- **Uppgift:** BL-015
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Löst av Yorgo (#161). Kontrollen `grep … "head_hash" -A2` blandade in en grep-flagga i söktexten och kunde aldrig gå igenom. Docstringen för `Verification` förklarar nu `head_hash` och trunkering, och kontrollen är rättad. Yorgo, 2026-11-03.

### Q-BOT-009 Utvecklaragenten behöver hjälp: BL-013
- **Datum:** 2026-11-02
- **Status:** Besvarad
- **Uppgift:** BL-013
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Löst av Yorgo (#159). Kontrollen pekade på en funktion på modulnivå (`tests.unit.test_main.test_check_config_success`) som unittest inte kan köra. Testet ligger nu i `TestMain.test_check_config_function_returns_zero`, och kontrollen pekar dit. Yorgo, 2026-11-03.

### Q-BOT-008 Utvecklaragenten behöver hjälp: ruff:I001:src/aie/__main__.py:330
- **Datum:** 2026-11-01
- **Status:** Besvarad
- **Uppgift:** ruff:I001:src/aie/__main__.py:330
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: check_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Struken. Ruff-varningar är inga uppgifter för utvecklaragenten längre (#158), se Q-BOT-012. Yorgo, 2026-11-03.

### Q-BOT-007 Utvecklaragenten behöver hjälp: BL-011
- **Datum:** 2026-11-01
- **Status:** Besvarad
- **Uppgift:** BL-011
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Redan klart. `_check_config` slutar med `return 0`. Kontrollen `!grep … "return 0"` var omvänd och kunde aldrig gå igenom. BL-011 är markerad klar med en rättad kontroll. Yorgo, 2026-11-03.

### Q-BOT-006 Utvecklaragenten behöver hjälp: BL-010
- **Datum:** 2026-11-01
- **Status:** Besvarad
- **Uppgift:** BL-010
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Punkten är ersatt av BL-019, som agenten kan göra. Kontrollen pekade på `tests.unit.test_registry`, som testar plattformsregistret, och klassen `TestAgentRegistry` finns inte. Testet ska nu ligga i den nya filen `tests/unit/test_agent_registry.py`, klass `TestSetGuard`. Yorgo, 2026-11-03.

### Q-BOT-005 Utvecklaragenten behöver hjälp: BL-009
- **Datum:** 2026-11-01
- **Status:** Besvarad
- **Uppgift:** BL-009
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Punkten är ersatt av BL-018, som agenten kan göra. Den gamla bad bara om ett test för ett beteende som inte fanns: `set_guard` kontrollerar inte `guard` i dag. Punkten säger nu att kontrollen ska läggas till i `set_guard` och testas i `tests/unit/test_agent_registry.py`, klass `TestSetGuard`. Yorgo, 2026-11-03.

### Q-BOT-004 Utvecklaragenten behöver hjälp: ruff:RUF022:src/aie/agents/__init__.py:14
- **Datum:** 2026-10-29
- **Status:** Stängd — släppt, lågt värde
- **Uppgift:** ruff:RUF022:src/aie/agents/__init__.py:14
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: check_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Släppt, lågt värde. Robin, 2026-10-30.


### Q-BOT-003 Utvecklaragenten behöver hjälp: ruff:I001:src/aie/agents/__init__.py:2
- **Datum:** 2026-10-28
- **Status:** Stängd — släppt, lågt värde
- **Uppgift:** ruff:I001:src/aie/agents/__init__.py:2
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Släppt, lågt värde. Robin, 2026-10-30.


### Q-BOT-002 Utvecklaragenten behöver hjälp: BL-005
- **Datum:** 2026-10-28
- **Status:** Stängd — släppt, lågt värde
- **Uppgift:** BL-005
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Släppt, lågt värde. Robin, 2026-10-30.


### Q-BOT-001 Utvecklaragenten behöver hjälp: BL-002
- **Datum:** 2026-10-28
- **Status:** Stängd — släppt, lågt värde
- **Uppgift:** BL-002
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):** Släppt, lågt värde. Robin, 2026-10-30.

<!-- scout:start -->
## Scouten väntar på grundarna (2026-11-04)
- Etsy: ETSY_API_KEY saknas, källan hoppades över
- researchen misslyckades: produktagenten gav 9 giltiga idéer, minst 10 krävs
<!-- scout:end -->
