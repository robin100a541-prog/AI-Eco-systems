# Arbetsorder 04 — print-on-demand inför Q4 (Yorgo, 2026-11-04)

Sparad ordagrant enligt D-012. Inklistrad av Yorgo i en Claude Code-session 2026-11-04.

---

Läs CLAUDE.md, TODO.md, ai-enterprise/PROJECT_STATUS.md och ai-enterprise/docs/FOUNDER-CHECKLIST.md.

BAKGRUND (grundarbeslut 2026-11-04, Yorgo): Vi satsar på print-on-demand inför Q4.
Kedjan blir: Printify (leverantör, gratisplanen) → Etsy (säljsida, global, inga månadsavgifter) → Pinterest och eventuellt Instagram (automatisk marknadsföring). Trender och idéer hämtas från Etsy API, Pinterest Trends API och Printifys katalog.
Krav: 0 kr i fasta kostnader, hela världen som marknad, och så lite manuellt arbete som möjligt (bara att skapa konton och koppla API:er).
Konton för Etsy, Pinterest och Instagram finns INTE än. Bygg allt som går utan dem, med mockar.

REGLER: Bara standardbiblioteket. Sätt aldrig ANTHROPIC_API_KEY. Nycklar läses bara från miljövariabler eller GitHub-hemligheter och skrivs aldrig ut, loggas aldrig och committas aldrig. Inga nätverksanrop i testerna. Inga betaltjänster. Allt externt går via Authorization Engine som egna verktyg. Små PR:er. Reservera migrations- och D-nummer i TODO.md och pusha det först. Spara den här prompten i ai-enterprise/docs/prompts/04-pod-q4.md och logga sessionen enligt D-012.

1. PRINTIFY (nyckeln finns: PRINTIFY_API_TOKEN)
   - Klient med urllib: Bearer-token, egen User-Agent, timeout, begränsat antal återförsök, och hantering av rate limits.
   - Läsverktyget `printify.read`: shops, blueprints, print providers, varianter med baspris och frakt per land.
   - Verifiera i Printifys API-dokumentation vilka bildformat uppladdning kräver (PNG/JPEG/SVG, upplösning).
   - Skrivverktyget `printify.draft`: skapa en OPUBLICERAD produkt i Printify. Det kostar inget och publicerar inget. Bygg det men låt det vara AV i konfigurationen tills grundarna godkänt beslutet i punkt 6.
   - En daglig GitHub Actions-körning läser katalogen. Hemligheten får aldrig vara tillgänglig för PR:er från forkar.

2. PLATTFORMSREGISTRET: lägg in Printify och Etsy med verifierade avgifter, källa och datum.
   - Etsy: 0,20 USD per annons, 6,5 % transaktionsavgift, betalningsavgift, Offsite Ads 12–15 % vid sådan försäljning, och en eventuell engångsavgift vid start.
   - Printify: baspris och frakt per produkt och land. Printify Premium (39 USD/mån) räknas som en kostnad som kräver beslut.
   - Etsy kräver att Printify anges som produktionspartner och att AI-användning anges i annonsen. Lägg in det som regler som kontrolleras i koden.

3. KLIENTER SOM VÄNTAR PÅ NYCKLAR (mockade, avstängda tills nyckeln finns)
   - Etsy Open API v3 (ETSY_API_KEY, OAuth): läsa listningar, sökningar, favoriter och recensioner som marknadssignaler till scouten.
   - Pinterest API v5 (PINTEREST_*): Trends (`/v5/trends/keywords/{region}/top/{trend_type}`) som trendsignal, och skapa pin med länk till Etsy-annonsen.
   - Instagram Graph API (INSTAGRAM_*): publicera bild eller karusell från en publik bild-URL, högst 50 inlägg per dygn.
   - Varje klient har ett kommando för att koppla kontot: `python -m aie connect etsy|pinterest|instagram`. Det kör OAuth med en lokal callback-server på 127.0.0.1 och sparar token utanför repot.

4. DET PINTEREST KRÄVER FÖR STANDARD-ÅTKOMST (förbered nu)
   - En integritetspolicy och en appbeskrivning som en statisk sida i docs/ (publiceras via GitHub Pages).
   - En manus-checklista för den demovideo Pinterest kräver: OAuth-flödet och en riktig pin. Grundaren spelar in den.

5. Q4-IDÉER MED RIKTIGA KOSTNADER
   - Låt scouten och Research ta fram 10 Q4-idéer (jul, Black Friday, presenter, nischade målgrupper) med Printifys verkliga baspris och frakt plus Etsys avgifter och skatt.
   - Kör spärren "simulera före start" (normal och pessimistisk).
   - Designerna måste vara egna: inga varumärken, kända figurer eller kopierade motiv. Lägg in en kontroll som stoppar sådant.
   - Utred om det finns en GRATIS bildgenerering vars villkor tillåter kommersiell användning. Lägg den som en R-fråga, och koppla inte in något som kostar. Tills vidare: typografiska designer och mönster som systemet själv kan generera som PNG eller SVG.
   - Spara de bästa idéerna som utkast i ai-enterprise/products/q4/: design, titel, taggar, pris, marginal och valideringsplan.

6. BESLUTSFÖRSLAG OM AUTONOMI (i docs/proposals/, ska godkännas av en grundare enligt D-049)
   Agenterna får utan att fråga:
   - skapa utkast i Printify,
   - publicera högst 5 nya Etsy-annonser per dag (bara produkter som klarat spärren),
   - publicera högst 10 marknadsföringsinlägg per dag,
   - göra utgifter under HUMAN_APPROVAL_THRESHOLD inom budget.
   Allt loggas, en daglig rapport skrivs, och nödstoppet och stop-loss gäller. Kundmeddelanden på Etsy kan inte skötas via API: grundarna notifieras.

7. Skriv ai-enterprise/docs/setup-konton.md med exakta steg för grundarna: Etsy-butik, koppla Printify till Etsy, Etsy developer-app, Pinterest företagskonto, Pinterest-app och uppgradering till Standard, Instagram Professional-konto och Meta-app, och vilka GitHub-hemligheter som ska läggas in.

8. Kör hela sviten. Rapportera på svenska:
   - vad som är byggt,
   - antal tester,
   - om Printify-anropet fungerade på riktigt,
   - de 3 bästa Q4-idéerna med kalkyl,
   - exakt vad grundarna ska göra härnäst.
