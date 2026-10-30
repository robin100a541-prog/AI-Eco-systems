# Checklista för grundarna: från bygge till första försäljning

Gör stegen i ordning. Varje steg säger exakt vad du gör. Inget i systemet flyttar pengar, skapar konton
eller publicerar något åt dig; det gör bara du.

Kommandona körs i en terminal i mappen `ai-enterprise/`. Skriv först `export PYTHONPATH=src` (Mac och Linux)
eller `set PYTHONPATH=src` (Windows).

## 1. Oberoende granskning (D-055), krävs före riktiga pengar
1. Öppna en **ny** Claude Code-session på repot (en ny chatt, inte den som byggde koden).
2. Klistra in prompten i `docs/reviews/REVIEW-PROMPT.md`.
3. Slå ihop PR:en med granskningen. Be sedan en byggsession rätta allt som är märkt `high` eller `critical`.

## 2. Skatteverket (Q-TAX-01)
1. **Klart (Robin 2026-10-30):** momsen sköts av plattformarna; inget företag behöver öppnas nu (Q-TAX-01 i DECISIONS.md).
   (Gumroad, som är merchant of record). Ska intäkten deklareras som enkelt bolag (NE-bilaga), och behöver vi
   registrera oss för moms?"
2. Skriv svaret, med datum och namn på handläggaren, under Q-TAX-01 i `DECISIONS.md` (via en PR med etiketten
   `founder-approved`).
3. Tills svaret finns reserverar systemet 50 % av intäkten som skatt (`untracked_rate` i `config/tax.toml`).

## 3. Välj produkt bland topp 3 (f-skatt-guide är STOPPAD, Robin 2026-10-30)

Läs `docs/reports/7a-opportunities.md` och välj en av de tre bästa tillsammans. Den gamla delen nedan gäller inte längre.

### (Gammalt) Granska produkten
1. Läs `products/f-skatt-guide/GRANSKNING.md` och rätta felen i `products/f-skatt-guide/product.md`.
2. Gör om PDF:en: `python -c "from pathlib import Path; from aie.pilot.writer import write_pdf; d=Path('products/f-skatt-guide'); write_pdf((d/'product.md').read_text(), d/'product.pdf')"`.
3. Öppna `product.pdf` och läs den. Ta bort raden "INTE KLAR ATT LISTA" i `GRANSKNING.md`. Gör en PR.

## 4. Skapa Gumroad-kontot (en grundare, i eget namn)
1. Gå till gumroad.com och skapa ett konto med din e-post. Verifiera kontot och lägg in utbetalningsuppgifter.
2. Läs Gumroads villkor och reglerna om AI-innehåll. Godkänn bara om de tillåter produkten.
3. Sätt undan **500 kr** som pilotens kapital. Mer får inte användas (START_CAPITAL).

## 5. Förbered och godkänn piloten i systemet
1. `python -m aie pilot prepare --as robin --product products/f-skatt-guide`
   Läs listningen, priset, budgettaket, stop-loss och stoppkriterierna. Kommandot skriver ut ett nummer i
   godkännandekön, till exempel `#1`.
2. `python -m aie pilot approve 1 --as robin` (använd numret från steg 1).
3. `python -m aie pilot status --product products/f-skatt-guide` ska visa "Godkänd".

## 6. Lista produkten för hand
1. I Gumroad: New product, sedan Digital product.
2. Kopiera titel, pris (12 USD), beskrivning, taggar och **upplysningen om AI-användning** från
   `products/f-skatt-guide/listing.md`. Ladda upp `product.pdf`.
3. Publicera. Skriv datumet i `products/f-skatt-guide/GRANSKNING.md`.

## 7. Slå på instrumentpanelen (GitHub Pages)
1. På GitHub: repot, Settings, Pages. Under "Build and deployment" väljer du Source "GitHub Actions".
2. Kör workflowen `company-daily` en gång (Actions, company-daily, Run workflow).
3. Panelen finns sedan på https://robin100a541-prog.github.io/AI-Eco-systems/

## 8. Importera försäljningen varje vecka
1. I Gumroad: Analytics, Sales, Export. Spara CSV-filen, till exempel `sales-v45.csv`.
2. Läs av växelkursen USD till SEK för veckan (Riksbanken) och nettot som Gumroad visar.
3. `python -m aie results import sales-v45.csv --format sales --as robin --product products/f-skatt-guide --usd-sek 10.5 --platform-net 20.60`
4. Visar kommandot **AVSTÄMNING STÄMMER INTE**, är en incident öppnad. Jämför filen med Gumroad innan du går vidare.
5. Visar kommandot **STOPP**, avpublicera produkten i Gumroad. Nya utgifter är då spärrade (skyddat läge).
   Bara en grundare kan häva det.

## 9. Varje dag (automatiskt)
- `company-daily` kör en företagscykel varje natt och skriver rapporter i `docs/reports/`.
- När något väntar på dig står det överst i `docs/QUESTIONS-FOR-FOUNDERS.md`.
- Nödstopp: lägg en fil `docs/KILL-SWITCH` med en rad om varför. Ta bort filen för att släppa stoppet.

## 10. Fas 8 (senare)
När piloten har fler intäktskällor: ändra `MIN_ACTIVE_PLATFORMS` till 2 och `MAX_PLATFORM_REVENUE_SHARE`
till 60 i `config/risk_limits.toml` (D-059, en PR med `founder-approved`).

## Säkerhetskopiering (teknisk del, kan köras av kodagenten)

När pilotens databas finns, kör från `ai-enterprise/`:

```bash
PYTHONPATH=src python3 -m aie.memory.backup create data-pilot/data/prod.db --out data-pilot/backups
PYTHONPATH=src python3 -m aie.memory.backup verify data-pilot/backups/<filnamnet-från-första-kommandot>.db
```

Första kommandot tar en konsistent SQLite-backup inklusive WAL och provar återställning i en separat temporär mapp. Manifestet (`.json`) innehåller kontrollsumma, schema, miljö, tabellantal och revisionskedjans slut. Det andra kommandot provar samma backup igen utan att skriva över driftdata. Båda måste lyckas. Saknad databas ger fel, aldrig en tom "backup".

Behåll både `.db` och `.json` privat. Kopiera dem till en separat, privat lagringsplats utanför datorn efter varje försäljningsimport och före databasuppgraderingar. `data-pilot/` är gitignorerad; ladda aldrig upp dessa filer till det publika repot eller publika Actions-artefakter. En annan privat plats och backupintervallet måste fortfarande väljas av grundaren. Lokal backup skyddar inte mot att hela datorn försvinner.

Vid skarp återställning: stoppa alla skrivande processer, verifiera backupen, återställ till en **ny** datamapp och kontrollera rapporter/godkännanden innan konfigurationen pekas om. Skriv inte över originaldatabasen. Backupverktyget gör bara övningen och kan inte skriva över driftdata. Manifest och databas tillsammans är ingen kryptografisk signatur mot en angripare som kan ersätta båda.

## Testa automatiken utan att publicera

En kodagent kan köra `python scripts/verify_daily_cycle.py` från `ai-enterprise/`. Det startar två separata CLI-processer i en tillfällig SIM-miljö utan att ärva API-nycklar eller GitHub-token. Kontrollen verifierar att dag två återupptar dag ett, att båda rapporterna finns, att revisionskedjan är hel och att instrumentpanelen bara innehåller offentliga SIM-data. Det här är ett test, inte en skarp företagskörning.

GitHub Actions → company-daily → Run workflow har nu `verify_only` påslaget som standard för manuella starter. Testjobbet har inga hemligheter och använder varken företagets cache, rapport-PR eller Pages. Avmarkera bara `verify_only` när du avsiktligt vill köra den vanliga företags-/publiceringsvägen. Schemalagda körningar använder fortfarande den vanliga vägen.
