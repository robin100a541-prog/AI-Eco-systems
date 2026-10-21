# ARCHITECTURE — AI Enterprise System

Version: 0.1 (Fas 0, förslag) · Status: **Föreslagen — väntar på grundarnas godkännande (se DECISIONS.md)**

## 1. Grundidé

Systemet byggs som en **lokal Python-applikation med en deterministisk kärna** och en utbytbar "hjärna".

- **Kärnan** (behörigheter, budget, ledger, risk, revision, livscykel, nödstopp) är vanlig kod med tester. Den fattar inga kreativa beslut, men den *tillåter eller blockerar* alla handlingar. Detta uppfyller §35: reglerna upprätthålls av programvaran, inte av en prompt.
- **Agenternas resonerande** (analys, förslag, yttranden) kommer från en utbytbar `ReasoningProvider`. Kärnan behandlar allt som en provider returnerar som ett *förslag* som måste passera Authorization → Budget → Risk innan något händer.

```
           ┌──────────────── Grundare (Yorgo, Robin) ────────────────┐
           │      CLI: start / stop / status / approve / kill        │
           └───────────────────────────┬─────────────────────────────┘
                                       │ Human Approval Interface
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ ORCHESTRATOR  (uppgifter, hierarki, eskalering, samråd)                      │
│    │ förslag från agenter                                                    │
│    ▼                                                                         │
│ AGENT RUNTIME ──► ReasoningProvider  (rule | manual | claude-code | local)   │
│    │ "jag vill göra X"                                                       │
│    ▼                                                                         │
│ ┌─────────── KONTROLLKEDJA (obligatorisk, i denna ordning) ───────────────┐  │
│ │ KillSwitch/Mode → Authorization → Budget → Risk → (HumanApproval)       │  │
│ └───────────────────────────────┬─────────────────────────────────────────┘  │
│                                 ▼ tillåten                                   │
│                          TOOL GATEWAY (enda vägen ut)                        │
│                                 │                                            │
│ LEDGER · DECISIONS · MEMORY · EVALUATION · AUDIT LOG · MONITORING            │
│                     └──────── SQLite (en fil) ────────┘                      │
└──────────────────────────────────────────────────────────────────────────────┘
          CONFIGURATION: config/*.toml (versionerad i git, validerad vid start)
```

Viktigaste designregeln: **agenter har inga direkta verktyg.** De returnerar strukturerade `ActionRequest`-objekt. Endast Tool Gateway utför handlingar, och bara efter att kontrollkedjan sagt ja. Varje steg skrivs till audit-loggen.

## 2. Komponenter (§39) → moduler

| Komponent | Modul | Ansvar | Fas |
|---|---|---|---|
| Configuration System | `src/aie/config/` | Läser `config/*.toml`, validerar, vägrar starta vid fel. Versionsfält. | 1 |
| Memory System | `src/aie/memory/` | SQLite-åtkomst, migrationer, beständiga register. | 1 |
| Audit System | `src/aie/audit/` | Append-only händelselogg med hashkedja (varje rad innehåller hash av föregående → manipulering syns). | 1 |
| Monitoring | `src/aie/monitoring/` | Strukturerad loggning (JSON-rader), räknare, loopdetektering. | 1 / 6 |
| Agent Runtime | `src/aie/agents/` | Agentregister, mandat, livscykel, körning via provider. | 2 |
| Authorization Engine | `src/aie/authorization/` | Default deny. Kontrollerar roll + verktyg + mandat. | 2 |
| Orchestrator | `src/aie/orchestration/` | Uppgifter, tilldelning, hierarki, eskalering. | 2–3 |
| Decision Engine | `src/aie/decisions/` | 11-stegs beslutspost, samråd, oenighet. | 3 |
| Ledger | `src/aie/ledger/` | Dubbel bokföring light: append-only poster, korrigeringsposter, idempotens. | 4 |
| Budget Engine | `src/aie/budget/` | Disponibelt kapital, reserv, departementsbudgetar, uppdelningsdetektering. | 4 |
| Risk Engine | `src/aie/risk/` | Riskklass, stop-loss, skyddat driftläge. | 4 |
| Human Approval Interface | `src/aie/interfaces/approval.py` | CLI-kö för godkännanden. | 3–4 |
| Evaluation Engine | `src/aie/evaluation/` | Prognos vs utfall, prestationsmått, lärdomsregister. | 5 |

## 3. Teknikval

### 3.1 Språk och körmiljö

**Python ≥ 3.11**, endast standardbiblioteket i MVP.

Motivering: gratis (PSF-licens), finns på Windows/macOS/Linux, och standardbiblioteket täcker allt MVP behöver: `sqlite3` (lagring), `tomllib` (läsa konfiguration, finns från 3.11), `decimal` (exakta belopp), `logging`, `unittest` (tester), `hashlib`, `uuid`, `argparse`. Noll tredjepartsberoenden betyder noll licensrisk och ingen installation som kan gå sönder på en av grundarnas datorer.

### 3.2 Verktygsregister (krav DR-02)

Status: ✅ verifierad · 🟡 ska verifieras av grundarna · ⛔ inte tillåten utan beslut

| Verktyg | Syfte | Licens | Kostnad | Status / anmärkning |
|---|---|---|---|---|
| Python 3.11+ | Körmiljö | PSF License (öppen) | 0 kr | ✅ Standardbibliotek räcker för MVP |
| SQLite (via `sqlite3`) | Beständig lagring | Public domain | 0 kr | ✅ Ingår i Python. En fil, ingen server. |
| Git | Versionshantering | GPLv2 | 0 kr | 🟡 Finns ev. redan; kontrolleras av `check_env.py` |
| GitHub Free | Delat privat repo | Tjänstevillkor | 0 kr | ✅ Gratisplanen tillåter obegränsade privata repon med obegränsat antal medarbetare och 2 000 Actions-minuter/mån för privata repon (källa nedan). Privata repon har en begränsad funktionsuppsättning. |
| Claude Pro (×2) | Utvecklingsstöd i chatt och Claude Code | Anthropic villkor | Befintlig | ✅ Pro täcker Claude Code i terminal/IDE. ⚠️ Se 3.3. |
| unittest | Tester | PSF | 0 kr | ✅ Standardbibliotek |
| pytest | Bekvämare tester | MIT (ej verifierat i Fas 0) | 0 kr | Valfritt senare; licens kontrolleras innan införande |
| Ollama | Lokal LLM-provider | MIT | 0 kr (egen hårdvara/el) | ✅ Verktyget. Varje modells licens kontrolleras separat. |
| Groq gratisplan | Extern gratis LLM | Tjänstevillkor | 0 kr inom gratisgränser | 🟡 Villkor för dataanvändning läses innan aktivering |
| OpenRouter `:free` | Extern gratis LLM | Tjänstevillkor | 0 kr för `:free`-modeller | 🟡 Samma; skriptet vägrar modeller utan `:free` |
| Anthropic API och andra betalda API:er | Programmatisk LLM | Kommersiell | **Betald** | ⛔ Endast via D-009 (finansierat av realiserad vinst) |
| Molnhosting, betalda API:er | — | — | Betalt | ⛔ Kräver uttryckligt grundarbeslut |

### 3.3 Modellåtkomst — den viktigaste begränsningen (krav DR-03)

Verifierat 2026-10-21 mot Anthropics supportartikel:

- Pro inkluderar Claude Code, men **API-användning faktureras separat** och Pro innehåller inga API-krediter.
- Användningsgränserna (femtimmarsfönster + veckogräns) **delas mellan claude.ai och Claude Code**.
- Om miljövariabeln `ANTHROPIC_API_KEY` är satt använder Claude Code den nyckeln och debiterar API-pris i stället för abonnemanget.

Konsekvens: Claude används för att **bygga** systemet. Agenterna **i** systemet drivs av gratis språkmodeller (beslut D-008).

#### Gratis modeller (verifierat 2026-10-21 mot leverantörernas dokumentation)

| Provider | Modeller (exempel) | Gratisgräns | Roll |
|---|---|---|---|
| `groq` | `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` | Tabellen visar 30 anrop/min, ~1 000/dag, 200 000 tokens/dag per modell; exakta gratisgränser visas i kontot | Primär |
| `openrouter` | modeller som slutar på `:free` | 20 anrop/min; 50/dag (1 000/dag först efter köp av krediter — kräver beslut) | Sekundär |
| `ollama` | valfri öppen modell ni laddar ner | Obegränsat; begränsas av RAM/GPU. Ollama är MIT-licensierat; **varje modell har egen licens som kontrolleras** | Lokal reserv, och för känsliga data |
| `gemini` | Flash-modeller | Kraftigt sänkt (~20/dag rapporterat sedan dec 2025); Google beskriver nivån som avsedd för tidig testning | Endast tillägg |
| `rule` | Deterministisk Python | Obegränsat | Tester och simulering, alltid reproducerbar |
| `paid:*` | Betalda API:er | Kostar pengar | **0 kr tills realiserad vinst finns** (D-009) |

Alla gratisleverantörer stöder samma OpenAI-kompatibla chattformat, så en enda klient i standardbiblioteket räcker. Verifieras på grundarnas datorer med `scripts/llm_smoke_test.py`.

#### ProviderRouter (Fas 2)
- Varje agentroll har en lista med tillåtna leverantörer/modeller i `config/permissions.toml`.
- Dagskvoter räknas i databasen. När en kvot tar slut går anropet till nästa leverantör; när alla är slut **köas** uppgiften (ingen betald fallback).
- Varje anrop loggas: leverantör, modell, tokens, latens, kostnad (0 kr eller faktisk).
- Dataklassning: `public` får gå till externa gratis-API:er; `internal`/`personal`/`secret` får bara gå till `ollama` eller `rule`.
- Modellsvar är alltid **förslag**. De passerar kontrollkedjan som allt annat.

#### Uppgradering till betalda API:er (D-009)
Budgetkategorin `API_SPEND` är spärrad på 0 kr tills ledgern visar realiserad nettovinst efter reserverad skatt. Därefter kan en del av vinsten (`API_REINVEST_SHARE`) användas, via affärsförslag + CFO/CRO-yttrande + grundargodkännande över tröskeln. Routern lägger då till `paid:*`-leverantören med hård månadsgräns.

### 3.4b Skatt (D-010)
En **Tax Engine** (Fas 4) märker varje intäkt med ett skattespår (ISK, egenanställning, enkelt bolag, hobby), reserverar beräknad skatt som ett åtagande innan kapital blir disponibelt, bevakar momsgränsen, arkiverar underlag i 7 år och genererar underlag till varje grundares deklaration. Ledgern byggs med verifikationsnummer, datum, belopp, motpart och underlag för att kunna fungera som bokföring i spår C.

`check_env.py` varnar om `ANTHROPIC_API_KEY` är satt, eftersom det tyst skulle byta till betald fakturering.

### 3.4 Lagring

En SQLite-fil per miljö: `data/sim.db` (simulering/test) och senare `data/prod.db`. Miljön sätts i `config/system.toml` och skrivs in i databasens metadatatabell; systemet vägrar starta om de inte matchar (SR-11). `data/*.db` är gitignorerat — databasen är *driftdata*, inte källkod. Delning av driftdata mellan grundarna löses i Fas 7 (se öppen fråga Q-07).

Belopp lagras som heltal i minsta enhet (öre/cent) + valutakod, och räknas med `Decimal` (ER-01). Simulerade belopp använder valutakoden `SIM` så att de aldrig kan summeras med SEK/EUR (ER-15).

### 3.5 Konfiguration

`config/system.toml`, `config/budgets.toml`, `config/permissions.toml`, `config/risk_limits.toml` (TOML i stället för YAML: läses av standardbiblioteket). Alla §25-parametrar finns i `risk_limits.toml`; ett saknat värde betyder "blockera", aldrig "obegränsat" (ER-02).

### 3.6 Gränssnitt mot grundarna

Ett kommandoradsverktyg: `python -m aie <kommando>` — `init`, `start`, `stop`, `status`, `report`, `approvals`, `approve <id>`, `reject <id>`, `kill`, `resume`. Inget webbgränssnitt i MVP (ingen hosting behövs).

## 4. Minsta fungerande version (MVP = Fas 1–4 i simulerat läge)

MVP är **inte** ett vinstbringande företag. MVP bevisar att skyddsräcket fungerar innan någon "intelligens" kopplas på.

MVP kan:
1. Startas/stoppas, läser och validerar konfiguration, överlever omstart.
2. Registrera ~6 agenter: CEO, CFO, CRO, Audit, en Research-chef, en Research-arbetsagent — som resonerar med gratis språkmodeller via ProviderRouter (`rule` i automatiska tester).
3. Skapa en uppgift → agent föreslår åtgärd → kontrollkedjan beslutar → audit-loggen visar varför.
4. Föra en ledger i `SIM`-valuta, räkna nettovinst och disponibelt kapital, respektera reserv.
5. Blockera: budgetöverskridande, obehörigt verktyg, uppdelade köp, åtgärd i nödstopp, saknad gräns.
6. Låta Audit återberäkna CFO:s rapport från ledgern och flagga avvikelser.
7. Nödstopp + återstart utan dataförlust.

MVP kan **inte**: röra riktiga pengar eller kontakta andra externa system än gratis språkmodeller (från Fas 2, D-008).

## 5. Delat arbete mellan Yorgo och Robin

Se DECISIONS.md D-004. Kort: ett privat GitHub-repo är enda sanningskällan. Var och en arbetar på en egen gren, öppnar en pull request, den andra granskar. `main` får bara ändras via PR med gröna tester.

## Källor
- [Rate Limits — GroqDocs](https://console.groq.com/docs/rate-limits)
- [API Rate Limits — OpenRouter](https://openrouter.ai/docs/api/reference/limits)
- [Gemini rate limit 20 RPD — Google AI Developers Forum](https://discuss.ai.google.dev/t/gemini-rate-limit-20-rpd/111274)
- [Ollama — pkg.go.dev (licens MIT)](https://pkg.go.dev/github.com/jmorganca/ollama@v0.1.2)
- [Gumroad — Pricing](https://gumroad.com/pricing)
- [Etsy — Creativity Standards](https://etsy.com/legal/creativity)
- [Etsy fees 2026 — Checkout Page](https://checkoutpage.com/blog/etsy-fees)
- [DAC7 — Access Financial](https://accessfinancial.com/sv/ordlista/dac7/)
- [Skatteverket — Hobby](https://skatteverket.se/privat/skatter/arbeteochinkomst/inkomster/hobby)
- [Skatteverket — Vad är näringsverksamhet](https://www.skatteverket.se/foretagorganisationer/foretagare/vadarnaringsverksamhet.4.6efe6285127ab4f1d25800025792.html)
- [Skatteverket — Egenanställning](https://www.skatteverket.se/privat/skatter/arbeteochinkomst/inkomster/egenanstallning)
- [Skatteverket — Enkelt bolag](https://www.skatteverket.se/foretag/drivaforetag/foretagsformer/enkeltbolag.4.6d02084411db6e252fe8000928.html)
- [Skatteverket — Skatt på investeringssparkonto](https://www.skatteverket.se/privat/skatter/vardepapper/investeringssparkontoisk.4.5fc8c94513259a4ba1d800037851.html)
- [Using Claude Code with your Pro or Max plan — Claude Help Center](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- [About GitHub's plans — GitHub Docs](https://docs.github.com/en/get-started/learning-about-github/githubs-plans)
