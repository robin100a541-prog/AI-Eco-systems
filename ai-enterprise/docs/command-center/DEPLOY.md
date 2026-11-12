# DEPLOY: så blir Command Center live

Den här guiden tar Command Center från koden i repot till en gemensam HTTPS-adress som bara Yorgo och Robin når. Allt är gratis, och inget betalkort behövs. Räkna med cirka 40 minuter första gången.

- **Inloggningen** är Command Centers egen (D-094): en åtkomstkod per grundare. Cloudflare Access används inte.
- **Följ stegen i ordning,** a till h. Varje steg säger vem som gör det.
- **Knappnamnen** är kontrollerade mot Cloudflares dokumentation 2026-11-11. De som är märkta "(ungefär)" kunde inte kontrolleras och kan heta något snarlikt.
- **Hemligheter:** skriv aldrig en kod, en nyckel eller en token i en fil i repot, i en PR eller i en chatt. De ska bara in i fälten som guiden pekar på.

## Det som redan är gjort
- **Koden** ligger i `ai-enterprise/command-center/`: webbsidan i `public/` och API:t i `functions/`.
- **KV-namnrymden** `aie-command-center` finns i Cloudflare.
- **GitHub-hemligheterna** `CLOUDFLARE_ACCOUNT_ID`, `KV_NAMESPACE_ID`, `STATE_KEY` och `GROQ_API_KEY` är satta.
  - **`STATE_KEY`** krypterar databaskopiorna i KV. Ingen har en kopia av värdet. Byt den inte i onödan: efter ett byte går de gamla kopiorna inte att läsa.
- **Actions-minuterna** är nere på cirka 1 310 per månad (`DATA.md` avsnitt 8), under taket 2 000 för ett privat repo.

## Steg a — Robin gör repot privat
1. Öppna repot på GitHub och gå till **Settings**.
2. Längst ned, under **Danger Zone**, välj **Change repository visibility**, sedan **Change to private**, och bekräfta.
3. **Kontrollera** i en terminal: `gh repo view robin100a541-prog/AI-Eco-systems --json visibility` ska visa `PRIVATE`.

## Steg b — Åtkomstkoder och sessionsnyckel (Yorgo och Robin, var för sig)
Var och en väljer sin egen kod, minst 12 tecken. Koden lämnar aldrig datorn: kommandot skriver bara ut en hash.

1. **Yorgo** kör i PowerShell, i mappen `ai-enterprise`:
   ```
   $env:PYTHONPATH = "src"; py -m aie command-center make-code --founder Yorgo
   ```
   Skriv koden två gånger (den syns inte). Kopiera raden som skrivs ut. Den börjar med `yorgo=pbkdf2_sha256$210000$`.
2. **Robin** kör samma kommando med `--founder Robin` på sin dator och kopierar sin rad, som börjar med `robin=`.
3. **Slå ihop raderna** med ett komma emellan, utan mellanslag och på en enda rad. Det är värdet för `FOUNDER_CODE_HASHES`:
   ```
   yorgo=pbkdf2_sha256$210000$...,robin=pbkdf2_sha256$210000$...
   ```
4. **Yorgo** skapar sessionsnyckeln:
   ```
   $env:PYTHONPATH = "src"; py -m aie command-center make-secret
   ```
   Värdet som skrivs ut är `SESSION_SECRET`.
5. **Spara båda värdena** i en lösenordshanterare tills steg d. Hashraderna är inte koderna, men behandla dem ändå som hemliga.

**Byta kod senare:** kör `make-code` igen, byt grundarens rad i `FOUNDER_CODE_HASHES` i Cloudflare och publicera om. Byter du `SESSION_SECRET` loggas alla ut.

## Steg c — Robin installerar Cloudflare Pages GitHub-app på repot
1. **Skapa ett Cloudflare-konto** på https://dash.cloudflare.com/sign-up om det inte redan finns. Gratisplanen räcker, och inget kort behövs.
2. I Cloudflare: gå till **Workers & Pages** och välj **Create application**, sedan **Pages** och **Connect to Git**.
3. Välj **GitHub** och logga in som Robin.
4. Välj **Only select repositories** och bara `AI-Eco-systems`, och sedan **Install & Authorize**.

## Steg d — Pages-projektet skapas, med hemligheter och KV-bindning (Robin)
1. Välj repot `AI-Eco-systems` och **Begin setup**.
2. Fyll i **Set up builds and deployments**:

   | Fält | Värde |
   |---|---|
   | Project name | `aie-command-center` (blir adressen `aie-command-center.pages.dev` och går inte att byta) |
   | Production branch | `main` |
   | Framework preset | `None` |
   | Build command | lämna tomt |
   | Build output directory | `public` |
   | Root directory (advanced) > Path | `ai-enterprise/command-center` |

3. Öppna **Environment variables (advanced)** på samma sida och lägg in de fem variablerna. Välj **Encrypt** (ungefär) för var och en:

   | Variabel | Värde |
   |---|---|
   | `FOUNDER_CODE_HASHES` | den sammanslagna raden från steg b |
   | `SESSION_SECRET` | värdet från steg b |
   | `GITHUB_READ_TOKEN` | läs-tokenen från steg f |
   | `GITHUB_DISPATCH_TOKEN` | dispatch-tokenen från steg f |
   | `GROQ_API_KEY` | samma Groq-nyckel som agenterna använder (för chatten) |

   Har du inte tokens från steg f ännu: gör steg f först, eller lägg in dem efteråt enligt punkt 6.
4. Välj **Save and Deploy**. Sidan är stängd direkt: utan `FOUNDER_CODE_HASHES` och `SESSION_SECRET` svarar den bara 503 "Not configured", och med dem kräver den inloggning.
5. **KV-bindningen:** gå till projektet, **Settings** > **Bindings** > **Add** > **KV namespace**.
   - **Variable name:** `KV` (exakt så, med versaler)
   - **KV namespace:** `aie-command-center`
6. **Lägga till eller ändra en variabel efteråt:** projektet, **Settings** > **Variables and Secrets** > **Add**, typen **Secret**, för både **Production** och **Preview**.
7. **Publicera om,** så att bindningen och variablerna börjar gälla: projektet, **Deployments**, och **Retry deployment** på den senaste.

## Steg e — Cloudflare API-token med rätt bara till KV (Robin)
1. I Cloudflare: **My Profile** > **API Tokens** > **Create Token**, och välj att börja från början (Custom token).
2. **Permissions:** `Account` · `Workers KV Storage` · `Edit`. Inga andra rättigheter.
3. **Account Resources:** bara ditt konto.
4. Välj **Continue to summary** och sedan **Create Token**. Värdet visas bara en gång.
5. Lägg värdet som GitHub-hemlighet: repot, **Settings** > **Secrets and variables** > **Actions** > **New repository secret**, med namnet `CLOUDFLARE_API_TOKEN`.

## Steg f — Två finkorniga GitHub-tokens (Robin)
Gå till GitHub, **Settings** (din profil) > **Developer settings** > **Personal access tokens** > **Fine-grained tokens** > **Generate new token**. Gör det två gånger. För båda gäller **Repository access:** **Only select repositories** och bara `AI-Eco-systems`.

| Token | Namn | Repository permissions | Blir variabeln i Cloudflare |
|---|---|---|---|
| Bara läsning | `command-center-read` | **Contents:** Read-only, **Pull requests:** Read-only, **Actions:** Read-only (Metadata följer med) | `GITHUB_READ_TOKEN` |
| Bara starta workflow | `command-center-dispatch` | **Actions:** Read and write (Metadata följer med). Inget annat | `GITHUB_DISPATCH_TOKEN` |

Välj en giltighetstid och skriv upp datumet. När en token går ut slutar GitHub-flödet eller knapparna att fungera tills den är utbytt i Cloudflare (steg d punkt 6).

## Steg g — Notiser: ntfy och Gmail (Yorgo och Robin)
1. **Installera appen ntfy** på mobilen, från App Store eller Google Play. Den är gratis och kräver inget konto.
2. **Välj ett ämne** som ingen kan gissa. Robin skapar det en gång, i PowerShell:
   ```
   "aie-" + (-join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_}))
   ```
3. **Prenumerera:** i appen väljer båda **Subscribe to topic** och skriver in ämnet. Dela det muntligt eller i en lösenordshanterare, aldrig i repot.
4. **App-lösenord för Gmail:** kontot som ska skicka måste ha tvåstegsverifiering. Gå till https://myaccount.google.com/apppasswords, skapa ett lösenord med namnet `command-center` och kopiera de 16 tecknen utan mellanslag.
5. **Lägg in GitHub-hemligheterna** (repot, **Settings** > **Secrets and variables** > **Actions** > **New repository secret**):

   | Hemlighet | Värde |
   |---|---|
   | `NTFY_TOPIC` | ämnet från punkt 2 |
   | `GMAIL_USER` | Gmail-adressen som skickar notiserna |
   | `GMAIL_APP_PASSWORD` | app-lösenordet från punkt 4 |
   | `NOTIFY_TO` (valfri) | mottagarnas adresser med komma emellan. Utan den går e-posten till `GMAIL_USER` |

Notiserna till ntfy innehåller bara fasta meningar utan belopp eller namn, eftersom den som kan ämnet kan läsa dem. Saknas en hemlighet hoppas den kanalen över utan fel.

## Steg h — Första körningen och kontrollen
1. **Kör den dagliga cykeln en gång:** på GitHub, **Actions** > **company-daily** > **Run workflow**. Bocka ur `verify_only` och välj **Run workflow**. Den publicerar den första snapshoten till KV.
2. **Kontrollera att sidan är stängd** för den som inte är inloggad:
   ```
   py ai-enterprise\scripts\check_deploy.py https://aie-command-center.pages.dev
   ```
   Varje sida och fil ska ge 302 till `/login`, API:t 401, och bara inloggningssidan 200. Skriptet säger till om sidan svarar 503 "Not configured".
3. **Logga in:** öppna https://aie-command-center.pages.dev, välj grundare och skriv din kod. Sidan ska visa data och "Data as of" med dagens datum.
4. **Prova spärren** om du vill: fem felaktiga koder låser inloggningen i 15 minuter.

## Framtida uppdateringar
- **En merge till `main`** som ändrar `ai-enterprise/command-center/` publiceras automatiskt av Cloudflare Pages inom någon minut.
- **Varje gren och PR** får en egen förhandsvisning på `<gren>.aie-command-center.pages.dev`. Den kräver samma inloggning, förutsatt att variablerna i steg d är satta för **Preview** också.
- **Data** uppdateras av `company-daily` varje dygn, och direkt efter varje knapptryck (`control-ingest`).

## Felsökning
| Det som syns | Orsak och åtgärd |
|---|---|
| "Not configured" (503) på alla sidor | `FOUNDER_CODE_HASHES` eller `SESSION_SECRET` saknas eller har fel form. Kontrollera att raden börjar med `yorgo=pbkdf2_sha256$210000$`, och att `SESSION_SECRET` har minst 32 tecken. Publicera om |
| "Wrong founder or access code" trots rätt kod | Hashraden klipptes av eller fick ett mellanslag. Kör `make-code` igen och byt raden |
| "Too many attempts" | Fem fel på 15 minuter. Vänta, eller ta bort nycklarna `lock:*` i KV |
| Felkod 1102 eller "Worker exceeded resource limits" vid inloggning | Gratisplanens gräns för processortid. Försök igen. Kommer felet ofta: ta med det till nästa session |
| Sidan laddar men visar "No data" | Snapshoten saknas i KV. Kör `company-daily` (steg h), och kontrollera `CLOUDFLARE_API_TOKEN` (steg e) |
| Gul banner "Data is stale" | Ingen snapshot på 26 timmar. Titta på senaste körningen av `company-daily` under Actions |
| Knappen ger "queued" men inget händer | `GITHUB_DISPATCH_TOKEN` saknas, har gått ut eller har fel rättighet. Beslutet ligger kvar och utförs vid nästa `company-daily` |
| Live-flödet saknar GitHub-händelser | `GITHUB_READ_TOKEN` saknas eller har gått ut |
| Chatten visar "Waiting for quota" | 30 meddelanden per timme är slut, eller Groqs gratiskvot. Vänta |
| Inga notiser | `NTFY_TOPIC` eller Gmail-hemligheterna saknas. Det är inget fel, kanalen hoppas bara över |

## Det som inte går att kontrollera härifrån
Guiden är skriven utan tillgång till Cloudflare-kontot. Koden är testad mot efterbildningar av Cloudflares och GitHubs API:er, men den första riktiga publiceringen är det första riktiga provet. Går något fel i ett steg: stanna, ändra inget annat och ta med felmeddelandet till nästa session.
