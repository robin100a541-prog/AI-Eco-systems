# Nattbotens backlogg

Egna förbättringsuppgifter för nattboten när det inte finns någon ledig uppgift i `ROADMAP.md`.
Reglerna står i `docs/BOT.md` avsnitt 2b. Prioritet: 1 buggar, 2 kravtäckning, 3 säkerhet,
4 kodkvalitet, 5 dokumentation, 6 förberedelse av nästa fas (bara text).

Format: `- [ ] BL-NNN (prioritet) Vad och var. Klart när: `kontroll` — status`. Kontrollen bevisar att punkten är klar (`ruff <fil> [REGEL]`, `test <test-id>`, `flaky-test <test-id>`, `verifies <KRAV-ID>`, `grep <fil> <text>`, `!grep <fil> <text>`; se `src/aie/dev_agent/verify.py`). Utvecklaragenten tar bara punkter med kontroll och skriver själv in en kontroll där den saknas.
Varje körning lägger till minst 3 nya punkter. Grundarna får lägga till, ändra ordning eller stryka punkter.

## Öppna

- [ ] BL-001 (1 buggar) Kör hela sviten 3 gånger per Python-version (`python3.11/3.12/3.13 -m unittest discover -s tests`). Notera varje test som någon gång fallerar, med felutskrift. Klart när alla körningar är gröna, eller varje instabilt test har en egen BL-punkt med orsak Klart när: `test tests.unit.test_all` — öppen
- [ ] BL-002 (2 kravtäckning) ER-12 (riskklass före godkännande) och SR-15 har inget test som nämner dem (`grep -rn "ER-12\|SR-15" tests/` är tomt, 2026-10-28). Läs kraven i `REQUIREMENTS.md`, hitta koden som uppfyller dem och skriv tester märkta `Verifies ER-12` och `Verifies SR-15`. Uppfylls kravet inte av koden: gör en grundarfråga i stället för att bygga en ny funktion — öppen
- [ ] BL-003 (2 kravtäckning) FR-14, FR-26 och DR-02, DR-04, DR-06, DR-08, DR-09, DR-10, DR-11 saknar test som nämner dem (2026-10-28). En PR per krav eller per liten grupp. Krav som hör till en fas som inte är byggd (Fas 7 eller senare) noteras här i stället Klart när: `verifies FR-14`, `verifies FR-26`, `verifies DR-02`, `verifies DR-04`, `verifies DR-06`, `verifies DR-08`, `verifies DR-09`, `verifies DR-10`, `verifies DR-11` — öppen
- [ ] BL-004 (4 kodkvalitet) `ruff check src tests` ger 78 fynd (2026-10-28), varav 35 `I001` (osorterade importer). Rätta bara `I001`, med `ruff check --select I001 --fix`. Testerna ska vara oförändrade och gröna före och efter. Övriga regler blir egna punkter — öppen
- [ ] BL-005 (5 dokumentation) `PROJECT_STATUS.md` och `ROADMAP.md` anger testantal från olika tillfällen. Kör sviten, uppdatera siffrorna till dagens riktiga antal och kontrollera att varje kommando i `docs/setup.md` fungerar som beskrivet — öppen
- [ ] BL-006 (4 kodkvalitet) Lägg till en `__repr__`‑metod på `Agent` för tydligare debugging. Klart när: `grep src/aie/agents/registry.py def __repr__` — öppen
- [ ] BL-007 (2 kravtäckning) I `register`‑metoden, lägg till en kontroll att `manager_id != agent_id` (en agent får inte vara sin egen chef). Klart när: `grep src/aie/agents/registry.py manager_id != agent_id` — öppen
- [ ] BL-008 (5 dokumentation) Utöka docstringen för `AgentRegistry.register` med beskrivning av `reason`‑parametern och vilka fel som kan kastas. — öppen
- [ ] BL-009 (2 kravtäckning) Skriv enhetstest som verifierar att `AgentRegistry.set_guard` kastar `RegistryError` om `guard` saknar `transition_block_reason`. Klart när: `test tests.unit.test_registry.TestAgentRegistry.test_set_guard_invalid` — öppen

## Pågår

_Inget._

## Klart

_Inget ännu._
