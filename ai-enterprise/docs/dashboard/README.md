# Ekobyn — verklig arbetsstatus utan extra AI-anrop

Från `ai-enterprise/`, visa sidan lokalt:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/dashboard
```

Öppna http://127.0.0.1:8765/. Nästa arbetskörning kan skriva status till samma katalog:

```sh
# Befintlig simulering, en dag, inga nätverks-/modellanrop med scripted:
PYTHONPATH=src python3 -m aie simulate resume --days 1 --agents scripted --dashboard docs/dashboard/status.json

# För en ny, tom SIM-datamapp: simulate start --scenario normal --as robin ...
# Den vanliga daily-cycle har redan --dashboard och rapporterar automatiskt under arbetet.
# Riktig produktresearch kan också observeras, med samma befintliga kvoter:
PYTHONPATH=src python3 -m aie pilot discover --as robin --agents groq --dashboard docs/dashboard/status.json
```

Det sista kommandot använder modell och webb som den vanliga researchen och ska bara köras när research faktiskt önskas. Instrumenteringen skickar inga extra modellfrågor och ändrar inte anrop, kvoter, kostnadstak eller körfrekvens. Sidan startar inga arbetscykler. En snabb skriptad cykel kan vara klar innan sidan hinner läsa mellanlägen; arbetet fördröjs inte för animationen.

**Gör nu** kommer från kodens pågående steg: läser en offentlig källa, anropar modellen, kontrollerar åtgärder, klar eller blockerad. Bara fasta offentliga etiketter exporteras, aldrig prompter, modellsvar, uppgiftstitlar, affärsunderlag eller felens fritext. **Borde göra** är uttryckligen en rollplan, inte bevis på en tilldelad uppgift. **Senaste rapport** är historisk information, inte en liveindikator.

Under ett verkligt bedömningsmöte i simulationscykeln skickas dess deltagar-ID:n. Bara dessa agenter går till torget. Ett öppet tvistärende räknas inte automatiskt som ett pågående möte. Grafiska rörelser visar arbetsläget, inte fysiska positioner.

Status hämtas varannan sekund under arbete, annars var femte sekund (15 sekunder i en dold flik). En cachad JSON-snapshot får ett livstecken varannan sekund utan SQLite-läsning eller AI-anrop från heartbeat-tråden. Efter tio sekunder utan färskt livstecken försvinner liveindikeringen och rörelserna stoppas. Avslut, fel och kvotpaus visas separat. Nödstopp och skyddat läge fryser rörelserna. Systeminställningen för minskad rörelse pausar animationen från början.

Skrivningar ersätter JSON-filen atomärt. Ett OS-fillås tillåter bara en live-skrivare per målfil; på plattformar utan `fcntl` avstår livevisningen. Telemetrifel får inte ändra affärsarbetets utfall eller skapa modellåterförsök. Den sparade exempelstatusen behåller sitt ursprungliga datadatum när schemafält för rollplaner läggs till.

**GitHub Pages är statiskt.** Där visas den senaste publicerade statusen, inte en pågående Actions-körning. Live kräver att arbetsprocessen skriver till samma statusfil som den lokala webbservern läser. Ingen extern server, publicering, modellkostnad eller ständig arbetsloop aktiveras här.

Kontroller:

```sh
node --test tests/dashboard_world.cjs
PYTHONPATH=src python3 -m unittest tests.unit.test_dashboard tests.unit.test_dashboard_live -q
```
