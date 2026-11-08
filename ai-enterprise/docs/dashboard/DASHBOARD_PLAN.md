# DASHBOARD_PLAN — kommandocentralen

**Skapad:** 2026-11-08 av Claude (session med Yorgo) · **Status:** Förslag, kräver beslut D-013
**Design:** designytan "AI-Ecosystem — startsida" i Yorgos Claude-konto (10 sidor, klickbar prototyp)

## 1. Vad dashboarden är

Dashboarden är systemets ögon och knappar för er två. Den ersätter Robins tidigare animerade värld. I arkitekturen är den två av komponenterna i §39: Monitoring (se allt) och Human Approval Interface (godkänna, pausa, stoppa).

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

## 3. Teknikval (förslag D-013)

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

### D0 — Förberedelser
Repot finns på GitHub, beslutet D-013 är föreslaget, CLAUDE.md har regler, DESIGN.md finns, krav FR-27 till FR-33 finns.

### D0b — Testdata i SIM
scripts/seed_sim.py fyller data/sim.db med realistiska SIM-händelser: 14 agenter i 8 departement, ledgerposter för 30 dagar, några blockerade handlingar, 3 väntande godkännanden. Vägrar köra om databasens miljö inte är "sim". Tester: vägrar prod, audit-kedjan giltig efteråt.

### D1 — Server, inloggning och sidomeny
src/aie/interfaces/web/ med ThreadingHTTPServer. python -m aie dashboard startar på 127.0.0.1:8765; --lan binder till alla nätverkskort. Åtkomstkod per grundare (hash i .env, aldrig i git), sessionscookie HttpOnly och SameSite=Strict, CSRF-token på alla POST. Delat skal: sidomeny, rubrikrad med Live-indikator, SIM-etikett, klocka, knapparna Pause agents och Kill switch (inaktiva tills D5). Följ DESIGN.md. Fungerar i mobilbredd. Tester: fel kod nekas, POST utan CSRF nekas, servern lyssnar bara på 127.0.0.1 utan --lan.

### D2 — Live-händelser och Activity log
/api/stream (SSE) skickar nya rader från audit-loggen inom 2 sekunder. Sidan Activity log med filter (Blocked, Money, Decisions, Agents, System) och indikator för verifierad hashkedja, beräknad av kärnans audit-modul. Home får Live activity med de 6 senaste. Bruten ström visar "Offline" och återansluter. Tester: ny audit-rad når klient, manipulerad rad gör att indikatorn visar fel.

### D3 — Departement, huset och agenter
Departments (en byggnad per departement, tänt fönster per agent som är ACTIVE med pågående uppgift), Department (planritning med ett rum per agent, mötesrum med pågående samråd, arkiv med lärdomar, uppgiftskö) och Agent (status, livscykel, mandat från config/permissions.toml, prestation, senaste arbete). Data via GET-endpoints, statusar live via /api/stream. Bara läsning.

### D4 — Godkännanden
Approvals: kön från kärnans godkännandekö. Beslutsposten visar mål, belopp, riskklass, max förlust, samrådsyttranden och oenigheter med det omtvistade påståendet. Approve och Reject anropar samma funktioner som CLI-kommandona, med inloggad grundare som beslutsfattare. Kräver regeln båda grundarna visas "Waiting for Robin" efter första godkännandet. Allt loggas. Tester: agent kan inte godkänna, samma grundare kan inte godkänna två gånger, beslut som kräver båda genomförs inte efter ett godkännande.

### D5 — Ekonomi, risk, Home och nödstopp
Finance (från försäljning till nettovinst, nettovinst per dag, momsgräns, skatt per spår och grundare, ledger med export av deklarationsunderlag), Risk and rules (läge, blockeringar per steg i kontrollkedjan idag, gränser från risk_limits.toml med användning, öppna incidenter) och Home (fyra nyckeltal, kapitalfördelning, väntande beslut, departement). Alla siffror från kärnans beräkningar, aldrig i JavaScript. "Preliminary" där kärnan säger det. Pause agents och Kill switch kopplas till kärnan; nödstopp kräver bekräftelse och åtkomstkod. Tester: API-siffror exakt lika Audit-agentens återberäkning, nödstopp stoppar nya transaktioner och raderar inget.

### D6 — Chatta med en agent
Chatt på Agent-sidan via ProviderRouter till agentens tillåtna gratismodell. Kontext: roll, mandat, senaste uppgifter. Inga verktyg: chatten kan förklara, aldrig utföra, godkänna eller ändra gränser. Förslag sparas som obekräftade hypoteser. Allt loggas. "Waiting for quota" om kvoterna är slut. Tester: chatt kan inte skapa en ActionRequest, slut kvot ger tydligt meddelande.

### D7 — Notiser
src/aie/notify/ med ntfy (slumpat ämnesnamn från .env) och Gmail SMTP (app-lösenord i .env). Utlösare: nödstopp eller skyddat läge, nådd riskgräns, blockerad handling, beslut som väntat mer än 1 timme, slut gratiskvot. ntfy får bara generisk text, aldrig belopp eller namn. Daglig mejlsammanfattning kl. 21. Max en notis per typ var 15:e minut. Settings visar och slår av/på kanaler. Tester med falska servrar.

### D8 — Mobil och finputs
Alla sidor i 390 px och 1440 px bredd. Ingen vågrät rullning, knappar minst 44 px, tabeller rullar i egen ruta, kontrast 4,5:1, tom-vy och fel-vy på varje sida. Checklista i docs/dashboard/TESTING.md.

## 7. Risker
- Dashboarden kan inte visa riktiga siffror före motorn; fram till dess SIM-data.
- Ett lokalt system sover när datorn sover. Server tas i Q-07 före pilot.
- ntfy:s publika server är inte privat, därför inga detaljer dit.
- LAN-läget gör dashboarden nåbar för alla på samma wifi med koden. Bara hemma.

## 8. Öppna frågor
| ID | Fråga |
|---|---|
| Q-09 | Godkänner ni regeln: en grundare räcker för kod, simulering och riskklass 1; båda krävs för riktiga pengar, gränser, nya kanaler och när agenter är oense? |
| Q-10 | Vem bygger vilka steg? Förslag: Yorgo D1, D2, D4; Robin D3, D5; sedan växlar ni. |
