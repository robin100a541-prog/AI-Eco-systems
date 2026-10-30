# Setup — kom igång (Fas 0)

## 0. Var grundarna utvecklar
- **Robin** utvecklar via Claude Code i molnet (Claude-appen). Molnmiljön är Robins utvecklingsmiljö; ingen lokal installation behövs.
- **Yorgo** utvecklar lokalt på Windows.
- **Båda** måste få `REDO för Fas 1` från `check_env.py` och `OK` från testerna i sin miljö. Rapporten läggs i `docs/environment.md`.

## 1. Installera grunderna (gratis)
- **Python 3.11 eller nyare:** https://www.python.org/downloads/ (Windows: kryssa i "Add python.exe to PATH").
- **Git:** https://git-scm.com/downloads
- **GitHub-konto** (gratis): https://github.com

## 2. Kör miljökontrollen
Packa upp projektet, öppna en terminal i mappen `ai-enterprise` och kör:

```bash
# macOS / Linux
python3 scripts/check_env.py --founder Yorgo
python3 -m unittest discover -s tests -v

# Windows (PowerShell)
py -3 scripts\check_env.py --founder Robin
py -m unittest discover -s tests -v
```

**Windows: skriv `py -3` före ett skript.** Utan versionsflagga läser `py` skriptets första rad (`#!/usr/bin/env python3`) och letar efter `python3` i PATH. Där ligger ofta Microsoft Stores genväg, som bara svarar "Python was not found" (kod 9009). `py -3` hoppar över den raden. För `py -m ...` spelar det ingen roll.

**Förväntat:** rapporten slutar med `Resultat: REDO för Fas 1`, och testerna slutar med `OK`.
Kopiera hela rapporten (från `## Miljö:` till `Resultat:`) in i `docs/environment.md` under ditt namn.

Skriptet läser bara information. Det installerar eller skickar ingenting.

## 2b. Testa en gratis språkmodell
1. Skapa ett gratis konto på https://console.groq.com och skapa en API-nyckel. Lägg **inte** in något betalkort.
2. Kör:
```bash
# macOS / Linux
export GROQ_API_KEY="din-nyckel"
python3 scripts/llm_smoke_test.py --provider groq

# Windows (PowerShell)
$env:GROQ_API_KEY="din-nyckel"
py -3 scripts\llm_smoke_test.py --provider groq
```
**Förväntat:** JSON med `"answer"` (t.ex. "Blå") och `quota_headers` som visar era gränser, sedan `OK — modellen svarade.` Klistra in resultatet i `docs/environment.md`, men **aldrig** nyckeln.

Valfritt: OpenRouter (`--provider openrouter --model <id>:free`) och Ollama (installera från ollama.com, hämta en modell, `--provider ollama --model <namn>`).

Nycklar sparas aldrig i projektmappen eller i git. Senare läses de från en `.env`-fil som är gitignorerad.

## 2c. Köra paketet `aie` utan installation (Fas 1)
Koden ligger i `src/aie/` och installeras inte. Det finns två sätt att nå den, och båda fungerar likadant på Windows, macOS och Linux.

**Tester.** `tests/unit/__init__.py` lägger till `src/` i `sys.path` när testerna startar. Du behöver inte göra något, bara stå i repots rot:
```bash
python3 -m unittest discover -s tests -v      # macOS / Linux
py -m unittest discover -s tests -v           # Windows
```

**Kommandoraden.** Sätt `PYTHONPATH` till `src` och stå i repots rot, eftersom `config/` söks relativt den mapp du står i:
```bash
# macOS / Linux
PYTHONPATH=src python3 -m aie check-config

# Windows (PowerShell), gäller resten av terminalfönstret
$env:PYTHONPATH = "src"
py -m aie check-config

# Windows (cmd)
set PYTHONPATH=src
py -m aie check-config
```
**Förväntat:** `Konfiguration OK (...)` och kod 0. Vid fel listas **alla** fel och koden blir 1. Med `--config-dir <mapp>` kan du kontrollera en annan konfigurationsmapp.

Varför inte `pip install -e .`? Det kräver ett byggverktyg (setuptools) som pip laddar ner. D-002 tillåter inga beroenden, så paketet körs direkt från källkoden.

## 2d. Starta och stoppa systemet (Fas 1.6)
Stå i `ai-enterprise/` med `PYTHONPATH=src` satt (se 2c). Databasen hamnar i `data_dir` och loggen i `log_dir` från `config/system.toml`, relativt mappen du står i.

```bash
python3 -m aie init      # skapar eller uppgraderar databasen
python3 -m aie start     # kör tills det ombeds stanna; Ctrl+C stänger ned rent
python3 -m aie status    # i ett annat fönster: driftläge och kontroll av revisionsloggen
python3 -m aie stop      # i ett annat fönster: ber systemet stanna och väntar (högst 30 s)
```

**Kod 0** betyder att kommandot lyckades. **Kod 1** betyder ett fel som är utskrivet och loggat:
- ogiltig konfiguration
- en `log_dir` eller `data_dir` som inte kan skapas
- en manipulerad revisionslogg (då vägrar `start`, och `status` ger kod 1)
- systemet är redan igång
- `stop` gav upp efter väntetiden

Om förra körningen dog utan att stänga ned (strömavbrott, dödad process) märker `start` det, loggar det och startar ändå.

## 2e. Grundarnas godkännandekö (Fas 3)
Det som ligger utanför en agents mandat eller över `HUMAN_APPROVAL_THRESHOLD` väntar på grundarna. `--as` måste vara ett namn i `founders` i `config/system.toml`.

```bash
python3 -m aie approvals list                                      # det som väntar
python3 -m aie approvals approve 3 --as robin --note "OK"          # en röst; över gränsen krävs båda
python3 -m aie approvals reject 3 --as yorgo --note "För hög risk" # ett nej avslår; motivering krävs
```

Kod 0 betyder att det lyckades. Kod 1 betyder ett fel, till exempel att du inte är grundare, redan har röstat eller försöker godkänna något över en hård gräns. Allt hamnar i revisionsloggen.

## 2f. Manuella svar från Claude (Fas 3, D-022)
Slå på `manual` i `config/providers.toml` genom att ta bort `#` framför blocket. När en agent behöver ett svar läggs förfrågan i `<data_dir>/manual/<miljö>/`.

```bash
python3 -m aie manual list                                       # väntande förfrågningar
python3 -m aie manual show 3f2a9c0d1b4e5a67                       # texten att köra i Claude
python3 -m aie manual answer 3f2a9c0d1b4e5a67 --as robin --file svar.txt
```

Bara data som är klassad `public` hamnar här. Klistra aldrig in nycklar eller lösenord i svaret; det avvisas.

## 2g. Simulera med Groq-agenter (arbetsorder 02, PR 8, D-060)
Agenterna i simuleringen kan svara med Groqs gratismodell i stället för de skriptade svaren. **Yorgo kör detta själv med sin egen gratisnyckel (Fas 0.10).** Claude skapar inget konto, godkänner inga villkor och hanterar inte nyckeln.

1. Skapa en nyckel enligt 2b. Lägg inte in något betalkort.
2. Sätt nyckeln bara i terminalfönstret. Skriv den aldrig i en fil i projektet, och klistra aldrig in den i en chatt eller ett ärende.
3. Kör en simulering i en egen datamapp:
```bash
# macOS / Linux
export GROQ_API_KEY="din-nyckel"
python3 -m aie simulate start --scenario normal --as yorgo --days 5 --agents groq

# Windows (PowerShell)
$env:GROQ_API_KEY="din-nyckel"
py -3 -m aie simulate start --scenario normal --as yorgo --days 5 --agents groq
```

**Vad som skickas till Groq:** bara simulerade uppgifter, alltså scenariot, SIM-belopp och agentens roll. Förfrågan märks `public`, och det är bara tillåtet i miljön `sim` med valutan `SIM`. Riktiga uppgifter finns inte i en simulering, och i prod kan läget inte startas.

**Kvoten:**
- Gränserna står i `config/providers.toml`. De ligger under Groqs gratisgränser.
- Räcker dagens kvot inte till en hel simulerad dag, pausas körningen före dagen med `PAUSAD: kvoten ...`. Inget halvt dygn sparas.
- Fortsätt efter nästa UTC-dygn:
```bash
python3 -m aie simulate resume --agents groq
```

**Inget byts tyst:**
- Bara leverantörer av typen `groq` används. `rule`, `openrouter` och betalda API:er tar aldrig över.
- Saknas `GROQ_API_KEY` vägrar kommandot att starta.
- Kostnaden loggas som 0 i revisionsloggen (`llm.call`).

**Bedömningar** (`simulate evaluate`, `assess run`) körs bara med `scripted` eller `local`. En körning som pausas halvvägs skulle ge en halv bedömning.

**Förväntat:** en rad per dag med order, åtgärder och nekade åtgärder. Svarar modellen med något som inte är giltig JSON nekas åtgärden och noteras (D-043). Det är ett väntat utfall och inget fel i systemet.

## 2h. Importera utfall från verkligheten (arbetsorder 02, PR 10, D-062)
När ni har sålt något på riktigt, till exempel efter ett manuellt försök med en produkt i `products/`, förs siffrorna in här. Utgå från mallen `docs/templates/utfall.csv`. Den har bara rubrikraden, så att inga exempelsiffror kan importeras av misstag. Skriv en rad per dag och initiativ.

| Kolumn | Innehåll |
|---|---|
| `day` | ÅÅÅÅ-MM-DD, aldrig i framtiden |
| `initiative` | en nyckel som finns i registret |
| `visitors`, `orders` | antal |
| `revenue_minor`, `refunds_minor`, `fees_minor`, `costs_minor` | heltal i öre eller cent |
| `currency` | SEK eller USD |
| `source` | **krävs**: en länk till plattformens rapport, ett kvitto eller en fil som visar siffrorna |
| `note` | fritt |

```bash
python3 -m aie results import utfall.csv --as yorgo
python3 -m aie results list
python3 -m aie results report mallar        # prognos (simulerat) mot utfall (verifierat i verkligheten)
```

**Om filen innehåller ett fel:** hela filen avvisas, och felen listas per rad.

**Om du importerar samma rad igen:** den sparas inte en gång till.

**Utfall ändras aldrig.** En rättelse är en ny rad med en egen källa.

**Om initiativet har minst 7 dagar med utfall:** de uppmätta värdena ersätter antagandena i `assess run`. Det gäller besökare, konvertering, återbetalningar och avgiften när plattformens avgift är okänd. Varje sådant värde märks "verifierat i verkligheten".

## 3. Skapa det gemensamma repot (en av er)
```bash
cd ai-enterprise
git init -b main
git add .
git commit -m "Fas 0: krav, arkitektur, beslut, miljökontroll"
```
Skapa sedan ett **privat** repo `ai-enterprise` på github.com (utan README), och följ GitHubs instruktion "push an existing repository". Gå till *Settings → Collaborators* och bjud in den andra grundaren.

## 4. Arbetsflöde (förslag D-004)
```bash
git pull                                  # alltid först
git switch -c fas1-config                 # ny gren per uppgift
# ... arbeta, kör testerna ...
git commit -am "Beskrivning"
git push -u origin fas1-config            # öppna sedan en Pull Request på GitHub
```
Den andra grundaren granskar och mergar. Uppdatera PROJECT_STATUS.md och CHANGELOG.md i samma PR.

## Viktigt om Claude-kostnader
Sätt **inte** miljövariabeln `ANTHROPIC_API_KEY`. Om den är satt använder Claude Code betald API-fakturering i stället för ert Pro-abonnemang. `check_env.py` varnar för detta.

## Säker pilotimport efter granskningsfynden H1–H3

En export med återbetalning måste ha `Refund Date` (eller `refund_date`/`refunded_at`) med det verkliga återbetalningsdatumet. Datum får inte gissas från importdagen. Försäljningen och återbetalningen kan höra till olika perioder. Samma export kan importeras igen; en senare retur skapar en separat post. Motstridiga rader, ändrade belopp och en gammal export som utelämnar en redan bokförd retur avvisas.

Migration 34 körs när databasen öppnas. Den skriver inte om äldre ledgerposter. Sådana poster saknar ofta verkligt händelsedatum och rapporteras fortsatt på registreringsdatum tills en granskad, spårbar rättelse gjorts. Importen stoppar vid en sådan äldre post i stället för att anta att perioden stämmer. Säkerhetskopiera databasen före uppgradering.
