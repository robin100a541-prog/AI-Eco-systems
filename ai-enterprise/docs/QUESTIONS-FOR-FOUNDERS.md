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

### Q-BOT-006 Utvecklaragenten behöver hjälp: BL-010
- **Datum:** 2026-11-01
- **Status:** Öppen
- **Uppgift:** BL-010
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):**


### Q-BOT-005 Utvecklaragenten behöver hjälp: BL-009
- **Datum:** 2026-11-01
- **Status:** Öppen
- **Uppgift:** BL-009
- **Fråga:** Hur ska uppgiften lösas, eller ska den strykas?
- **Varför det spelar roll:** Utvecklaragenten har misslyckats 3 gånger med uppgiften. Senast: apply_failed.
- **Alternativ:**
  1. Ge en ledtråd eller lös den själv.
  2. Stryk uppgiften.
- **Botens rekommendation:** alternativ 1 om uppgiften fortfarande behövs.
- **Svar (grundare, namn och datum):**


## Besvarade

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
## Scouten väntar på grundarna (2026-10-31)
- Etsy: ETSY_API_KEY saknas, källan hoppades över
- researchen misslyckades: scout-1: modellen gav inget användbart svar (IdeaError: svaret innehåller ingen JSON)
<!-- scout:end -->
