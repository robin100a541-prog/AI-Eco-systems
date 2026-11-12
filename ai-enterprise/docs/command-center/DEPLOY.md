# DEPLOY: så blir Command Center live

> **2026-11-12:** Cloudflare Access används inte längre (D-094). Steg 3 och variablerna `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` och `ALLOWED_EMAILS` nedan gäller inte. Guiden skrivs om i nästa del.

Den här guiden tar Command Center från koden i repot till en gemensam HTTPS-adress som bara Yorgo och Robin når. Allt är gratis. Räkna med cirka 45 minuter första gången.

- **Vem gör vad:** stegen 1–5 kräver Robin, som äger repot. Yorgo kan sitta med. Steg 7 gör var och en på sin mobil.
- **Efteråt:** en merge till `main` publiceras automatiskt inom någon minut (steg 8).
- **Knappnamnen** är kontrollerade mot Cloudflares dokumentation 2026-11-11. De som är märkta "(ungefär)" kunde inte kontrolleras och kan heta något snarlikt.
- **Hemligheter:** skriv aldrig en nyckel, ett lösenord eller en token i en fil i repot, i en PR eller i en chatt. De ska bara in i fälten som guiden pekar på.

## Det som redan är gjort
- **Koden** ligger i `ai-enterprise/command-center/`: webbsidan i `public/` och API:t i `functions/`.
- **`STATE_KEY`** är satt som GitHub-hemlighet 2026-11-11. Den krypterar databaskopiorna i KV.
  - **Ingen har en kopia av värdet,** och det går inte att läsa ut.
  - **Byt den inte i onödan:** efter ett byte går de gamla kopiorna i KV inte att läsa. Databasen finns då kvar i Actions-cachen, och nästa körning sparar en ny kopia.

## Steg 1 — Gör repot privat och ge Cloudflare tillgång (Robin)
1. **Gör repot privat:** öppna repot på GitHub och gå till **Settings**. Längst ned under **Danger Zone** väljer du **Change repository visibility**, sedan **Change to private**, och bekräftar.
2. **Kontrollera:** `gh repo view robin100a541-prog/AI-Eco-systems --json visibility` ska visa `PRIVATE`.
3. **Cloudflares GitHub-app** installeras i steg 2, när du kopplar repot. Välj då **Only select repositories** och bara `AI-Eco-systems`.

**Varför privat först:** ett privat repo har 2 000 gratis Actions-minuter per månad. Beräkningen står i `DATA.md` avsnitt 8.

## Steg 2 — Cloudflare-konto och Pages-projekt (Robin)
1. **Skapa ett konto** på https://dash.cloudflare.com/sign-up. Gratisplanen räcker, och inget kort behövs.
2. **Skapa projektet:** gå till **Workers & Pages** och välj **Create application**, sedan **Pages** och **Connect to Git**.
3. **Koppla GitHub:** välj **GitHub** och logga in. Välj **Only select repositories** och `AI-Eco-systems`, och sedan **Install & Authorize**.
4. **Börja:** välj repot och **Begin setup**.
5. **Fyll i Set up builds and deployments:**

   | Fält | Värde |
   |---|---|
   | Project name | till exempel `aie-command-center`. Det blir adressen `aie-command-center.pages.dev` och går inte att byta senare |
   | Production branch | `main` |
   | Framework preset | `None` |
   | Build command | lämna tomt |
   | Build output directory | `public` |
   | Root directory (advanced) > Path | `ai-enterprise/command-center` |

6. **Publicera:** välj **Save and Deploy**. Sidan är nu publicerad men **öppen för alla** tills steg 3 är klart. Gör därför steg 3 direkt. Den visar ingen data ännu, eftersom KV saknas.

## Steg 3 — Access: bara två mejladresser kommer in (Robin)
1. **Slå på Access:** gå till Pages-projektet, **Settings**, och välj **Enable access policy**. Första gången får du välja ett teamnamn för Zero Trust. Välj gratisplanen (Free), som räcker för upp till 50 användare.
2. **Skydda produktionsadressen också:**
   1. Välj **Manage** på policyn som skapades.
   2. Under **Access** > **Applications** väljer du projektet och sedan **Configure**.
   3. Under **Public hostname**, i fältet **Subdomain**, tar du bort jokertecknet (`*`) och väljer **Save**. Byt **Application name** om du får ett fel.
   4. Gå tillbaka till Pages-projektet, **Settings** > **General**, och välj **Enable access policy** igen.
   5. Nu ska det finnas **två** applikationer: en för `aie-command-center.pages.dev` och en för förhandsvisningarna (`*.aie-command-center.pages.dev`).
3. **Engångskod som inloggning:** i **Zero Trust**, under inställningarna för inloggningsmetoder (ungefär: **Settings** > **Authentication** > **Login methods**), lägger du till **One-time PIN**. Nya team har den inte påslagen från början.
4. **Policyn i båda applikationerna:** öppna varje applikation under **Zero Trust** > **Access controls** > **Applications** och redigera dess policy:
   - **Action:** `Allow`
   - **Include:** väljaren `Emails`, med exakt de två adresserna (Yorgos och Robins)
   - Ta bort alla andra regler, till exempel "Emails ending in" och "Everyone".
5. **Kopiera AUD-taggarna:** för varje applikation väljer du **Edit**, och under **Additional settings** kopierar du **Application Audience (AUD) Tag**. Det blir två värden, som används i steg 6.
6. **Teamdomänen** är `<teamnamn>.cloudflareaccess.com`. Den används också i steg 6.

**Kontroll:** öppna adressen i ett privat webbläsarfönster. Du ska få Cloudflares inloggningssida, och en annan mejladress än de två ska aldrig få någon kod.

## Steg 4 — KV-namnrymden och bindningen (Robin)
1. **Skapa namnrymden:** i Cloudflare går du till KV (ungefär: **Storage & Databases** > **KV**) och skapar en namnrymd med namnet `aie-command-center`.
2. **Kopiera ID:t** som står vid namnrymden. Det är `KV_NAMESPACE_ID` i steg 6.
3. **Bind den till Pages-projektet:** gå till projektet, **Settings** > **Bindings** > **Add** > **KV namespace**.
   - **Variable name:** `KV` (exakt så, med versaler)
   - **KV namespace:** `aie-command-center`
4. Bindningen börjar gälla vid nästa publicering (steg 6 avslutas med en).

## Steg 5 — Tre tokens (Robin)
**Två finkorniga GitHub-tokens:** gå till GitHub, **Settings** (din profil) > **Developer settings** > **Personal access tokens** > **Fine-grained tokens** > **Generate new token**. För båda gäller **Repository access:** **Only select repositories** och `AI-Eco-systems`.

| Token | Namn | Repository permissions | Blir variabeln |
|---|---|---|---|
| Läsning | `command-center-read` | **Contents:** Read-only, **Pull requests:** Read-only, **Actions:** Read-only (Metadata följer med) | `GITHUB_READ_TOKEN` |
| Starta workflow | `command-center-dispatch` | **Actions:** Read and write (Metadata följer med) | `GITHUB_DISPATCH_TOKEN` |

**En Cloudflare API-token med rätt bara till KV:** i Cloudflare går du till **My Profile** > **API Tokens** > **Create Token** och väljer att börja från början (Custom token).
- **Permissions:** `Account` · `Workers KV Storage` · `Edit`
- **Account Resources:** bara ditt konto
- Välj **Continue to summary** och sedan **Create Token**. Värdet visas bara en gång. Det blir `CLOUDFLARE_API_TOKEN`.

**Konto-ID:t** (`CLOUDFLARE_ACCOUNT_ID`) står på startsidan för **Workers & Pages**, i högerspalten (ungefär: **Account ID**).

## Steg 6 — Var varje variabel ska ligga
`ALLOWED_EMAILS` skrivs som `yorgo=<Yorgos mejl>,robin=<Robins mejl>`, med exakt samma värde på båda ställena. Namnen före `=` måste vara `yorgo` och `robin`, eftersom det är så grundarna heter i `config/system.toml`.

**I Cloudflare** (Pages-projektet, **Settings** > **Variables and Secrets** > **Add**, välj typen **Secret**, och lägg dem för både **Production** och **Preview**):

| Variabel | Värde |
|---|---|
| `ACCESS_TEAM_DOMAIN` | `<teamnamn>.cloudflareaccess.com`, utan `https://` |
| `ACCESS_AUD` | de två AUD-taggarna från steg 3, med komma emellan |
| `ALLOWED_EMAILS` | `yorgo=...,robin=...` |
| `GITHUB_READ_TOKEN` | läs-tokenen från steg 5 |
| `GITHUB_DISPATCH_TOKEN` | dispatch-tokenen från steg 5 |
| `GROQ_API_KEY` | samma Groq-nyckel som agenterna använder (för chatten) |

**I GitHub** (repot, **Settings** > **Secrets and variables** > **Actions** > **New repository secret**):

| Hemlighet | Värde |
|---|---|
| `CLOUDFLARE_API_TOKEN` | KV-tokenen från steg 5 |
| `CLOUDFLARE_ACCOUNT_ID` | konto-ID:t från steg 5 |
| `KV_NAMESPACE_ID` | ID:t från steg 4 |
| `ALLOWED_EMAILS` | `yorgo=...,robin=...` |
| `NTFY_TOPIC` | ämnet från steg 7 |
| `GMAIL_USER` | Gmail-adressen som skickar notiserna |
| `GMAIL_APP_PASSWORD` | ett app-lösenord för den adressen, se nedan |
| `GROQ_API_KEY` | finns redan |
| `STATE_KEY` | finns redan, rör den inte |

**App-lösenord för Gmail:** kontot måste ha tvåstegsverifiering. Gå till https://myaccount.google.com/apppasswords, skapa ett lösenord med namnet `command-center` och kopiera de 16 tecknen utan mellanslag.

**Avsluta med att publicera och fylla på data:**
1. **Publicera om:** i Pages-projektet går du till **Deployments** och väljer **Retry deployment** på den senaste, så att variablerna och bindningen börjar gälla.
2. **Kör den dagliga cykeln en gång:** på GitHub går du till **Actions** > **company-daily** > **Run workflow**, bockar ur `verify_only` och väljer **Run workflow**. Den publicerar den första snapshoten till KV.
3. **Öppna adressen** och logga in. Sidan ska visa data och "Data as of" med dagens datum.

## Steg 7 — ntfy på mobilen (Yorgo och Robin, var för sig)
1. **Installera appen ntfy** från App Store eller Google Play. Den är gratis och kräver inget konto.
2. **Välj ett ämne** som ingen kan gissa. Robin skapar det en gång, till exempel `aie-` följt av 24 slumpade tecken. I PowerShell:
   ```
   -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})
   ```
3. **Prenumerera:** i appen väljer du **Subscribe to topic** och skriver in ämnet. Båda grundarna prenumererar på samma ämne.
4. **Lägg ämnet** som GitHub-hemligheten `NTFY_TOPIC` (steg 6). Dela det mellan er muntligt eller i en lösenordshanterare, aldrig i repot.

Notiserna innehåller bara fasta meningar utan belopp eller namn, eftersom den som kan ämnet kan läsa dem.

## Steg 8 — Framtida uppdateringar
- **En merge till `main`** som ändrar `ai-enterprise/command-center/` publiceras automatiskt av Cloudflare Pages inom någon minut. Ingen behöver göra något.
- **Varje gren och PR** får en egen förhandsvisning på `<gren>.aie-command-center.pages.dev`. Den skyddas av samma Access-regel (steg 3).
- **Data** uppdateras av `company-daily` varje dygn, och direkt efter varje knapptryck (`control-ingest`).
- **Variabler:** ändrar du en variabel i Cloudflare krävs en ny publicering (**Retry deployment**).

## Kontrollera att sidan är stängd
Kör efter steg 3, och sedan när du vill:
```
py ai-enterprise\scripts\check_deploy.py https://aie-command-center.pages.dev
```
Skriptet loggar inte in. Varje adress, också `/api/health`, ska ge en omdirigering till Cloudflare Access och aldrig 200. Det avslutar med fel om något är öppet.

## Felsökning
| Det som syns | Orsak och åtgärd |
|---|---|
| Sidan laddar men visar "No data" | Snapshoten saknas i KV. Kör `company-daily` (steg 6), och kontrollera de tre Cloudflare-hemligheterna i GitHub |
| "Not signed in" eller 401 från API:t | `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` eller `ALLOWED_EMAILS` stämmer inte i Cloudflare. Publicera om efter ändringen |
| Gul banner "Data is stale" | Ingen snapshot på 26 timmar. Titta på senaste körningen av `company-daily` under Actions |
| En knapp ger "this identity has no founder name" | `ALLOWED_EMAILS` saknar `yorgo=` eller `robin=` framför adressen |
| Knappen ger "queued" men inget händer | `GITHUB_DISPATCH_TOKEN` saknas eller har fel rättighet. Beslutet ligger kvar och utförs vid nästa `company-daily` |
| Chatten visar "Waiting for quota" | 30 meddelanden per timme är slut, eller Groqs gratiskvot. Vänta |
| Inga notiser | `NTFY_TOPIC` eller Gmail-hemligheterna saknas. Det är inget fel, kanalen hoppas bara över |

## Det som inte går att kontrollera härifrån
Guiden är skriven utan tillgång till ett Cloudflare-konto. Koden är testad mot efterbildningar av Cloudflares och GitHubs API:er, men den första riktiga publiceringen är det första riktiga provet. Går något fel i ett steg: stanna, ändra inget annat och ta med felmeddelandet till nästa session.
