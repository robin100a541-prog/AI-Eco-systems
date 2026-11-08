# DASHBOARD_PLAN — kommandocentralen

**Skapad:** 2026-11-08 av Claude (session med Yorgo) · **Status:** Förslag, kräver beslut D-073 (föreslaget 2026-11-08) · **Uppdaterad:** 2026-11-08: nummer rättade (teknikvalet heter nu D-073) och stegen D0–D8 omskrivna så att de bygger på det som finns, se `GAP_ANALYSIS.md`. Originaltexten finns i git-historiken (commit f84d485).
**Design:** designytan "AI-Ecosystem — startsida" i Yorgos Claude-konto (10 sidor, klickbar prototyp)

## 1. Vad dashboarden är

Dashboarden är systemets ögon och knappar för er två. Den ersätter Robins tidigare animerade värld (Ekobyn), men återanvänder dess datakontrakt, validering och husmotiv (se `GAP_ANALYSIS.md`). I arkitekturen är den två av komponenterna i §39: Monitoring (se allt) och Human Approval Interface (godkänna, pausa, stoppa).

Grundregler:
1. Allt är live och sant. Varje siffra läses från databasen (ledger, audit-logg, agentregister). Inga siffror räknas fram i webbläsaren och inga påhittade värden visas. Saknas data står det "saknas".
2. Dashboarden fattar inga egna beslut. Varje knapp anropar samma kärnfunktion som CLI:t (approve, reject, pause, kill). Den skriver aldrig direkt i databasen och kan aldrig gå förbi kontrollkedjan.
3. Budgetar och gränser ändras inte i dashboarden. De ändras i config/*.toml via pull request som den andra grundaren granskar. Dashboarden visar dem bara.
4. Simulerade pengar märks alltid "SIM". Läget syns överst på varje sida.

## 2. Sidorna (från designen)

| Sida | Visar | Knappar som fungerar |
|---|---|---|
| Home | Kapital, realiserad nettovinst, skattereserv, reserv, väntande beslut, departement, live-händelser | Pausa agenter, nödstopp |
| Departments | Varje departement som en byggnad, tänt fönster = agent som arbetar | — |
| Department (huset) | Planritning med ett rum per agent, mötesrum (samråd), arkiv (lärdomar), uppgiftskö | Pausa departement, ny uppgift |
| Agent | Status, mandat, prestation, senaste arbete, chatt | Pausa, sätt under prövning, chatta |
| Finance | Från försäljning till nettovinst, vinst per dag, momsgräns, skatt per spår, ledger | Exportera deklarationsunderlag |
| Approvals | Kö + beslutspost med samråd och invändningar | Godkänn, avvisa |
| Risk and rules | Läge, kontrollkedjans blockeringar, gränser, incidenter | — |
| Activity log | Hela audit-loggen med filter, hashkedjan verifierad | Filtrera |
| Settings | Notiser, grundare och godkännanderegler, AI-modeller, åtkomst | Slå av/på notiskanaler |

## 3. Teknikval (förslag D-073)

| Del | Val | Varför |
|---|---|---|
| Webbserver | Pythons http.server (ThreadingHTTPServer) | Standardbibliotek, noll beroenden (D-002) |
| Live-data | Server-Sent Events (/api/stream) | Enkelt, envägs, fungerar i alla webbläsare och på mobil |
| Gränssnitt | Vanlig HTML, CSS och JavaScript, inga ramverk, inget byggsteg | Inget npm, inget som kan gå sönder |
| Typsnitt | Cormorant Garamond (rubriker) och Inter (text), sparade lokalt i repot | Öppna licenser (OFL), fungerar utan internet |
| Inloggning | Åtkomstkod per grundare, sparad som hash i .env | Vet vem som godkände vad |
| Åtkomst | Bara 127.0.0.1 som standard. --lan öppnar för mobiler på samma wifi | Inget nås från internet |
| Mobilnotis | ntfy (gratis app + gratis server) | Gratis push. Skickar bara "Något väntar på dig", aldrig belopp eller detaljer, eftersom ämnet på den publika servern kan läsas av den som vet namnet |
| Mejl | Gmail SMTP med app-lösenord via smtplib | Gratis, standardbibliotek |
| SMS | Nej | Kostar pengar per meddelande. Kräver eget beslut enligt §42 |

Designtokens (kopiera till docs/dashboard/DESIGN.md):
- bakgrund #0E0D0B · sidomeny #12110E · kort #15130F · kantlinje #2A251C
- guld (accent) #C9A24A · ljust guld #E3C77E
- text #EDE6D6 · rubrik #F3ECDC · dämpad text #A39A88
- grön #8FD9A3 på #16301F · gul #EBC870 på #3A2E12 · röd #FFB4AA på #3A1512
- hörn 12px på kort, 8px på knappar · kantlinjer 1px · knappar minst 44px höga
- Gränssnittet är på engelska. Bara mörkt läge.

## 4. Ordningen

Dashboarden kan bara visa riktiga data när motorn finns. Den byggs steg för steg parallellt med motorns faser. För att se något tidigt finns steg D0b: ett skript som fyller testdatabasen med SIM-händelser, tydligt märkt som testdata, som aldrig kan köras mot prod.db.

## 5. Arbetssätt i Claude Code

1. CLAUDE.md i repots rot gäller i varje session.
2. Varje steg: egen gren, plan mode, läs planen, godkänn, bygg.
3. Grundaren kör testkommandot och klickar igenom själv.
4. Pull request, den andra grundaren granskar och mergar. /clear före nästa steg.
5. Pro-gränser delas mellan chatt och Claude Code. Ett steg per session.
6. Sätt aldrig ANTHROPIC_API_KEY.

## 6. Stegen

Varje steg bygger på det som redan finns (se `GAP_ANALYSIS.md`):
- **Ekobyn:** gränssnittet i `docs/dashboard/`.
- **`src/aie/dashboard/export.py`:** vitlistan och `check_public`.
- **`cycle.py`:** den dagliga cykeln.
- **Simuleringen:** `python -m aie simulate`.
- **Idéerna i PR #137:** arbetsfaserna och mötesdeltagarna.

Den nya servern läggs i `src/aie/dashboard/` och inte i ett nytt `src/aie/interfaces/web/`.

### D0 — Förberedelser (klar 2026-11-08 på grenen `dashboard/d0-setup`)
- **Repot:** finns på GitHub.
- **Beslut:** D-073 (teknikval) och D-074–D-080 (svaren på frågorna från D0) är föreslagna.
- **CLAUDE.md** har reglerna.
- **Filer:** `DESIGN.md` och `GAP_ANALYSIS.md` finns, och FR-27 till FR-33 finns i REQUIREMENTS.md.
- **Publicering:** `pages`-jobbet är borttaget ur `company-daily` (D-075).

### D0b — Testdata i SIM (bygger på simuleringen)
**Inget nytt fyllskript.** `python -m aie simulate start --scenario normal --as yorgo` fyller redan en SIM-databas med agenter, ledgerposter, prognoser och blockerade handlingar, genom samma spärrar som alltid. Revisionskedjan är därför giltig.

`scripts/seed_sim.py` blir ett tunt skal:
1. Det kör ett scenario i 30 dagar.
2. Det lägger 3 väntande godkännanden via kärnans kö (`EscalationQueue.submit_*`).
3. Det skriver ut sökvägen.

Det vägrar köra om miljön inte är `sim` eller valutan inte är `SIM`, med samma kontroll som simuleringen (`require_sim`).

**Avvikelse från originalet:** "14 agenter i 8 departement" ändras till de roller och departement som finns i `config/permissions.toml` (6 departement). Fler departement kräver en ändring i den skyddade filen.

**Tester:** skriptet vägrar prod, och `AuditLog.verify()` är OK efteråt.

### D1 — Server, inloggning och sidomeny
- **Servern:** `src/aie/dashboard/server.py` med `ThreadingHTTPServer` och kommandot `python -m aie dashboard`. Den startar på `127.0.0.1:8765`, och `--lan` binder till alla nätverkskort.
- **Gränssnittet:** statiska filer i `src/aie/dashboard/web/`. De serveras av servern och ligger inte i det publika `docs/`.
- **Inloggning:**
  - en åtkomstkod per grundare, som hash i `.env` och aldrig i git
  - sessionscookie med HttpOnly och SameSite=Strict
  - CSRF-token på alla POST
- **Det delade skalet** följer `DESIGN.md`:
  - sidomeny
  - Live-indikator och etiketten SIM eller REAL
  - klocka och inloggad grundare
  - Pause agents och Kill switch, inaktiva tills D5
- **Typsnitten** Cormorant Garamond och Inter läggs i `assets/fonts/`, med OFL-licensen bredvid.
- **Återanvänds:**
  - Ekobyns byggfria struktur, `validate()` och hantering av reducerad rörelse
  - `node --test` för gränssnittet
- **Tester:**
  - fel kod nekas
  - POST utan CSRF nekas
  - servern lyssnar bara på 127.0.0.1 utan `--lan`
  - `.env` läses men skrivs aldrig ut

### D2 — Live-händelser och Activity log
- **Strömmen:** `/api/stream` (SSE) skickar nya rader från revisionsloggen inom 2 sekunder.
  - Raderna tvättas med samma vitlista och `check_public` som `export.py`.
  - Det som visas för en agent använder `export.ACTIVITY`, alltså samma generiska aktivitetstext som i Ekobyn.
- **Agentens arbetsläge** följer idén i PR #137: `PHASES` för tänker, kontrollerar, hämtar, klar, blockerad och väntar, plus mötesdeltagarna. Läget räknas ur revisionsloggen och skrivs inte till en publik fil (D-079).
- **Activity log:** filter för Blocked, Money, Decisions, Agents och System. Kedjans status kommer från `AuditLog.verify()`.
- **Home** får Live activity med de 6 senaste händelserna.
- **Bruten ström:** visar "Offline" och återansluter.
- **Tester:**
  - en ny rad i revisionsloggen når klienten
  - en manipulerad rad visar att kedjan är bruten
  - inga fält utanför vitlistan går ut

### D3 — Departement, huset och agenter
- **Departments och Department (huset):** bygger vidare på Ekobyns hus, ett per departement, och agenternas förnamn från `export.ensure_names`. Husen ritas om med tokens från `DESIGN.md`.
  - **Tänt fönster:** en agent som är `ACTIVE` med en pågående uppgift (`TaskBoard`).
  - **Mötesrummet:** pågående samråd (`ConsultationBoard`).
  - **Arkivet:** lärdomar (`LessonRegistry`).
- **Agent:**
  - status och livscykel (`AgentRegistry`)
  - mandat från `config/permissions.toml`
  - prestation (`PerformanceReview`)
  - senaste arbete
- **Data:** via GET-endpoints. Statusarna uppdateras live via `/api/stream`.
- **Bara läsning.**
- **Ekobyn tas bort** först när D3 är klar, och bara med ett eget beslut.

### D4 — Godkännanden
- **Approvals** samlar tre köer som redan finns, var och en via sina kärnfunktioner:
  - grundarnas kö (`EscalationQueue.pending/approve/reject`, samma som `python -m aie approvals`)
  - utgiftsgodkännanden (`SpendApprovals`, samma som `python -m aie spend`)
  - bedömningar (`AssessmentStore`, samma som `python -m aie assess`)
- **Beslutsposten** visar mål, belopp, riskklass, största förlust, samrådsyttranden och oenigheter (`DisputeBoard`).
- **Beslutsfattare** är den inloggade grundaren.
- **"Waiting for Robin"** visas bara om regeln kräver båda. Med D-049 räcker en grundare. Q-09 avgör om det ändras.
- **Allt loggas.**
- **Tester:**
  - en agent kan inte godkänna
  - samma grundare kan inte godkänna två gånger
  - ett beslut som kräver båda genomförs inte efter ett enda godkännande

### D5 — Ekonomi, risk, Home och nödstopp
- **Finance** använder kärnans beräkningar, och inget räknas i JavaScript:
  - `compute_result` och `capital_position`, samma som `export._score`
  - momsgränsen och skatten per spår och grundare (`TaxEngine`)
  - ledgern
  - export av deklarationsunderlag (D-034)
- **Risk and rules:**
  - läget (`KillSwitch`, `ProtectedMode`)
  - dagens blockeringar per steg, ur `tool.denied` i revisionsloggen
  - gränserna från `risk_limits.toml` med användning
  - öppna incidenter (`IncidentLog`)
- **Home:** fyra nyckeltal, kapitalfördelning, väntande beslut och departement. "Preliminary" visas där kärnan säger det.
- **Kill switch** kopplas till `KillSwitch.engage`. Det kräver bekräftelse och åtkomstkod. Återstart sker som i dag (`vote_release`).
- **Pause agents:** det finns **ingen kärnfunktion** som pausar alla agenter på en gång i dag. Den byggs i kärnan, som en övergång till `SUSPENDED` med skäl för varje aktiv agent, och anropas sedan av dashboarden.
- **Tester:**
  - API:ets siffror är exakt lika med revisionens omräkning (`recompute`)
  - ett nödstopp stoppar nya transaktioner och raderar inget

### D6 — Chatta med en agent
- **Chatten** på Agent-sidan går via `LLMGateway` och `ProviderRouter` till agentens tillåtna gratismodell.
- **Kontexten** är roll, mandat och senaste uppgifter.
- **Inga verktyg:** chatten kan förklara, men aldrig utföra, godkänna eller ändra gränser.
- **Förslag** sparas som obekräftade hypoteser (§29).
- **Allt loggas.** "Waiting for quota" visas när kvoterna är slut, och då används ingen betald reserv.
- **Tester:**
  - chatten kan inte skapa en åtgärd
  - en slut kvot ger ett tydligt meddelande

### D7 — Notiser
- **Modulen:** `src/aie/notify/` med ntfy, där ämnesnamnet slumpas och sparas i `.env`, och Gmail SMTP med app-lösenord i `.env`.
- **Utlösare** finns redan i kärnan och används:
  - nödstopp eller skyddat läge (`KillSwitch`, `ProtectedMode`)
  - nådd riskgräns (`StopLoss`)
  - blockerad handling (`tool.denied`)
  - ett beslut som väntat mer än 1 timme. Notisen i `QUESTIONS-FOR-FOUNDERS.md` från `cycle.py` återanvänds.
  - slut gratiskvot
- **ntfy** får bara generisk text. Den dagliga sammanfattningen skickas med e-post klockan 21.
- **Högst en notis** per typ var 15:e minut.
- **Settings** slår av och på kanalerna.
- **Tester:** med falska servrar.

### D8 — Mobil och finputs
- **Bredder:** alla sidor fungerar i 390 px och 1440 px.
- **Krav:**
  - ingen vågrät rullning
  - knappar minst 44 px
  - tabeller rullar i en egen ruta
  - kontrast 4,5:1
  - tom vy och felvy på varje sida
- **Checklista** finns i `docs/dashboard/TESTING.md`.

### W — Windows-testerna (egen uppgift, oberoende av D1–D8)
12 tester faller lokalt på Windows men är gröna i CI. Listan finns i `GAP_ANALYSIS.md` avsnitt 5.
- **Trolig orsak:** låsta SQLite-filer vid städning och sökvägar.
- **Varför det spelar roll:** Yorgo kör Windows, och utan en grön svit lokalt syns nya fel dåligt.
- **Uppgiften** står i `TODO.md`.

## 7. Risker
- Dashboarden kan inte visa riktiga siffror före motorn; fram till dess SIM-data.
- Ett lokalt system sover när datorn sover. Server tas i Q-07 före pilot.
- ntfy:s publika server är inte privat, därför inga detaljer dit.
- LAN-läget gör dashboarden nåbar för alla på samma wifi med koden. Bara hemma.

## 8. Öppna frågor
| ID | Fråga |
|---|---|
| Q-09 | Godkänner ni regeln: en grundare räcker för kod, simulering och riskklass 1; båda krävs för riktiga pengar, gränser, nya kanaler och när agenter är oense? (Obs: i dag gäller D-049, där en grundare räcker överallt; regeln kräver ett nytt beslut.) |
| Q-10 | Vem bygger vilka steg? Förslag: Yorgo D1, D2, D4; Robin D3, D5; sedan växlar ni. |
