# TESTING: kommandocentralen

Den här filen beskriver hur kommandocentralen startas och prövas för hand. Den fylls på för varje steg, och D8 lägger till hela mobilchecklistan. De automatiska testerna står i tabellen längst ned.

## Starta på Windows (Yorgo): ett kommando
Dubbelklicka på `ai-enterprise\dashboard.cmd` i Utforskaren, eller kör den från valfri terminal:
```
"%USERPROFILE%\Desktop\Ai Eco-systemi-enterprise\dashboard.cmd"
```
**Vad skriptet gör av sig självt:**
1. **Python:** går till rätt mapp, sätter `PYTHONPATH` och hittar Python (`py -3` eller `python`).
2. **Åtkomstkoden:** finns ingen frågar det vem du är, och du skriver koden två gånger. Bara en hash sparas, i `ai-enterprise\.env`.
3. **Testdata:** saknas lokal SIM-data skapas testdata med `scripts\seed_sim.py`.
4. **Start:** startar servern och öppnar webbläsaren på http://127.0.0.1:8765/. Är porten upptagen används nästa lediga, och adressen skrivs ut.
5. **Fel:** stannar med "Press any key" vid fel, så att du hinner läsa felet.

**Varför D1 inte startade hos Yorgo (diagnos 2026-11-09):**
- **Ingen kod sattes:** `ai-enterprise\.env` fanns inte, och revisionsloggen hade ingen `dashboard.login`. Yorgo kom alltså aldrig förbi att sätta koden.
- **Fel skal:** instruktionen satte `PYTHONPATH` med PowerShell-syntax (`$env:PYTHONPATH = "src"`) i ett kodblock märkt som bash. Kört i Git Bash misslyckas raden, och då ger `py -m aie` felet "No module named aie".
- **Andra hinder:**
  - Fönstret stängdes vid fel.
  - På Windows kunde två servrar dessutom dela port 8765 (SO_REUSEADDR). Nu binds porten exklusivt, och en upptagen port leder till nästa.

### Öppna på mobilen (samma wifi)
```
"%USERPROFILE%\Desktop\Ai Eco-system\ai-enterprise\dashboard.cmd" --lan
```
1. **Adressen:** terminalen skriver ut raden `On your phone (same Wi-Fi): http://192.168.x.x:8765/`.
2. **Brandväggen:** första gången frågar Windows brandvägg om Python får ta emot anslutningar. Kryssa bara i **Privata nätverk**, aldrig Offentliga, och välj Tillåt.
3. **Nätverksprofilen:** wifi-nätverket måste vara märkt som privat i Windows: Inställningar, Nätverk och internet, Wi-Fi, ditt nätverk, Nätverksprofil **Privat**.
4. **På mobilen:** öppna adressen på mobilen, som ska vara på samma wifi, och logga in.

**Säkerhet:**
- **Okrypterat:** trafiken går över http utan kryptering. Använd `--lan` bara på ditt eget hemnätverk, aldrig på ett öppet eller offentligt wifi.
- **Avsluta:** stoppa servern med Ctrl+C när du är klar.
- **Spärr:** fem felaktiga inloggningar från samma adress ger en minuts spärr.

### Felsökning
| Det som syns | Gör så här |
|---|---|
| `No module named aie` | Starta med `dashboard.cmd`, som sätter `PYTHONPATH` själv. |
| `No access code is set` | Starta `dashboard.cmd` igen. Den frågar efter koden. |
| `portarna 8765–8774 är upptagna` | Stäng andra fönster med Command Center, eller starta om datorn. |
| Mobilen når inte sidan | Kontrollera att servern startades med `--lan`, att mobilen är på samma wifi, att nätverksprofilen är Privat och att brandväggen tillåter Python i privata nätverk. |
| "Offline" i rubrikraden | Servern svarar inte, så starta den igen. |
| Du loggas ut | Sessionen gäller i 12 timmar och försvinner när servern startas om. |

## Kontroll för hand (Command Center, 2026-11-09)
Gjort i appens inbyggda webbläsare, mot den lokala servern med en tillfällig kopia av testdata och en genererad testkod:
- [x] **1440 px:** alla tio sidor visades med data.
- [x] **390 px:** `scrollWidth` 390 = `clientWidth` 390 på alla tio sidor, och den utfällbara menyn fungerar.
- [x] **Inga fel:** inga konsolfel och inga CSP-fel.
- [ ] **En riktig mobil.** Den kontrollen görs av Yorgo och Robin.
- [ ] **Den driftsatta sidan** på Cloudflare, efter `docs/command-center/DEPLOY.md`: inloggning med åtkomstkod, att fel kod nekas och att fem fel låser i 15 minuter, att en knapp ger en post i kön och att `py scripts\check_deploy.py <adress>` går igenom.
- [ ] **Chatten** mot Groq och **notiserna** (ntfy och Gmail). De kräver grundarnas nycklar.

## Automatiska tester
| Vad | Kommando |
|---|---|
| Allt i Python | `py -m unittest discover -s tests` |
| Snapshot, kö, notiser, lokal server och driftsättning | `py -m unittest tests.unit.test_snapshot tests.unit.test_control tests.unit.test_notify tests.unit.test_dashboard_server tests.unit.test_deploy` |
| Funktionerna och gränssnittets komponenter (körs i CI, kräver Node 22) | `node --experimental-default-type=module --test "tests/*.test.mjs"` i `command-center/` |
| Hela dygnskedjan i en tom mapp | `py scripts\verify_daily_cycle.py` |
