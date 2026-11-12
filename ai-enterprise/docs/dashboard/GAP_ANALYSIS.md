# Gapanalys: kommandocentralen mot befintlig kod (D0, 2026-11-08)

> **Läget 2026-11-11:** analysen beskriver läget före Command Center. Sedan dess gäller:
> - **Borttaget:** Ekobyn (`index.html`, `world.js`, `world.css`, `status.json`), `aie export-status` och testet `dashboard_world.cjs`.
> - **Kvar ur `export.py`:** vitlistan, `check_public` och de fasta agentnamnen. De används av snapshoten.
> - **PR #137** är stängd (avsnitt 7).
> - **"Pausa alla agenter"** finns nu som `ControlStops.place_all` (avsnitt 6 sa att funktionen saknades).
> - **Aktuell beskrivning:** `docs/command-center/DATA.md`.

Den första versionen skrevs innan `DASHBOARD_PLAN.md` fanns i repot. Planen lades in senare samma dag, och avsnitt 6
mappar nu varje steg D0–D8 mot befintlig kod. Stegen i planen är omskrivna efter den här analysen.

Underlaget är `main` vid commit `4bbbb77` (2026-11-08).

## 1. Det som finns i dag

### Gränssnittet: `ai-enterprise/docs/dashboard/`
| Fil | Vad | Kan återanvändas |
|---|---|---|
| `index.html`, `world.css`, `world.js` (162 rader) | **Ekobyn**: en tecknad by med ett hus per departement, vandrande agenter, aktivitetsbubblor, mötestorg, agentval, följkamera, paus och reducerad rörelse. Den hämtar `status.json` var 15:e sekund, validerar den och visar datatiden. Nödstopp och skyddat läge fryser animationen. Sidan är bara en läsvy, utan kommandon. | Ja: byggfri struktur, `validate()`, laddning och fel, reducerad rörelse, `money()`, och mönstret "bara offentliga data" |
| `app.html`, `privacy.html` | Appbeskrivning och integritetspolicy för Pinterests granskning (PR #176) | Inte för dashboarden. Se avsnitt 3 om dubbletterna |
| `status.json` | Den offentliga ögonblicksbilden som den dagliga cykeln skriver | Ja, och det är datakontraktet |
| `README.md` | Hur sidan körs lokalt och testas | Ja |

**Gränssnittets språk är svenska**, till exempel "vår lilla värld" och "Uppdatera data". Den nya regeln i
`CLAUDE.md` säger att dashboardens gränssnitt ska vara på engelska. Det är ett gap.

### Data: `ai-enterprise/src/aie/dashboard/`
- **`export.py` (`aie export-status`):** bygger `status.json` med en **vitlista** av fält:
  - agenterna, med ID, förnamn, roll, departement, status och en generisk aktivitet ur revisionsloggens åtgärdstyp, aldrig fritext
  - om ett möte pågår
  - nödstopp och skyddat läge
  - scoutens pipeline
  - poängtavlan med SIM och riktig valuta var för sig

  Varje textvärde prövas mot `mask_secrets` (`check_public`), och en hemlighet stoppar exporten (DR-13). Det här är den naturliga datakällan för kommandocentralen.
- **`cycle.py` (`aie daily-cycle`):**
  - kör en företagscykel per dygn
  - skriver dags- och veckorapporter i `docs/reports/`, `status.json` och en notis i `QUESTIONS-FOR-FOUNDERS.md`
  - har ett nödstopp via filen `docs/KILL-SWITCH`
- **Arbetsflödet** `.github/workflows/company-daily.yml` kör cykeln varje dygn och har ett jobb `pages` som publicerar `ai-enterprise/docs/dashboard`. Se avsnitt 2.

### Tester
| Test | Antal | Läge |
|---|---|---|
| `tests/unit/test_dashboard.py` | 7 | Gröna i CI på Linux. 5 faller lokalt på Windows (avsnitt 5) |
| `tests/dashboard_world.cjs` (`node --test`) | 8 | Körs av `dashboard-world.yml` när `docs/dashboard/**` ändras |

### Pågående arbete som berör dashboarden
- **PR #137** "show actual live agent work and meeting participants" (Robin/Codex) är öppen, rebasad och grön i CI 2026-11-03. Den lägger till live-status (`src/aie/dashboard/live.py`) med "Gör nu", "Borde göra" och "Senaste rapport". Den använder `fcntl`, som bara finns på POSIX, och fungerar därför inte på Windows. Den bör slås ihop eller stängas innan kommandocentralen byggs, så att arbetet inte görs två gånger.

### Andra datakällor som en kommandocentral kan visa
Allt finns redan som kommandon i `python -m aie`:
- `approvals`: grundarnas kö
- `kill`: nödstopp
- `report daily|periodic|monitor`
- `scout`: möjlighetsregistret
- `registry`: plattformar och initiativ
- `spend`: utgiftsgodkännanden
- `results`: utfall
- `pod list|orders`: lanseringen Q4 (`products/q4/LISTA.md`)
- `pilot status`

Ingen av dem exporterar till `status.json` i dag, utom scouten och poängtavlan.

## 2. Publiceringen: läget, utan ändringar
**Kommandon och utdata, 2026-11-08:**
```
gh api repos/robin100a541-prog/AI-Eco-systems/pages   → HTTP 404 (Pages är inte påslaget)
gh repo view … --json visibility                      → PUBLIC
curl https://robin100a541-prog.github.io/AI-Eco-systems/              → 404
curl https://robin100a541-prog.github.io/AI-Eco-systems/status.json   → 404
curl https://robin100a541-prog.github.io/AI-Eco-systems/privacy.html  → 404
company-daily, senaste körningen: cycle success, verify skipped, pages failure
```
**Slutsatser:**
- **GitHub Pages är inte påslaget.** Jobbet `pages` i `company-daily` misslyckades därför varje dygn. Dashboarden är inte publicerad via Pages. **Jobbet är borttaget** enligt D-075, i samma PR.
- **Repot är publikt.** Allt som committas kan läsas på github.com, även utan Pages: `status.json`, rapporterna, `products/q4/LISTA.md`, `meta.json` och konfigurationen. ROADMAP 0.7 säger "privat GitHub-repo". Det stämmer alltså inte med verkligheten. Det är en fråga till grundarna.

## 3. Kontroll av känsliga uppgifter i det som är offentligt
Kontrollen gjordes på `origin/main` med `git grep`:
| Vad | Fynd |
|---|---|
| **Hemligheter** (mönster för Groq, OpenAI, GitHub, AWS, JWT och Slack) | **Inga.** Den enda träffen är en avsiktlig teststräng i `tests/unit/test_dashboard.py` |
| **Belopp i `status.json`** | Bara SIM: kapital 50 000, reserv 10 000 och resultat 0 i minsta enhet. `real` är `null`. Inga belopp i riktig valuta |
| **Personuppgifter** | **Robins fullständiga namn, e-postadress och ort** står i `index.html`, `app.html` och `privacy.html` i repots **rot** och i `docs/` i rotmappen. De kom till i commit `4bbbb77` för Pinterests granskning. De är offentliga i repot. Jag har inte ändrat dem |
| **Personnummer eller telefonnummer** | Inga träffar |
| **Andra uppgifter som är synliga** | Printify-butikens id och produkt-id samt priser i `products/q4/`. Grundarnas färdigheter och "familjens fastighetsbolag" i `config/founders.toml`. Datorernas OS och Python-version i `docs/environment.md`. Inget av det är hemligt, men det är offentligt |

**Dubbletter:** det finns nu **två uppsättningar** Pinterest-sidor:
- `ai-enterprise/docs/dashboard/app.html` och `privacy.html` (PR #176, utan personuppgifter)
- repots rot och `docs/` (4bbbb77, med Robins kontaktuppgifter)

Vilken som gäller är en fråga till grundarna.

## 4. Gap som syns redan nu, utan planen
1. **Språket:** gränssnittet är på svenska, men regeln kräver engelska.
2. **Publiceringen:** Pages är inte påslaget, och `pages`-jobbet misslyckas dagligen. Antingen slår en grundare på Pages, eller tas jobbet bort.
3. **Synlighet:** repot är publikt. En kommandocentral med belopp i riktig valuta eller med beslutsunderlag kan inte ligga i `status.json` så länge repot är publikt.
4. **Bara läsning:** sidan har inga kommandon, med avsikt. Den finns på en publik adress utan inloggning. En "kommandocentral" som styr något kräver en lokal server och kan inte ligga på Pages. Det är en fråga.
5. **Datafärskhet:** `status.json` skrivs en gång per dygn av `company-daily`. Live-status finns bara i PR #137.
6. **Datakällorna:** kön, nödstoppet, rapporterna och lanseringen exporteras inte till dashboarden än.
7. **Windows:** 5 av de 7 dashboard-testerna faller lokalt på Windows (avsnitt 5).

## 5. Egen uppgift: de 12 testfelen på Windows (rörs inte i D0)
Med `py -m unittest discover -s tests` den 2026-11-08 kördes 836 tester. Det gav 3 failures och 9 errors, och alla är gröna i CI på Linux:
- `test_dashboard`: 5 errors, i `TestDailyCycle` (2) och `TestReportDate` (3)
- `test_dev_agent`: 3 errors, i `TestGitHub`, `TestRateLimits` och `TestReportsWithoutPR`
- `test_dev_agent_safety`: 1 error, `test_weekly_summary_counts_runs_items_and_red_tests`
- `test_backup`: 1 failure, `test_online_wal_backup_restores_ledger_approvals_and_audit`
- `test_periodic_report`: 1 failure, `test_report_commands_run_against_a_fresh_database`
- `test_scout`: 1 failure, `test_dashboard_and_questions`

Trolig orsak, inte utredd: låsta SQLite-filer vid städning och sökvägar med `/` i jämförelser. Uppgiften står i `TODO.md`.

## 6. Mappning mot D0–D8
| Steg | Finns redan | Återanvänds | Saknas |
|---|---|---|---|
| D0 | CLAUDE.md, ROADMAP och den här analysen | — | inget, D0 är klar på grenen `dashboard/d0-setup` |
| D0b | `python -m aie simulate` fyller en SIM-databas genom spärrarna, och `require_sim` vägrar prod | hela simuleringen | ett tunt `scripts/seed_sim.py` som lägger 3 väntande godkännanden. Planens "14 agenter i 8 departement" finns inte i `permissions.toml`, där det är 6 departement |
| D1 | inget serverkod. Gränssnittet är byggfritt med `node --test` | Ekobyns struktur, `validate()`, reducerad rörelse och testmönster | `src/aie/dashboard/server.py`, inloggning, CSRF, skalet, typsnitten Cormorant Garamond och Inter, och engelskt gränssnitt |
| D2 | revisionsloggen och `AuditLog.verify()`; vitlistan i `export.py`, `ACTIVITY` och `check_public` | vitlistan och aktiviteterna; arbetsfaserna och mötesdeltagarna ur PR #137 | `/api/stream` (SSE) och sidan Activity log |
| D3 | Ekobyns hus och agenter, `ensure_names`, `AgentRegistry`, `TaskBoard`, `ConsultationBoard`, `LessonRegistry` och `PerformanceReview` | husmotivet och namnen | GET-endpoints, och sidorna Departments, Department och Agent |
| D4 | `EscalationQueue`, `SpendApprovals`, `AssessmentStore` och `DisputeBoard`, med CLI:erna `approvals`, `spend` och `assess` | alla kärnfunktioner | sidan Approvals, som samlar de tre köerna. Regeln för "båda grundarna" beror på Q-09 |
| D5 | `compute_result`, `capital_position`, `TaxEngine`, `KillSwitch`, `ProtectedMode`, `IncidentLog` och `recompute` | allt | sidorna Finance, Risk och Home. **En kärnfunktion som pausar alla agenter saknas** |
| D6 | `LLMGateway`, `ProviderRouter` och kvoterna | allt | chatten utan verktyg på Agent-sidan |
| D7 | notisen i `QUESTIONS-FOR-FOUNDERS.md` från `cycle.py`; utlösarna i `KillSwitch`, `StopLoss` och `tool.denied` | utlösarna | `src/aie/notify/` med ntfy och SMTP |
| D8 | Ekobyn fungerar i mobilbredd | layoutmönstren | `TESTING.md` och kontroll av alla nya sidor |

## 7. PR #137 (live-status): granskning 2026-11-08
**Vad PR:en gör:**
- **Ändringarna:** 16 filer, varav en ny `src/aie/dashboard/live.py` på 185 rader, och 142 rader tester.
- **Funktionen:** den skriver en offentlig live-ögonblicksbild till `docs/dashboard/status.json`.
  - **Innehåll:** "Gör nu", "Borde göra", mötesdeltagare och ett livstecken med en lease på 10 sekunder.
  - **Hur:** en hjärtslagstråd skriver bilden, och en fil-lås per målfil skyddar den.
  - **Observerar** gatewayens och läsarens anrop utan extra modellanrop.
- **Läget:** CI var grönt 2026-11-03 (dashboard, unittest 3.11 och 3.12, protected-files). Sedan dess har main ändrats, och GitHub visar `mergeable: UNKNOWN`.

**Bedömning: slå inte ihop före D1 (D-079).**
1. **Den bygger på Ekobyn** (`world.js`), som kommandocentralen ersätter.
2. **Den skriver live-status till en publik fil** i ett publikt repo, men D-074 och D-075 gör repot privat och tar bort Pages.
3. **Den använder `fcntl`,** som bara finns på POSIX. Yorgo kör Windows, och 8 av dess tester faller lokalt där.
4. **Idéerna är bra och tas med i D2:** arbetsfaserna (`PHASES`), att bara verkliga mötesdeltagare visas, och att observera utan extra modellanrop. I kommandocentralen räknas de ur revisionsloggen och går via `/api/stream`, inte via en fil.

Robin avgör om PR:en stängs med en hänvisning hit eller hålls öppen som referens.

## 8. Uppföljning 2026-11-11: vad som blev av gapen
| Gap i analysen | Vad som hände |
|---|---|
| GitHub Pages var inte påslaget | Cloudflare Pages används i stället (D-085) |
| Repot är publikt | Fortfarande publikt. Robin gör det privat enligt `docs/command-center/DEPLOY.md` steg 1 |
| `status.json` committades varje dygn | Inget data committas längre (D-092). Snapshoten ligger i Cloudflare KV |
| PR #137 (live-status) | Stängd 2026-11-11. Agenternas status och samråd visas ur snapshoten |
| Pinterest-dubbletterna | Borttagna: `docs/dashboard/app.html` och `privacy.html`, och kopian i rotens `docs/`. Sidorna i repots rot finns kvar (D-077) |
| En kärnfunktion som pausar alla agenter saknades | `ControlStops.place_all` |
| 12 tester föll på Windows | 6 är rättade (`test_dashboard` 5 och `test_scout` 1): de läste filer utan `encoding="utf-8"`. 6 återstår |
