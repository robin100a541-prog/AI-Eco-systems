# TESTING: kommandocentralen

Den här filen beskriver hur kommandocentralen startas och prövas för hand. Den fylls på för varje steg, och D8 lägger till hela mobilchecklistan. De automatiska testerna körs med `py -m unittest discover -s tests` och finns i `tests/unit/test_dashboard_server.py` (D1) och `tests/unit/test_seed_sim.py` (D0b).

## Starta på Windows (Yorgo)

Allt körs i **PowerShell**. Ingenting installeras och ingenting kostar något.

### 1. Gå till mappen och hämta det senaste
```powershell
cd "$HOME\Desktop\Ai Eco-system\ai-enterprise"
git checkout main
git pull
$env:PYTHONPATH = "src"
```
`$env:PYTHONPATH = "src"` gäller bara det här terminalfönstret. Öppnar du ett nytt fönster kör du raden igen.

### 2. Sätt din åtkomstkod (en gång)
```powershell
py -m aie dashboard set-code --founder Yorgo
```
- **Koden:** skriv den två gånger, minst 8 tecken. Den syns inte när du skriver.
- **Var den sparas:** bara en hash sparas i `ai-enterprise\.env`. Filen kommer aldrig in i git.
- **Robin** gör samma sak med `--founder Robin` på sin dator.
- **Byta kod:** kör kommandot igen. Den gamla hashen ersätts.

### 3. Testdata (en gång, redan gjort på Yorgos dator 2026-11-08)
```powershell
py scripts\seed_sim.py
```
- **Väntat:** `Klar: data\sim.db (30 dagar i SIM, 3 väntande godkännanden, revisionslogg OK)`.
- **Om datamappen redan har en körning** stoppar skriptet. Det är avsiktligt. Vill du börja om tar du bort `data\sim.db` och kör igen.

### 4. Starta på datorn
```powershell
py -m aie dashboard
```
- **Öppna:** http://127.0.0.1:8765/ i webbläsaren och logga in som Yorgo med din kod.
- **Det här ska synas:**
  - Home med de 3 väntande godkännandena (40.00, 65.00 och 115.00 SIM)
  - etiketten **SIM**
  - en grön **Live**-punkt
  - klockan
  - knapparna Pause agents och Kill switch, gråa med texten "Available in D5"
- **Utan `--lan`** når bara datorn själv servern.
- **Stoppa:** tryck **Ctrl+C** i terminalen.

### 5. Öppna på mobilen (samma wifi)
```powershell
py -m aie dashboard --lan
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
| `No module named aie` | Du glömde `$env:PYTHONPATH = "src"`, eller står i fel mapp. |
| `No access code is set` | Kör steg 2. |
| `kunde inte starta på port 8765` | Porten är upptagen. Kör `py -m aie dashboard --port 8766` och öppna den porten. |
| Mobilen når inte sidan | Kontrollera att servern startades med `--lan`, att mobilen är på samma wifi, att nätverksprofilen är Privat och att brandväggen tillåter Python i privata nätverk. |
| "Offline" i rubrikraden | Servern svarar inte, så starta den igen. |
| Du loggas ut | Sessionen gäller i 12 timmar och försvinner när servern startas om. |

## Kontroll för hand (D1)
Gjort 2026-11-08 i appens inbyggda webbläsare, mot en tillfällig kopia med testdata och en genererad testkod:
- [x] **Fel kod:** "Wrong founder or access code." och HTTP 401.
- [x] **Rätt kod** ger Home med 3 väntande godkännanden, SIM, Live, klocka och inaktiva knappar.
- [x] **390 px:** menyn ligger överst och kan fällas ihop, och sidan rullar inte i sidled (`scrollWidth` 390 = `clientWidth` 390).
- [x] **Approvals** visar en tom vy med "This page is filled in step D4."
- [ ] **En riktig mobil** på samma wifi med `--lan`. Den kontrollen görs av Yorgo.
- [ ] **Rörelsen i en synlig webbläsare (D-084):** panelerna glider in lugnt, siffrorna räknas upp utan att gå över, mjuk scroll fungerar bara på datorn med mus, och med "Minska rörelse" påslaget i Windows (Inställningar, Hjälpmedel, Visuella effekter, Animeringseffekter av) står allt still. Den kontrollen görs av Yorgo.
