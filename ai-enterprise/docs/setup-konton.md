# Konton för print-on-demand: steg för grundarna (arbetsorder 04)

Stegen kan bara grundarna göra, eftersom de skapar konton, godkänner villkor och hanterar nycklar.
Systemet gör inget av det åt er (konstitutionen och D-010). Gör stegen i ordning, och bocka av.

**Nycklar och tokens:**
- De klistras **aldrig** in i en chatt, ett ärende, en fil i repot eller en commit.
- De sätts som GitHub-hemligheter (steg 7) eller som miljövariabler i din egen terminal.
- `python -m aie connect …` sparar dem i `~/.config/aie/tokens/`, utanför repot.

Det som står här är kontrollerat mot tjänsternas dokumentation 2026-11-04, så långt det gick utan konto.
Tjänsterna kan ändra sina formulär. Visar de något annat än det som står här, följ tjänsten och skriv en rad om det här.

## 0. Före allt
1. [ ] Läs och godkänn besluten **D-065–D-069** (`docs/proposals/2026-11-04-*.md`). D-069 avgör vad agenterna får göra själva.
2. [ ] Slå ihop PR:en med verktygen i `config/permissions.toml`. Den har etiketten `kräver-oberoende-granskning`, sätt `founder-approved`. Utan den läser systemet inte ens Printifys katalog.
3. [ ] Kör arbetsflödet **printify-catalog** en gång: Actions, printify-catalog, Run workflow. Kontrollera att sammanfattningen visar katalogen och att artefakten finns.

## 1. Etsy-butik
1. [ ] Gå till etsy.com/sell och skapa en butik med en grundares namn och e-post. En grundare äger kontot (D-010).
2. [ ] Välj butiksspråk, land (Sverige) och valuta.
3. [ ] Lägg in betalning (Etsy Payments) med ett **svenskt bankkonto**. Avgiften blir då 4 % + 3,00 SEK, som i kalkylen. Verifiera identiteten.
4. [ ] Visar Etsy en **engångsavgift för att öppna butiken**, skriv beloppet i `config/registry/platforms.toml` (`setup_minor`) i en PR. Avgiften "varierar per land" enligt Etsy, så vi vet inte beloppet än. Betala bara om ni är överens. Det är den enda kostnaden innan något har sålts.
5. [ ] Läs Etsys regler för AI-innehåll (etsy.com/legal/creativity) och för produktionspartners. Godkänn bara om de tillåter det vi gör.

## 2. Koppla Printify till Etsy
1. [ ] Logga in på printify.com. Kontot finns redan, och nyckeln ligger som `PRINTIFY_API_TOKEN`. Under My stores väljer du Add new store och sedan Etsy, och godkänner kopplingen.
2. [ ] I Etsy: Shop Manager, Settings, **Production partners**. Lägg till Printify som produktionspartner med en kort beskrivning, till exempel "Printify, print-on-demand-tryckeri". Etsy kräver det för print-on-demand. Systemet kontrollerar att varje annons anger Printify.
3. [ ] **Uppgradera inte till Printify Premium** (39 USD/mån). Det är en fast kostnad som kräver ett eget beslut (`costs.break_even_orders` räknar hur många order det kräver).

## 3. Etsy developer-app
1. [ ] Gå till etsy.com/developers/register och skapa en app med en grundares konto. Ange att den är för egen butik (personal access).
2. [ ] Lägg in callback-adressen `https://localhost:8765/callback`. Etsy tar **bara https**. Vid kopplingen kommer webbläsaren att visa ett fel för den adressen, och det är väntat: du kopierar adressen ur adressfältet och klistrar in den.
3. [ ] Notera appens **keystring** och **shared secret**. De sätts tillsammans som `ETSY_API_KEY = keystring:shared_secret`. Etsy kräver båda i rubriken `x-api-key`.
4. [ ] Koppla butiken i din egen terminal, från `ai-enterprise/` med `PYTHONPATH=src`:
   ```bash
   export ETSY_API_KEY="<keystring>:<shared secret>"     # Windows: $env:ETSY_API_KEY="…"
   export ETSY_REDIRECT_URI="https://localhost:8765/callback"
   python -m aie connect etsy
   ```
   Logga in hos Etsy och godkänn. Klistra sedan in adressen från adressfältet. Token sparas utanför repot.
5. [ ] Etsys access token gäller **1 timme** och refresh token 90 dagar. Förnyelsen byggs innan annonser publiceras automatiskt (D-069).

## 4. Pinterest: företagskonto
1. [ ] Skapa ett **företagskonto** (pinterest.com/business/create), eller gör om ett personligt konto i inställningarna.
2. [ ] Skapa en tavla för produkterna, till exempel "Cozy Winter Gifts".

## 5. Pinterest-app, Trial och sedan Standard
1. [ ] Gå till developers.pinterest.com, My apps, och skapa en app. Ange:
   - appbeskrivningen: https://robin100a541-prog.github.io/AI-Eco-systems/app.html
   - integritetspolicyn: https://robin100a541-prog.github.io/AI-Eco-systems/privacy.html

   Båda publiceras med GitHub Pages, se FOUNDER-CHECKLIST steg 7. Kräver Pinterest en e-postadress för kontakt, väljer ni vilken.
2. [ ] Lägg in redirect-adressen `http://127.0.0.1:8765/callback`.
3. [ ] Vänta på **Trial**-åtkomst. Under Trial syns pinnar bara för er själva.
4. [ ] Notera App ID och App secret, som blir `PINTEREST_APP_ID` och `PINTEREST_APP_SECRET`. Koppla sedan:
   ```bash
   python -m aie connect pinterest
   ```
5. [ ] Spela in demovideon enligt `docs/pinterest-demovideo.md`, och begär **Standard** under My apps, Upgrade.
6. [ ] Obs: **Trends API** riktar sig till byråer, enterprise och partner. Får vi inte tillgång, används Etsys signaler i stället, och det är ingen blockerare.

## 6. Instagram: Professional-konto och Meta-app
1. [ ] Gör Instagram-kontot till ett **Professional**-konto (Business), i appens inställningar.
2. [ ] Gå till developers.facebook.com och skapa en app av typen Business. Lägg till produkten **Instagram API with Instagram Login**.
3. [ ] Lägg till ert Instagram-konto som testare eller administratör i appen. Då fungerar publicering i utvecklingsläget för det egna kontot.
4. [ ] Behörigheter: `instagram_business_basic` och `instagram_business_content_publish`.
5. [ ] Lägg in en https-redirect, till exempel `https://localhost:8765/callback`. Notera App ID och App secret.
6. [ ] Koppla:
   ```bash
   export INSTAGRAM_APP_ID="…"; export INSTAGRAM_APP_SECRET="…"; export INSTAGRAM_REDIRECT_URI="https://localhost:8765/callback"
   python -m aie connect instagram
   ```
7. [ ] Instagram tar **bara JPEG** från en publik adress, och systemets designer är PNG (R-13). Slå inte på Instagram förrän R-13 är löst.

## 7. GitHub-hemligheter
Lägg in dem under Settings, Secrets and variables, Actions, New repository secret. Du kan också använda
`gh secret set NAMN`, som frågar efter värdet så att det inte syns i historiken:

| Hemlighet | Från | Behövs för |
|---|---|---|
| `PRINTIFY_API_TOKEN` | Printify, My profile, Connections (finns redan) | den dagliga katalogläsningen, och utkast när D-069 är godkänt |
| `ETSY_API_KEY` | Etsy developer-app: `keystring:shared_secret` | Etsys signaler och annonser |
| `ETSY_ACCESS_TOKEN` | `aie connect etsy` (filen i `~/.config/aie/tokens/etsy.json`) | butikens egna data i Actions |
| `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET` | Pinterest-appen | kopplingen |
| `PINTEREST_ACCESS_TOKEN` | `aie connect pinterest` | pins från Actions |
| `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` | Meta-appen | kopplingen |
| `INSTAGRAM_ACCESS_TOKEN` | `aie connect instagram` | inlägg från Actions |
| `INSTAGRAM_USER_ID` | kontots numeriska id, som Meta visar efter kopplingen | inlägg |

Kopiera ett token ur filen till GitHub utan att visa det:
`gh secret set ETSY_ACCESS_TOKEN < <(python -c "import json,pathlib;print(json.load(open(pathlib.Path.home()/'.config/aie/tokens/etsy.json'))['access_token'])")`.
Det fungerar i bash; på Windows öppnar du filen och kopierar värdet för hand.

## 8. När allt är kopplat
1. [ ] Sätt `enabled = true` för de tjänster som är kopplade, och `draft_enabled = true`, i `config/pod.toml`. Gör det i en PR, och bara när D-069 är godkänt.
2. [ ] Kör `python -m aie q4 --as <grundare> --catalog <katalogfilen från artefakten>`. Kalkylen och spärren använder då Printifys verkliga frakt.
3. [ ] Följ `products/q4/REPORT.md`. Bara idéer som är **redo** publiceras automatiskt.
