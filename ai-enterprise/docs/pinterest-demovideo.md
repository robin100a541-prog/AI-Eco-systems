# Manus och checklista: demovideon som Pinterest kräver för Standard-åtkomst

Pinterest granskar en skärminspelning innan appen får Standard-åtkomst. Källa: developers.pinterest.com, avsnittet
"access tiers", läst 2026-11-04. Pinterest vill se två saker:
- att användaren går igenom **OAuth-flödet**, med inloggning på Pinterests egen sida
- att appen gör en riktig åtgärd med API:t, i vårt fall att skapa en pin

Videon krävs även för en app med en enda användare. Den vanligaste orsaken till nej är att inloggningen inte syns.
Pinterest godtar en inspelning av terminalen.

**Grundaren spelar in videon.** Claude skapar inga konton och hanterar inga nycklar.

## Förberedelser (en gång)
1. [ ] Pinterest-kontot är ett **företagskonto**, se `setup-konton.md` steg 4.
2. [ ] Appen är skapad och har **Trial-åtkomst**. Under Trial syns pins bara för dig själv (sandbox). Det räcker för videon.
3. [ ] Två sidor är publicerade, med länkarna i appens inställningar:
   - integritetspolicyn: https://robin100a541-prog.github.io/AI-Eco-systems/privacy.html
   - appbeskrivningen: https://robin100a541-prog.github.io/AI-Eco-systems/app.html
4. [ ] Redirect-adressen `http://127.0.0.1:8765/callback` är registrerad i appen.
5. [ ] Miljövariablerna `PINTEREST_APP_ID` och `PINTEREST_APP_SECRET` är satta i terminalen. **Visa dem aldrig i bild**, och sätt dem före inspelningen.
6. [ ] `[pinterest] enabled = true` är satt i en lokal kopia av `config/pod.toml`, bara för inspelningen.
7. [ ] Det finns en tavla för testpinnar och en publik bild, till exempel ett av utkasten i `products/q4/`.
8. [ ] Stäng allt annat på skärmen: e-post, andra flikar och lösenordshanterare.

## Manus (2–3 minuter)
| # | Visa | Säg eller skriv i bild |
|---|---|---|
| 1 | Appbeskrivningen `app.html` | "AI Eco Systems publishes Pins for our own Etsy products. Only the two founders use it." |
| 2 | Terminalen: `python -m aie connect pinterest` | "The app starts Pinterest's OAuth flow." |
| 3 | Webbläsaren öppnar **Pinterests** inloggningssida. Logga in och visa adressfältet (pinterest.com) | "Login happens on Pinterest. The app never sees the password." |
| 4 | Pinterests medgivandesida med scopes. Klicka på godkänn | "We request boards:read, pins:read, pins:write and user_accounts:read." |
| 5 | Webbläsaren visar "Kontot är kopplat". Terminalen visar sökvägen till token-filen, **inte** själva token | "The token is stored outside the code and readable only by this user." |
| 6 | Terminalen: skapa en pin med `PinterestPinner.pin(...)` (kommando i avsnittet nedan) | "Now the app creates one Pin with our own image and a link to our Etsy listing." |
| 7 | Pinterest i webbläsaren: den nya pinnen på tavlan | "Here is the Pin. The app publishes at most 10 Pins per day and logs each one." |
| 8 | Integritetspolicyn `privacy.html` | "Our privacy policy explains what we store: only our own tokens and a log of our own Pins." |

## Kommandot i steg 6
Det här är det enda kodexemplet. Det körs från `ai-enterprise/` med `PYTHONPATH=src` och de verkliga id:na:
```bash
python - <<'PY'
from pathlib import Path
from aie.config import load_config
from aie.memory import Database
from aie.pod.channels import ActionLog, PinterestPinner, pinterest_client
from aie.pod.oauth import TokenStore
from aie.pod.printify import load_pod_config
from aie.simulation.agents import ensure_org
from aie.system import build_system

config = load_config("config")
with Database.open(Path("data-demo"), "sim") as db:
    system = build_system(config, db, "config")
    ensure_org(system.registry, "yorgo")
    pod = load_pod_config("config")
    pinner = PinterestPinner(system.engine, system.audit, "lead-1", pod,
                             pinterest_client(TokenStore().access_token("pinterest")), ActionLog(db))
    print(pinner.pin("<TAVLANS-ID>", "<titel>", "<beskrivning>", "https://www.etsy.com/listing/<ID>", "https://<publik-bild>.png"))
PY
```
Det kräver att PR:en med verktygen i `permissions.toml` är sammanslagen, och att D-069 är godkänt.

## Efter inspelningen
1. [ ] Titta igenom videon. Ingen nyckel, token, kod ur adressfältet eller e-post får synas.
2. [ ] Ladda upp videon där Pinterest anger vid uppgraderingen, under My apps och sedan Upgrade.
3. [ ] Sätt tillbaka `enabled = false` i den lokala kopian, tills D-069 är godkänt i repot.
4. [ ] Skriv datum och utfall i `docs/QUESTIONS-FOR-FOUNDERS.md` eller i `setup-konton.md`.
