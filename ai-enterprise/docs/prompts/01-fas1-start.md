# Instruktion 01 — starta Fas 1 i Claude Code

Klistra in allt under strecket i Claude Code, startat i projektmappen `ai-enterprise`.

---

Du arbetar i repot `ai-enterprise`, ett AI-företagssystem som byggs av Yorgo och Robin. Du har ingen tidigare kontext utöver filerna i repot.

## Läs först (i denna ordning)
1. `PROJECT_STATUS.md`
2. `CONSTITUTION.md` — styrande. Läs särskilt §35, §42–47 och §60.
3. `DECISIONS.md`, `ARCHITECTURE.md`, `REQUIREMENTS.md`, `ROADMAP.md`

## Fasta regler
- Python ≥ 3.11 och **endast standardbiblioteket** (D-002). Lägg inte till något beroende, inte heller pytest. Tester skrivs med `unittest`.
- Inga betaltjänster, inga API-anrop, inga nätverksanrop alls i denna uppgift.
- Om miljövariabeln `ANTHROPIC_API_KEY` är satt: **stoppa** och säg till. Den skulle göra att den här sessionen debiteras med API-pris i stället för Pro-abonnemanget.
- Påstå aldrig att något är testat om du inte har kört testet och sett resultatet. Klistra in den faktiska testutskriften i din slutrapport.
- Ändra aldrig `CONSTITUTION.md`. Ändra inte befintliga beslut i `DECISIONS.md`; lägg till nya om det behövs.
- Arbeta på en ny gren, aldrig direkt på `main`.

## Steg 0 — kontrollera läget
1. Kör `git status` och `git log --oneline`. Om arbetskatalogen inte är ren: stoppa och fråga.
2. Kör `python3 scripts/check_env.py --founder Yorgo` (Windows: `py` i stället för `python3`). Om resultatet är "INTE REDO": stoppa och förklara vad som behöver installeras.
3. Kör `python3 -m unittest discover -s tests -v`. Alla 18 befintliga tester ska vara gröna. Om inte: stoppa och rapportera.
4. Klistra in rapporten från `check_env.py` under Yorgos rubrik i `docs/environment.md`.
5. Skapa grenen `fas1-grund`.

## Uppgift — Fas 1, punkt 1.1 och 1.2 (inget mer)

**Mål:** ett körbart Python-paket som läser och validerar konfiguration, och vägrar starta vid ogiltig konfiguration (krav FR-02, DR-08, SR-10).

**1.1 Paketstruktur**
- `pyproject.toml` (paketnamn `aie`, `requires-python = ">=3.11"`, inga beroenden).
- `src/aie/__init__.py` med `__version__ = "0.1.0"`.
- `src/aie/__main__.py` med ett `argparse`-CLI som har kommandot `check-config`. Andra kommandon (`init`, `start` m.fl.) byggs senare.
- Tester ska kunna köras med `python3 -m unittest discover -s tests -v` från repots rot. Lös importvägen till `src/` på ett sätt som fungerar på Windows, macOS och Linux utan installation, och dokumentera hur i `docs/setup.md`.

**1.2 Konfiguration**
- `config/system.toml`: `environment` (`"sim"` eller `"prod"`), `data_dir`, `log_dir`, `base_currency`, `config_version`.
- `config/risk_limits.toml`: alla tio parametrarna i konstitutionens §25 samt `API_REINVEST_SHARE` och `API_MONTHLY_CAP` (D-009). Belopp anges som heltal i minsta enhet (öre/cent) tillsammans med valuta (D-006). I `sim` används valutan `SIM`.
- `src/aie/config/` med en laddare som returnerar oföränderliga (frozen) dataklasser och samlar **alla** valideringsfel i ett tydligt felmeddelande, inte bara det första.
- Valideringsregler som minst ska finnas:
  - okänd eller saknad `environment` ⇒ fel
  - `environment = "prod"` med valutan `SIM` ⇒ fel (ER-15)
  - `environment = "sim"` med en verklig valuta ⇒ fel
  - negativa belopp eller procentsatser utanför 0–100 ⇒ fel
  - `MINIMUM_RESERVE` > `START_CAPITAL` ⇒ fel
  - en §25-parameter som saknas ⇒ i `sim` en varning; i `prod` ett fel (ER-02: saknad gräns betyder blockera, aldrig "obegränsat")
  - okända nycklar ⇒ fel (skyddar mot stavfel som tyst stänger av en gräns)
  - hemligheter (`*_KEY`, `*_TOKEN`, `*_SECRET`, `password`) får inte finnas i `config/`; nycklar läses senare från miljövariabler (SR-10)
- `python3 -m aie check-config` skriver "Konfiguration OK" och avslutar med kod 0, eller listar felen och avslutar med kod 1.

**Tester** (`tests/unit/test_config.py`): minst ett test per valideringsregel, ett test som visar att giltig standardkonfiguration laddas, och ett test som visar att CLI:t ger kod 1 vid fel. Varje test har en docstring som säger vilket krav-ID det verifierar.

## Godkännandekriterier
- [ ] Alla tester gröna, gamla och nya. Den faktiska utskriften finns i slutrapporten.
- [ ] `python3 -m aie check-config` ger kod 0 med standardkonfigurationen.
- [ ] En medvetet trasig konfiguration ger kod 1 och listar alla fel.
- [ ] Inga tredjepartsimporter (kontrollera med `grep -rn "^import\|^from" src/`).

## Dokumentation (samma gren)
- `CHANGELOG.md`: ny version 0.1.0 med vad som lagts till.
- `PROJECT_STATUS.md`: aktuell fas, vad som är verifierat och nästa steg (1.3 loggning).
- `ROADMAP.md`: markera 1.1 och 1.2 som klara först när kriterierna är uppfyllda.
- `docs/conversations/ÅÅÅÅ-MM-DD-yorgo-fas1-config.md`: en sammanfattning av sessionen enligt `docs/conversations/README.md`.

## Avslut
1. Committa med ett beskrivande meddelande på grenen `fas1-grund`.
2. Om en GitHub-remote finns: pusha grenen och skapa en pull request mot `main`. Mergea **inte** själv; Robin eller Yorgo granskar.
3. Avsluta med en kort rapport: vad som gjordes, testutskriften, eventuella avvikelser från denna instruktion och varför, samt öppna frågor.
4. Stanna där. Börja inte på 1.3.
