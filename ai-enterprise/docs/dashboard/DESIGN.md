# DESIGN: kommandocentralen

- **Källa:** `DASHBOARD_PLAN.md` avsnitt 2 och 3, och designytan "AI-Ecosystem — startsida" i Yorgos Claude-konto. Det är en klickbar prototyp med 10 sidor, och den finns inte i repot.
- **Beslut:** D-073 (teknikval), föreslaget.
- **Språk:** gränssnittet är på engelska. Bara mörkt läge.

## Designtokens
Tokens definieras en gång som CSS-variabler i `:root` och används överallt. Inga färger hårdkodas i komponenterna.

| Token | Värde | Används till |
|---|---|---|
| `--bg` | `#0E0D0B` | sidans bakgrund |
| `--sidebar` | `#12110E` | sidomenyn |
| `--card` | `#15130F` | kort och paneler |
| `--line` | `#2A251C` | kantlinjer (1px) |
| `--gold` | `#C9A24A` | accent: aktiv menypunkt, primärknapp, fokus |
| `--gold-light` | `#E3C77E` | hover på accent, viktiga siffror |
| `--text` | `#EDE6D6` | brödtext |
| `--heading` | `#F3ECDC` | rubriker |
| `--muted` | `#A39A88` | dämpad text, etiketter och tidsstämplar |
| `--ok-fg` / `--ok-bg` | `#8FD9A3` / `#16301F` | grönt läge: aktiv, godkänd, kedjan verifierad |
| `--warn-fg` / `--warn-bg` | `#EBC870` / `#3A2E12` | gult läge: väntar, preliminärt, SIM |
| `--bad-fg` / `--bad-bg` | `#FFB4AA` / `#3A1512` | rött läge: blockerad, nödstopp, kedjan bruten |

| Form | Värde |
|---|---|
| Hörn på kort | 12px |
| Hörn på knappar | 8px |
| Kantlinjer | 1px `--line` |
| Knappar | minst 44px höga (pekskärm) |
| Kontrast | minst 4,5:1 för text mot bakgrund (D8) |

**Typsnitt:**
- **Cormorant Garamond** används för rubriker och **Inter** för text.
- Båda har SIL Open Font License och sparas i `assets/fonts/` med licensen. Inget laddas från internet (D-073).
- Typsnitten finns sedan D1 i `src/aie/dashboard/web/fonts/`: Cormorant Garamond 500 och 600, och Inter 400, 500 och 600, som woff2 med licensfilerna `OFL-*.txt`.

**Statusfärgerna har alltid text bredvid,** till exempel "Blocked" och "SIM". Färgen är aldrig enda bäraren av information.

## Sidorna
| Sida | Visar | Knappar | Steg |
|---|---|---|---|
| Home | kapital, realiserad nettovinst, skattereserv, reserv, väntande beslut, departement och live-händelser | Pause agents, Kill switch | D2, D5 |
| Departments | varje departement som en byggnad; ett tänt fönster är en agent som arbetar | — | D3 |
| Department (huset) | planritning med ett rum per agent, mötesrum (samråd), arkiv (lärdomar) och uppgiftskö | Pause department, New task | D3 |
| Agent | status, mandat, prestation, senaste arbete och chatt | Pause, Put on probation, Chat | D3, D6 |
| Finance | från försäljning till nettovinst, vinst per dag, momsgräns, skatt per spår och ledger | Export tax basis | D5 |
| Approvals | kön och beslutsposten med samråd och invändningar | Approve, Reject | D4 |
| Risk and rules | läge, kontrollkedjans blockeringar, gränser och incidenter | — | D5 |
| Activity log | hela revisionsloggen med filter och verifierad hashkedja | Filter | D2 |
| Settings | notiser, grundare och godkännanderegler, AI-modeller och åtkomst | slå av och på notiskanaler | D7 |

## Delat skal (D1)
Varje sida har samma skal:
- **sidomeny** med sidorna ovan
- **rubrikrad** med Live- eller Offline-indikator, etiketten **SIM** eller **REAL**, klocka och inloggad grundare
- **knapparna Pause agents och Kill switch,** som är inaktiva tills D5

I mobilbredd (390 px) fälls sidomenyn ihop till en meny.

## Rörelse (D-084)
Rörelsen ska kännas lugn och precis. Den görs med GSAP, och Lenis används för scrollen. Filerna och licenserna står i `src/aie/dashboard/web/vendor/README.md`.

| Rörelse | Hur | Tid | Kurva |
|---|---|---|---|
| Panelernas inträde | rubriken och korten tonar in och stiger 8 px, med 0,05 s mellan dem | 0,35 s | `power2.out` |
| Sidövergång | innehållet tonar ut 4 px uppåt innan nästa sida laddas, och sedan in som ovan | 0,15 s ut | `power1.out` |
| Uppräknande siffror (CountUp) | räknar från 0 till slutvärdet en gång när siffran syns. Slutvärdet finns i HTML och för skärmläsare | 0,6–1,1 s | `power3.out` |
| Statusbyte (Live/Offline) | punkten krymper från 1,8 till 1 och färgen glider över | 0,25–0,35 s | `power2.out` |
| Live-flödet (AnimatedList) | nya rader tonar in med 4 px, och listan när sidan laddas med 0,05 s mellan raderna | 0,3 s | `power2.out` |
| Spotlight | mjukt guldljus under pekaren och upplyst kant, bara med mus. Används på väntande godkännanden och i D3 på agentkorten | 0,25 s | `power2.out` |
| Radarn | byggs inte än. När den finns används samma regler | — | — |

**Regler:**
- **Mening:** inget rör sig utan att betyda något, och inget går i slinga.
- **Kurvan:** bara ease-out, aldrig studs, fjäder eller `back`.
- **`prefers-reduced-motion`:** då visas slutläget direkt, Lenis är av och spotlight-ljuset följer inte pekaren.
- **Lenis:**
  - **På:** bara på desktop med mus, från 768 px.
  - **Av:** på touch.
  - **Aldrig i** `table`, `dialog`, `.chat`, `.scroll-panel` eller element med `data-lenis-prevent`.
- **Innehållet syns alltid:**
  - **Före första målningen:** `boot.js` döljer innehållet bara om rörelse är tillåten.
  - **Om animationen aldrig startar:** CSS visar allt efter 1,2 s, och en timer hoppar till slutet.
  - **Siffror:** en siffra ändras först när animationen faktiskt går, så ett fel värde visas aldrig.

## Det som återanvänds från Ekobyn
Se `GAP_ANALYSIS.md`:
- **Byggfri struktur:** inget npm, och `node --test` för gränssnittet.
- **Validering av data** innan den visas (`validate()` i `world.js`), och den senaste giltiga ögonblicksbilden behålls vid fel.
- **Reducerad rörelse** respekteras.
- **Husen och agenterna** i Ekobyn är förlagan till Departments och Department (huset) i D3, men med tokens från den här filen.
