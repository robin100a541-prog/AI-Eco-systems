# Arbetsorder 05 — lansering Q4, första försäljningen (Yorgo, 2026-11-06)

Sparad ordagrant enligt D-012. Inklistrad av Yorgo i en Claude Code-session 2026-11-06.

---

Läs CLAUDE.md, TODO.md och ai-enterprise/PROJECT_STATUS.md.

GRUNDARBESLUT 2026-11-04 (Yorgo; räcker enligt D-049):
Efter 15 dagar finns ingen produkt ute. Målet är nu FÖRSTA FÖRSÄLJNING via Printify → Etsy inom 2 dagar.
Pausa allt arbete på styrning, register, granskningar och processer som inte blockerar detta.
Skriv planen nedan i ai-enterprise/docs/LANSERING-Q4.md och uppdatera PROJECT_STATUS.

Reservera migrations- och D-nummer i TODO.md och pusha först. Små PR:er. Slå ihop själv när CI är grön.
Sätt aldrig ANTHROPIC_API_KEY. Nycklar läses bara från miljövariabler och skrivs aldrig ut, loggas aldrig och committas aldrig.

1. BESLUT "TESTLÄGE": skriv in det i DECISIONS.md, godkänt av Yorgo.
   - Print-on-demand har ingen lagerrisk, eftersom kunden betalar innan Printify trycker.
   - Högst 20 aktiva Etsy-annonser via Printify UTAN krav på simuleringens "redo".
   - Max förlust = annonsavgifter (0,20 USD per annons) plus Etsys engångsavgift. Ingen betald reklam.
   - Varje produkt måste ha minst 30 % marginal per såld vara efter Printifys baspris, frakt till USA och EU, Etsys avgifter (6,5 % + betalningsavgift) och reserverad skatt. Annars stryks den.
   - founder_hour_value räknas inte i testläget.
   - Stop-loss och nödstopp gäller. Testläget slutar efter 30 dagar.
   Koppla in det i spärren så att testlägets produkter går igenom och allt annat fortfarande stoppas. Lägg till tester.

2. BEROENDE: tillåt Pillow (licens HPND, gratis) som enda nytt beroende, och bara i src/aie/pod/design. Skriv det i beslutet. Resten av koden använder fortfarande bara standardbiblioteket.

3. SCOUTEN: byt search_terms i config/founders.toml till print-on-demand för Q4: jul, presenter till pappa/mamma/lärare, fotboll, svenska, engelska och arabiska citat, fastighetsmäklare, kreatörer och videoredigerare. Kör scouten och dev-agenten en gång i veckan i stället för flera gånger per dag.

4. DESIGNER: ta fram 20 EGNA typografiska designer som PNG. Använd Printifys krav på format och upplösning, som du hämtar från Printifys API eller dokumentation.
   - Inga varumärken, klubbmärken, kända personer, figurer eller kopierad text.
   - Använd bara typsnitt med öppen licens, och lägg licensen i repot.
   - Spara designerna i ai-enterprise/products/q4/<nyckel>/.

5. PRINTIFY: hämta katalogen med PRINTIFY_API_TOKEN. Välj för varje design 1–2 produkter (t-shirt, hoodie, mugg eller poster) och en print provider som levererar till både USA och EU till lägst kostnad.
   - Skapa OPUBLICERADE produkter i Printify med titel, beskrivning, 13 taggar och pris.
   - Beskrivningen ska ange att designen är gjord med hjälp av AI och att Printify är produktionspartner.
   - Om Printifys API inte går att nå från din miljö: skapa allt som filer och skriv exakt vilket kommando grundaren ska köra lokalt.

6. Skriv ai-enterprise/products/q4/LISTA.md: en rad per produkt med bild, produkttyp, kostnad, pris, marginal i kr och %, taggar och en färdig Pinterest-text med rubrik och beskrivning. Längst ner: "Godkänn genom att skriva GODKÄND – namn".

7. Bygg `python -m aie pod publish --approved` som bara publicerar de produkter i LISTA.md som inte är strukna, och bara om raden GODKÄND finns. Kontrollera testlägets gräns på 20 annonser. Kör den INTE nu.

8. Bygg `python -m aie pod orders` som läser nya ordrar från Printify varje dag och för in dem i ledgern. Lägg till ett GitHub Actions-jobb för det.

Rapportera på svenska:
- om Printify-anropet fungerade,
- antal produkter i LISTA.md,
- lägsta och högsta marginal,
- och att grundaren nu ska följa steg 4–8 i LANSERING-Q4.md.
