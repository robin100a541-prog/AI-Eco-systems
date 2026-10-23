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
