# Nattbotens backlogg

Egna förbättringsuppgifter för nattboten när det inte finns någon ledig uppgift i `ROADMAP.md`.
Reglerna står i `docs/BOT.md` avsnitt 2b. Prioritet: 1 buggar, 2 kravtäckning, 3 säkerhet,
4 kodkvalitet, 5 dokumentation, 6 förberedelse av nästa fas (bara text).

Format: `- [ ] BL-NNN (prioritet) Vad och var. Klart när: `kontroll` — status`. Kontrollen bevisar att punkten är klar (`ruff <fil> [REGEL]`, `test <test-id>`, `flaky-test <test-id>`, `verifies <KRAV-ID>`, `grep <fil> <text>`, `!grep <fil> <text>`; se `src/aie/dev_agent/verify.py`). Utvecklaragenten tar bara punkter med kontroll och skriver själv in en kontroll där den saknas.
Varje körning lägger till minst 3 nya punkter. Grundarna får lägga till, ändra ordning eller stryka punkter.

## Öppna

- [ ] BL-001 (1 buggar) Kör hela sviten 3 gånger per Python-version (`python3.11/3.12/3.13 -m unittest discover -s tests`). Notera varje test som någon gång fallerar, med felutskrift. Klart när alla körningar är gröna, eller varje instabilt test har en egen BL-punkt med orsak Klart när: `test tests.unit.test_all` — öppen
- [ ] BL-002 (2 kravtäckning) ER-12 (riskklass före godkännande) och SR-15 har inget test som nämner dem (`grep -rn "ER-12\|SR-15" tests/` är tomt, 2026-10-28). Läs kraven i `REQUIREMENTS.md`, hitta koden som uppfyller dem och skriv tester märkta `Verifies ER-12` och `Verifies SR-15`. Uppfylls kravet inte av koden: gör en grundarfråga i stället för att bygga en ny funktion — öppen
- [ ] BL-005 (5 dokumentation) `PROJECT_STATUS.md` och `ROADMAP.md` anger testantal från olika tillfällen. Kör sviten, uppdatera siffrorna till dagens riktiga antal och kontrollera att varje kommando i `docs/setup.md` fungerar som beskrivet — öppen
- [ ] BL-008 (5 dokumentation) Utöka docstringen för `AgentRegistry.register` med beskrivning av `reason`‑parametern och vilka fel som kan kastas. — öppen
- [x] ~~BL-009~~ — ersatt av BL-018 2026-11-03 (Yorgo): punkten kunde inte göras som den stod, se Q-BOT-005
- [x] ~~BL-010~~ — ersatt av BL-019 2026-11-03 (Yorgo): punkten kunde inte göras som den stod, se Q-BOT-006
- [x] BL-011 (4 kodkvalitet) Lägg till en `return 0` i slutet av `_check_config` så funktionen alltid returnerar en exit‑kod. Klart när: `grep src/aie/__main__.py return 0` — klar (redan gjort: `_check_config` slutar med `return 0`. Den gamla kontrollen `!grep … "return 0"` var omvänd och kunde aldrig gå igenom. Yorgo, 2026-11-03)
- [x] BL-013 (2 kravtäckning) Skriv ett enhetstest som anropar `_check_config` med en giltig konfigurationskatalog och verifierar att den returnerar `0`. Klart när: `test tests.unit.test_main.TestMain.test_check_config_function_returns_zero` — klar (2026-11-03, Yorgo; den gamla kontrollen pekade på en funktion på modulnivå som unittest inte kan köra)
- [x] BL-014 (2 kravtäckning) Sätt standardvärde för `details` till tom `dict` i `append`‑signaturen och uppdatera docstringen. Klart när: `grep src/aie/audit/log.py ett föränderligt standardvärde delas` — klar (2026-11-03, Yorgo): bara docstringen. Standardvärdet förblir `None`, eftersom `{}` som standardvärde delas mellan anrop. Den gamla kontrollen krävde just det felet
- [x] BL-015 (5 dokumentation) Lägg till en kort beskrivning av `Verification.head_hash` i klass‑docstringen för att förklara dess roll vid trunkeringsdetektering. Klart när: `grep src/aie/audit/log.py syns en trunkering` — klar (2026-11-03, Yorgo; den gamla kontrollen med `-A2` var inget giltigt grep-mönster)
- [x] BL-016 (2 kravtäckning) Implementera enhetstest som verifierar att `AuditEntry.expected_hash()` returnerar samma hash som lagras i `AuditEntry.hash` för en ny rad. Klart när: `test tests.unit.test_audit.TestAppend.test_expected_hash_matches_stored_hash` — klar (2026-11-03, Yorgo; modulen heter test_audit, och hemlighetsvarningen var ett falsklarm från testernas låtsasvärden i test_audit.py)
- [ ] BL-017 (5 dokumentation) Lägg till en docstring på `_canonical` som förklarar varför `allow_nan=False` används och hur sortering av nycklar garanterar deterministisk hash. Klart när: `grep src/aie/audit/log.py "Deterministisk hash"` — öppen
- [ ] BL-018 (2 kravtäckning) `AgentRegistry.set_guard` i `src/aie/agents/registry.py` ska kasta `RegistryError` när `guard` inte är `None` och saknar metoden `transition_block_reason`. Lägg till kontrollen i `set_guard` och ett test i en ny fil `tests/unit/test_agent_registry.py`, klass `TestSetGuard`. (Ersätter BL-009, 2026-11-03, Yorgo: den gamla punkten bad bara om ett test för ett beteende som inte fanns, och klassen TestAgentRegistry finns inte.) Klart när: `test tests.unit.test_agent_registry.TestSetGuard.test_set_guard_invalid` — öppen
- [ ] BL-019 (2 kravtäckning) Testa att `AgentRegistry.set_guard(None)` i `src/aie/agents/registry.py` tas emot och att övergångar då tillåts utan vakt. Testet läggs i `tests/unit/test_agent_registry.py`, klass `TestSetGuard`. (Ersätter BL-010, 2026-11-03, Yorgo: kontrollen pekade på tests.unit.test_registry, som testar plattformsregistret.) Klart när: `test tests.unit.test_agent_registry.TestSetGuard.test_set_guard_none` — öppen

## Pågår

_Inget._

## Klart

- [x] ~~BL-004 (4 kodkvalitet) `ruff check src tests` ger 78 fynd (2026-10-28), varav 35 `I001` (osorterade importer). Rätta bara `I001`, med `ruff check --select I001 --fix`. Testerna ska vara oförändrade och gröna före och efter. Övriga regler blir egna punkter~~ — struken 2026-11-03 (Yorgo): ruff-varningar är inga uppgifter längre, se `dev_agent/picker.py`
- [x] BL-012 (2 kravtäckning) Skriv ett enhetstest som anropar `main()` med argumentet `check-config` och verifierar att exit‑koden är 0 vid giltig konfiguration. Klart när: `test tests.unit.test_main.TestMain.test_check_config_success` — klar (2026-11-01)
- [x] BL-007 (2 kravtäckning) I `register`‑metoden, lägg till en kontroll att `manager_id != agent_id` (en agent får inte vara sin egen chef). Klart när: `grep src/aie/agents/registry.py manager_id != agent_id` — klar (2026-10-31)
- [x] BL-003 (2 kravtäckning) FR-14, FR-26 och DR-02, DR-04, DR-06, DR-08, DR-09, DR-10, DR-11 saknar test som nämner dem (2026-10-28). En PR per krav eller per liten grupp. Krav som hör till en fas som inte är byggd (Fas 7 eller senare) noteras här i stället Klart när: `verifies FR-14`, `verifies FR-26`, `verifies DR-02`, `verifies DR-04`, `verifies DR-06`, `verifies DR-08`, `verifies DR-09`, `verifies DR-10`, `verifies DR-11` — klar (2026-10-31)
- [x] BL-006 (4 kodkvalitet) Lägg till en `__repr__`‑metod på `Agent` för tydligare debugging. Klart när: `grep src/aie/agents/registry.py def __repr__` — klar (2026-10-29, #104)
