# Drift: nödstopp, stop-loss och återstart

Det här är den dokumenterade processen som konstitutionen §26 och §38 kräver. Koden upprätthåller varje steg som är markerat **(kod)**. Övriga steg görs av er grundare.

Alla kommandon körs från `ai-enterprise/` med `PYTHONPATH=src` satt (se `docs/setup.md`).

## Nödstopp (SR-07, §38, D-030)

### Aktivera
```bash
python -m aie kill engage --as yorgo --reason "kort beskrivning av vad som hänt"
```
- **Vem:** en grundare, en aktiv kontrollfunktion (CFO, CRO, Compliance, Audit) eller systemkomponenten `system:protected-mode` **(kod)**.
- **Verkan direkt:**
  - Inga nya utgifter **(kod)**.
  - Inga modellanrop, ingen webbsökning och inga nya eller tilldelade uppgifter **(kod)**.
  - Rapporter, ledgerläsning, revisionskontroll, riskbedömning och stopp fungerar fortfarande, så att läget kan utredas **(kod)**.
  - Ingenting raderas **(kod)**.

### Utreda
1. `python -m aie status` visar driftläge och om revisionsloggen är intakt.
2. `python -m aie kill status` visar vem som aktiverade, varför och vilka som redan har röstat för återstart.
3. Läs revisionsloggen och ledgern. Gå igenom aktiva stop-loss-utlösningar och juridiska hållningar.
4. Skriv ned orsaken och åtgärden. Underlaget till incidentrapporten i §28 kommer i Fas 5.

### Starta om
```bash
python -m aie kill release --as yorgo --reason "orsak och åtgärd"
python -m aie kill release --as robin --reason "instämmer: ..."
```
- **Två olika grundare** krävs. Röster från ett tidigare nödstopp räknas inte **(kod)**.
- **Revisionsloggen måste vara intakt** vid varje röst. Är den manipulerad går det inte att starta om förrän det är utrett **(kod)**.
- Varje röst och själva återstarten loggas i revisionsloggen **(kod)**.

## Stop-loss (ER-13, §26, D-029)

- **Kontroll:** `StopLoss.evaluate()` kontrollerar förlust per initiativ, total drawdown, departementsbudgetar och reserven mot `config/risk_limits.toml` och `config/budgets.toml` **(kod)**.
- **Vid utlösning:**
  - Nya åtaganden blockeras i det berörda området, alltså initiativet, departementet eller hela företaget **(kod)**.
  - Exponering och förpliktelser beräknas och loggas, och CRO, CFO och departementschefen anges som mottagare **(kod)**.
  - Befintliga förpliktelser avbryts inte. De betalas eller avbryts som vanligt via ledgern.
- **Återuppta:**
  1. Åtgärda läget, eller ändra gränsen via PR (D-019 punkt 3, båda grundarna).
  2. Två olika grundare godkänner var sin återhämtningsplan med `StopLoss.approve_resume()` **(kod)**.
  3. Det går inte medan gränsen fortfarande är nådd **(kod)**.
