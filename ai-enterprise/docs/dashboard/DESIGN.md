# DESIGN: Command Center

- **Stil:** mörkt "agentic OS" (uppdraget Command Center 2026-11-09, D-087).
- **Språk:** gränssnittet är på engelska. Bara mörkt läge.
- **Följs exakt:** `ai-enterprise/command-center/assets/css/app.css` definierar varje token en gång i `:root`. Testet `test_css_uses_the_design_tokens_exactly` kontrollerar att värdena nedan finns exakt så i CSS:en.
- **Ersätter** den tidigare designen från D1, med guld och Cormorant Garamond.

## Färger
| Token | Värde | Används till |
|---|---|---|
| `--bg` | `#070B14` | sidans bakgrund, med en svag radial ljuskägla upptill (`--glow`) |
| `--glow` | `rgba(56, 97, 180, 0.20)` | ljuskäglan upptill |
| `--panel` | `rgba(15, 22, 38, 0.72)` | paneler, med `backdrop-filter: blur(14px)` |
| `--line` | `rgba(148, 163, 184, 0.12)` | kantlinjer (1px) |
| `--text` | `#E6EAF2` | text |
| `--muted` | `#8A94A8` | dämpad text |
| `--label` | `#7DB3FF` | etiketter i Geist Mono med versaler |
| `--accent` | `#7DB3FF` | länkar, fokusring och primärknapp |
| `--working` | `#34D399` | status working |
| `--waiting` | `#FBBF24` | status waiting och SIM-etiketten |
| `--idle` | `#64748B` | status idle (pricken) |
| `--failed` | `#F87171` | status failed eller blocked, och nödstopp |
| `--offline` | `#475569` | status offline (pricken) |
| `--idle-text` | `#A3AEC2` | texten i pillerna idle och offline, ljusare så att kontrasten blir minst 4,5:1 |
| `--dept-executive` | `#A78BFA` | CEO och executive: violett |
| `--dept-research` | `#22D3EE` | Research: cyan |
| `--dept-sales` | `#FBBF24` | Sales: bärnsten. Departementet finns inte i config än och visas inte |
| `--dept-engineering` | `#34D399` | Engineering: smaragd. Departementet finns inte i config än och visas inte |
| `--dept-finance` | `#60A5FA` | Finance: blå |
| `--dept-control` | `#F472B6` | kontrollfunktionerna risk, compliance och audit: rosa |

## Form, typografi och rörelse
| Token | Värde | Används till |
|---|---|---|
| `--r-panel` | `16px` | hörn på paneler |
| `--r-card` | `12px` | hörn på kort |
| `--r-btn` | `8px` | hörn på knappar |
| `--s1` | `8px` | 8-punkters rutnät (`--s1` till `--s6` = 8–48 px) |
| `--t` | `200ms` | övergångar (150–250 ms) |

- **Rubriker:** Geist 700 med spärrning `-0.035em`. Stora titlar slutar med punkt, till exempel "Command center.".
- **Etiketter:** Geist Mono, versaler, spärrning `.14em`, 11–12 px, färg `--label`.
- **Siffror:** tabulära (`font-variant-numeric: tabular-nums`).
- **Knappar:** minst 44 px höga, med synlig fokusring (2 px `--accent`). Kontrasten är minst 4,5:1.
- **Typsnitt:** Geist och Geist Mono ligger lokalt i `assets/fonts/` med `OFL-Geist.txt`.
- **Ikoner:** Lucide som lokal SVG-sprite (`assets/icons/lucide-sprite.svg`, ISC, `LICENSE-lucide.txt`).
- **Inget av detta:** emojis, gradienttext och generiska mallkomponenter.

## Status
Status visas alltid som en pill med prick och text, aldrig bara som färg:
- **Färger:** working, waiting, idle, failed eller blocked, och offline.
- **Regeln** för hur status härleds står i `docs/command-center/DATA.md` avsnitt 9.
- **Okänd status** (`unknown`) visas inte.

## Rörelse (D-084, D-087)
- **Längd och kurva:** 150–250 ms med ease-out. Inget studsar.
- **Radarn:** prickarna rör sig långsamt (ett varv på 90–240 s), och aktiva agenter pulserar.
- **Uppräknande siffror:** 250 ms. Slutvärdet står alltid i HTML.
- **Live-flödet:** nya rader tonar in med 4 px.
- **Spotlight:** finns på kort, bara med mus.
- **Lenis:** mjuk huvudscroll, bara på desktop med mus.
- **`prefers-reduced-motion`:** stänger av all animation, radarns rörelse och Lenis.
- **Innehållet** är aldrig beroende av en animation för att synas.

## Skalet
- **Sidomeny:** logotyp, sidorna, och under rubriken **AGENTS** alla agenter med statuspill.
- **Topprad:** verklig systemstatus (normal, protected eller kill switch), "Data as of <tid>", klocka, etiketten SIM eller REAL, inloggad grundare, Pause agents och Kill switch.
- **Banner:** är snapshoten äldre än 26 timmar visas en gul banner: "Data is stale".
- **Mobil (390 px):** menyn blir en utfällbar panel, och sidan rullar aldrig i sidled. Det är kontrollerat på alla tio sidor.

## Sidorna
| Sida | Innehåll |
|---|---|
| Command center | nyckeltal, radar, Current directive, Context window, statsrad i mono, diagram, System health, Chat with an agent och Live activity |
| Agents | nätverksträd: CEO överst, linjer till chefer och agenter. Kontrollfunktionerna streckade, eftersom de rapporterar till grundarna (§8) |
| Departments | ett kort per departement i config, ritat som en byggnad där tända fönster är agenter som arbetar |
| Department | planritning med ett glasrum per agent, mötesrum, arkiv och uppgiftskö |
| Agent | profil, mandat (själv, kräver godkännande, aldrig), prestation, körhistorik, pengar, senaste arbete, kontroller och chatt |
| Approvals | glaskort med filtret In review, Approved och Rejected, detaljvy och knapparna Review och Approve |
| Finance | från brutto till netto, dag, vecka och månad, per agent, moms och skatt, och fliken Transactions |
| Risk and rules | läge, kontrollkedjan med dagens blockeringar, gränser med användning och incidenter |
| Activity | Live och Logs, med filter och verifierad hashkedja |
| Settings | notiskanaler, grundare och regler, modeller och åtkomst. Gränserna ändras aldrig här |

Varje del har en laddningsvy (skeleton), en tomvy och en felvy. Saknad data visas som "N/A".
