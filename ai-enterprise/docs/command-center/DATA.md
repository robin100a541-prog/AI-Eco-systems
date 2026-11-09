# DATA: arkitektur och data för Command Center

- **Skriven:** 2026-11-09 (Del 0), verifierad mot koden och GitHub.
- **Källor:** varje påstående nedan har en källa: en fil, en tabell, en workflow eller ett API-anrop med datum.
- **Overifierat:** det som inte gick att verifiera står under **Overifierat**.

## 1. Repot
- **Språk:**
  - Python 3.11 och 3.12, med bara standardbiblioteket (D-002). Undantaget är Pillow i `src/aie/pod/design/` (D-070).
  - Gränssnittet är byggfri HTML, CSS och JS.
  - GitHub Actions används för drift.
- **Struktur:**
  - `ai-enterprise/src/aie/`: kärnan, med cirka 30 paket (`agents`, `audit`, `authorization`, `budget`, `ledger`, `governance`, `simulation`, `scout`, `pilot`, `pod`, `dev_agent`, `dashboard` med flera).
  - `config/*.toml`: konfigurationen. Den är skyddad och ändras bara med `founder-approved`.
  - `tests/`: `unittest`, med 864 tester 2026-11-09.
  - `.github/workflows/`: 13 workflows.

## 2. Agenterna
Rollerna kommer ur `config/permissions.toml` (`[roles.*]`). Agent-ID:n är de som koden registrerar.

| Agent-ID | Roll | Departement | Vad den gör | Registreras av |
|---|---|---|---|---|
| `ceo-1` | ceo | executive | samordnar, prioriterar och tilldelar uppgifter | `simulation/agents.py` (`ORG`) |
| `cfo-1` | cfo | finance | ekonomisk styrning och skattespår | samma |
| `cro-1` | cro | risk | riskgränser | samma |
| `comp-1` | compliance | compliance | lagar, avtal och plattformsvillkor | samma |
| `audit-1` | auditor | audit | oberoende granskning, med `recompute` (ER-16) | samma |
| `lead-1` | research_lead | research | leder Research, lägger ut till försäljning och gör prognoser | samma |
| `res-1` | researcher | research | utreder möjligheter. Används också som agent i Printify-workflows | samma |
| `scout-1` | scout | research | Opportunity Scout: letar och poängsätter möjligheter | `scout/cycle.py` |
| `dev-1` | developer | executive | utvecklaragenten: små kodändringar via PR | `dev_agent/cli.py` |

**Departementen** i config är sex: `executive`, `finance`, `risk`, `compliance`, `audit` och `research`. Det finns inga departement för Sales eller Engineering, så de visas inte.

## 3. Var och hur de körs
Alla körningar sker i GitHub Actions. Ingenting körs schemalagt på Yorgos eller Robins dator.

| Workflow | När | Vad | Tillstånd mellan körningar |
|---|---|---|---|
| `company-daily` | dagligen 04:23 UTC | `daily-cycle`: en SIM-dag med de 7 agenterna i `ORG`, rapporter och notis | `actions/cache`, prefix `company-` (`ai-enterprise/data`, cirka 28 KB) |
| `scout` | måndagar | `scout run` | `actions/cache`, prefix `scout-`. Det är en **egen** SIM-databas, skild från `company-` |
| `dev-agent` | onsdagar | utvecklaragenten | `actions/cache`, prefix `dev-agent-`, med bara väntande rapporter och en JSON-fil |
| `pod-orders` | dagligen | läser ordrar från Printify och bokför dem i **pilotens ledger (SEK, prod)** | `actions/cache`, prefix `pod-orders-` (`ai-enterprise/data-pilot`) |
| `printify-catalog` | dagligen | läser katalogen | ingen databas sparas. Artefakt |
| `pod-prepare`, `pod-publish`, `pilot-groq` | manuellt | piloten | ingen. Artefakt |
| `nightly` | dagligen | `simulate evaluate`, en isolerad testkörning | ingen |
| `dev-agent-guard` | vid push till main och måndagar | backar en trasig bot-commit och skriver veckorapporten | ingen |
| `ai-enterprise-tests`, `dashboard-world`, `protected-files` | PR och push | CI | ingen |

**Källa:** `.github/workflows/*.yml` och `gh api repos/.../actions/caches` (2026-11-09). Där syns cachenycklar som `company-42621583798-1` på 28 001 byte och `scout-42634068254-1` på 407 234 byte.

## 4. Hur saker registreras i dag
- **Intäkter, kostnader och transaktioner:** registreras i `ledger_entries` med `ledger_status` som historik. Det sker bara via `Ledger.record` (`src/aie/ledger/ledger.py`).
  - **Typer:** `revenue` (brutto), `fee` (plattformsavgift), `refund`, `cost`, `capital_in`, `capital_out` och `tax_payment`.
  - **Status:** `pending`, `settled`, `failed` och `cancelled`.
  - **Dubbletter:** varje post har `idempotency_key` (UNIQUE) och eventuellt `external_id` (UNIQUE). Dubbletter avvisas med `_refuse_duplicate`, och nekandet loggas.
  - **I SIM** bokförs intäkterna av `system:simulation`, inte av en agent. Det framgår av `recorded_by` i den lokala SIM-databasen 2026-11-08.
- **Resultat:** `compute_result` (`ledger/results.py`) räknar bara poster som är `settled`. Revisionen räknar om direkt från tabellerna med `recompute` (ER-16).
- **Kapital:** `capital_position` (`budget/capital.py`) ger likvida medel, skyddad reserv (`MINIMUM_RESERVE`), åtaganden, disponibelt och återinvesterbart kapital.
- **Skatt:** `TaxEngine` och tabellerna `tax_assignments`, `tax_events` och `tax_payments`.
- **Körningar, statusar och fel:** revisionsloggen `audit_log` (`audit/log.py`) med `seq`, en hashkedja med `prev_hash` och `AuditLog.verify()`.
  - **Exempel på händelser:** `llm.call` (detaljer: `caller`, `model`, `provider` och `tokens`), `simulation.day`, `simulation.action` (`agent` och `outcome`), `tool.denied`, `approval.requested`, `ledger.recorded` och `dependency.warning`.
  - **Agenternas livscykel:** `agents` och `agent_state_changes`.
  - **Uppgifter:** `tasks` och `task_events`.
  - **Gratiskvoter:** `provider_usage`, med anrop och tokens per dag och leverantör.
- **Godkännanden:**
  - `approval_requests` och `approval_votes` (`governance/escalation.py`)
  - `spend_approvals`
  - `assessments`
  - samråd i `consultations` och `consultation_opinions`, och tvister i `disputes`
- **Nödstopp och läge:** `kill_switch_events`, `operating_mode_events`, `stop_loss_trips` och `incidents`.

## 5. Databaser, loggar och API:er
- **SQLite:** `data/sim.db` (SIM) och `data-pilot/data/prod.db` (pilot, SEK). Båda är gitignorerade, och det finns 52 tabeller (`memory/migrations.py`).
- **Loggar:** `logs/aie.log` (JSON-rader), plus revisionsloggen i databasen.
- **Externa API:er:** Groq (LLM, gratis), Printify, YouTube och Etsy. Nycklarna finns som GitHub-hemligheter.

## 6. Befintliga dashboard-delar (före Command Center)
- **Ekobyn:** `docs/dashboard/index.html`, `world.js`, `world.css` och `status.json`. `status.json` skrivs av `export-status` och `daily-cycle` och committas via PR.
- **D1:s lokala server:** `src/aie/dashboard/server.py`, `auth.py` och `web/`, plus rörelsen från D-084.
- **Pinterest-sidor:** `docs/dashboard/app.html` och `privacy.html` är dubbletter enligt D-077.

## 7. Beslut: en auktoritativ plats för tillståndet (Del 0)
**Problem:**
- **Cachen kan försvinna:** företagets databas finns bara i Actions-cachen. GitHub tar bort en cachepost som inte använts på 7 dagar, och tar bort äldre poster när repots tak på 10 GB nås. Försvinner cachen startar `python -m aie init` en ny tom databas utan varning, och historiken är borta.
- **Data i git:** `company-daily` committar rapporter, `status.json` och grundarnotisen till repot. Det strider mot beslut 8 (inget data i git).
- **Två SIM-databaser:** scout har en egen SIM-databas (`scout-`), skild från företagets.

**Ingenting finns bara på Yorgos dator.** Den lokala `data/sim.db` är testdata från D0b.

**Lösning (genomförs i Del 1):** den **auktoritativa platsen är Cloudflare KV**, eftersom den är gratis, varaktig och nås utan att någon dator är på.
1. **Efter varje körning:** `company-daily` och `pod-orders` laddar upp en krypterad kopia av sin databas till KV, under nycklarna `state:company` och `state:pilot`.
   - **Kryptering:** `openssl enc -aes-256-cbc -pbkdf2` på runnern, med nyckeln i GitHub-hemligheten `STATE_KEY`. Klartext lämnar aldrig runnern.
2. **Före varje körning:** först används cachen, som är snabbast. Saknas den hämtas databasen från KV. Saknas den också startar en ny databas, och det loggas som fel och syns i snapshoten.
3. **Rapporterna och `status.json` committas inte längre.** De går till KV i snapshoten, och rapporterna sparas som Actions-artefakt (14 dagar).
4. **Ingen agent flyttas:**
   - Alla körs som förut i samma workflows.
   - Det som flyttas är bara **var databasfilen sparas mellan körningar**: från bara cachen till cache plus KV.
   - Scouts egna databas behålls som den är. Att slå ihop den med företagets är en fråga till grundarna, och den ändras inte här.
5. **Utan Cloudflare:** så länge `CLOUDFLARE_API_TOKEN` och `KV_NAMESPACE_ID` saknas fungerar allt som i dag, och steget hoppas över med en varning i körningens sammanfattning.

## 8. Actions-minuter (Del 0)
**Mätt:** de senaste 30 dagarna, 2026-10-10 till 2026-11-09, gick det 2 351 jobbminuter för `ai-enterprise tests`. Det är 438 körningar: 190 vid push till main och 248 på PR. Allt räknat per jobb och avrundat uppåt till hel minut, via `gh api .../actions/runs/{id}/jobs`.

**Ändrat:**
- **`ai-enterprise-tests.yml`:**
  - **Push till main:** bara Python 3.12.
  - **PR mot main:** 3.11 och 3.12, eftersom de krävs av grenskyddet.
  - **Bara dokument:** en PR som bara ändrar samtalsloggar, rapporter och `.md` i roten hoppar över testerna. Jobbet körs ändå, så att de krävda kontrollerna rapporteras.
  - **Concurrency:** en ny commit avbryter en pågående körning (cancel-in-progress).
  - **Cache:** pip-cache för Pillow.
- **`protected-files.yml`:** concurrency med cancel-in-progress.
- **`nightly.yml`:** körs en gång i veckan i stället för varje natt. Den är en utvärdering, inte en agent.
- **Inga data-PR:er (beslut 8):** company-daily och scout slutar öppna dagliga PR:er med data (Del 1). Det tar bort cirka 34 PR:er och lika många push-körningar per månad.

**Beräknat per månad**, med samma regler tillämpade på förra månadens körningar:

| Workflow | Minuter |
|---|---|
| ai-enterprise tests (cirka 156 PR:er, alltså förra månadens takt utan bot-PR:erna) | cirka 1 220 |
| protected-files | cirka 150 |
| company-daily (dagligen, med publicering) | cirka 75 |
| control-ingest (nytt, cirka 30 knapptryck) | cirka 30 |
| printify-catalog och pod-orders (dagligen) | cirka 60 |
| command-center-tester (nytt, bara PR:er som rör `command-center/`) | cirka 60 |
| dev-agent, dev-agent-guard, nightly, scout och manuella körningar | cirka 120 |
| **Summa** | **cirka 1 700** |

**Slutsats:**
- **Över taket i dag:** med förra månadens takt, som var en byggmånad med cirka 190 sammanslagna PR:er, hamnar förbrukningen över 1 400.
- **Kostnad per PR:** varje sammanslagen PR kostar cirka 9 minuter. Det är tester på två versioner, en version vid push och protected-files.
- **Grundlasten:** utan PR:er är grundlasten cirka 285 minuter.
- **Gränsen:** taket på 1 400 hålls med **högst cirka 120 sammanslagna PR:er per månad**. Det kräver färre och större PR:er, till exempel en per del som i Command Center.
- **Tills vidare kostar det inget:** repot är fortfarande publikt, och publika repon har obegränsade Actions-minuter.

## 9. Snapshoten (Del 1, D-088)
**Byggs av:** `py -m aie publish` i company-daily, ur företagets databas och bara med kärnans funktioner (`src/aie/dashboard/snapshot.py`).
- **Där den ligger:** den laddas upp till KV som `snapshot:latest` och `snapshot:<datum>`, där historiken sparas i 35 dagar.
- **Hur den läses:** `functions/api/snapshot.js` serverar den oförändrad, och den lokala servern bygger samma schema ur den lokala databasen.
- **Om uppladdningen misslyckas:** felet loggas, snapshoten sparas i `data/publish-pending/`, och kommandot avslutar ändå med 0. Agenterna påverkas aldrig, och nästa körning försöker igen.

### Schema `aie.snapshot/1`
Varje siffra är `{"value", "source", "as_of"}`. Varje lista är `{"items", "source", "as_of"}`. Saknas data är `value` null, och gränssnittet visar "N/A".

| Fält | Innehåll | Källa |
|---|---|---|
| `generated_at`, `environment`, `currency` | när snapshoten byggdes, och sim/SIM eller prod | konfigurationen |
| `system` | `mode` (normal, protected eller kill switch), `kill_switch`, `protected_mode`, `last_run` och `last_run_day` (senaste `simulation.day`) samt `version` | `KillSwitch`, `ProtectedMode`, `audit_log` och `aie.__version__` plus `GITHUB_SHA` |
| `economy` | `revenue_gross`, `refunds`, `costs`, `platform_fees`, `net_profit_realized`, `preliminary` (skäl), `tax_reserve`, `liquid`, `disposable_capital`, `protected_reserve` och `vat` (`sales`, `threshold`, `level`) | `compute_result`, `capital_position` och `TaxEngine` |
| `economy_real` | samma fält för pilotens databas (SEK) om den finns, annars null | samma |
| `periods.day`, `.week`, `.month` | `period`, `revenue`, `cost` (kostnader plus avgifter plus återbetalningar) och `net` | `compute_result` per period |
| `per_agent` | `agent` (den som bokförde, alltså `recorded_by`), `revenue`, `cost` och `net` | `compute_result` per `recorded_by` |
| `ledger` | de 500 senaste posterna: `id`, `key` (idempotensnyckeln), `type`, `amount`, `status`, `by`, `initiative`, `department`, `date` och `external_id`, plus `total` | `Ledger.entries` |
| `agents` | `id`, `name`, `role`, `department`, `level`, `description`, `lifecycle`, `status`, `manager`, `task`, `progress` (alltid null), `model`, `last_run`, `runs`, `actions_done`, `actions_failed`, `success_rate` och `tools` (mandatet) | `AgentRegistry`, `permissions.toml`, `audit_log` och `tasks` |
| `departments` | `id`, `roles` och `agents` | `permissions.toml` och `AgentRegistry` |
| `approvals` | `id`, `kind`, `task`, `amount`, `status`, `required`, `votes`, `goal`, `risk_class`, `max_loss`, `stop_conditions`, `opinions` och `objections` | `approval_requests`, `approval_votes` och `consultation_opinions` |
| `risk_limits` | `name`, `limit` och `used`. `used` finns bara där kärnan räknar användningen, annars null | `risk_limits.toml`, `capital_position` och `compute_result` per initiativ |
| `blocks_today` | `step`, `what` och `count` | `audit_log`: `tool.denied`, `budget.blocked` och `ledger.duplicate_refused` |
| `events` | de 300 senaste: `id` (unikt, till exempel `audit:<seq>`, `agent:<id>` eller `task:<id>`), `at`, `actor`, `action`, `type` och `hash` | `audit_log`, `agent_state_changes` och `task_events` |
| `audit_chain` | `ok`, `length` och `first_bad_seq` | `AuditLog.verify` |
| `quotas` | `provider`, `day`, `calls` mot `calls_limit` och `tokens` mot `tokens_limit` | `provider_usage` och `providers.toml` |

### Brutto och netto
- **Brutto (`revenue_gross`):** summan av poster av typen `revenue` med status `settled`. Avgifter och återbetalningar dras **inte** av. De är egna posttyper (ER-23).
- **Netto (`net_profit_realized`):** brutto minus `refund`, `cost` och `fee`, bara för poster som är `settled`. `pending` räknas aldrig (ER-11), och `capital_in`, `capital_out` och `tax_payment` är varken intäkt eller kostnad.
- **Preliminärt:** om någon post väntar, eller om ett initiativ har intäkter utan kostnader, står skälen i `economy.preliminary`. Gränssnittet visar då "Preliminary".
- **Kontrollen:** siffrorna är exakt revisionens omräkning. Testet `test_snapshot_matches_the_audit_agents_recomputation` kör `recompute` (ER-16) mot snapshoten.

### Dubbletter
- **Poster:** varje post har `idempotency_key` (UNIQUE) och eventuellt `external_id` (UNIQUE).
  - **Samma nyckel och samma innehåll** är ett omförsök. Det ger samma post (`ledger.replayed`), så posten räknas en gång.
  - **En ny post med ett externt ID som redan finns** avvisas och loggas som `ledger.duplicate_refused`.
- **Händelser:** händelsernas ID:n är unika, och revisionsloggens `seq` är unik.

### Agentstatus (härledd, regeln är den här)
| Status | När |
|---|---|
| `offline` | livscykeln är `suspended` eller `retired` |
| `blocked` | agentens pågående uppgift har status `blocked` |
| `waiting` | agenten har en förfrågan som väntar på en grundare |
| `working` | agenten har en pågående uppgift (`assigned` eller `in_progress`) |
| `idle` | aktiv utan uppgift |
| `unknown` | annan livscykel, till exempel `created` eller `testing`. Visas inte som status |

En **körning** (`runs`) är ett modellanrop (`llm.call`) med agenten som `caller`.
- **Lyckade åtgärder** är `simulation.action` med `outcome = done`.
- **Misslyckade** är andra utfall plus `tool.denied` för agenten.

### KV-nycklar
| Nyckel | Skrivs av | Innehåll |
|---|---|---|
| `snapshot:latest`, `snapshot:<YYYY-MM-DD>` | `py -m aie publish` | snapshoten |
| `report:<fil>` | `py -m aie publish --reports` | de tre senaste dagliga rapporterna (35 dagar) |
| `state:company`, `state:scout`, `state:pilot` | `scripts/state.sh push` | krypterad databaskopia (D-093) |

## Overifierat
- **Pilotens databas:** pod-orders har ingen cachepost bland de 20 senaste, så om pilotens databas har några poster är inte verifierat. Den kan inte läsas utan att köra workflowen.
- **Groq-kvoten i drift:** Groqs verkliga gratiskvot kontrolleras inte här. `provider_usage` räknar bara det som systemet självt har använt.
