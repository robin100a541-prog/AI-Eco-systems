# Lansering Q4: första försäljningen via Printify och Etsy

**Grundarbeslut 2026-11-04 (Yorgo, räcker enligt D-049):** efter 15 dagar finns ingen produkt ute. Målet är
nu den **första försäljningen via Printify och Etsy inom 2 dagar**. Allt arbete med styrning, register, granskningar
och processer som inte blockerar detta är pausat. Prompten finns i `docs/prompts/05-lansering-q4.md`.

## Ramarna (beslut D-070, testläget)
- **Ingen lagerrisk:** print-on-demand trycks först när kunden har betalat.
- **Högst 20 aktiva Etsy-annonser** via Printify, utan krav på att simuleringen säger "redo".
- **Största förlust:** annonsavgifterna (0,20 USD per annons, alltså högst 4 USD) och Etsys engångsavgift för att öppna butiken. Ingen betald reklam.
- **Varje produkt måste ha minst 30 % marginal** per såld vara. Annars stryks den. Marginalen räknas efter:
  - Printifys verkliga baspris
  - den dyraste frakten till USA eller EU
  - Etsys avgifter: 0,20 USD per annons, 6,5 % i transaktionsavgift, och 4 % + 3 SEK i betalningsavgift
  - reserverad skatt
- **Grundarnas tid** räknas inte i testläget.
- **Stop-loss och nödstopp** gäller.
- **Testläget slutar efter 30 dagar.**
- **Pillow** (licens HPND) är tillåtet som enda nytt beroende, och bara i `src/aie/pod/design/`.

## Steg
| # | Vem | Vad | Var | Klart när |
|---|---|---|---|---|
| 1 | Claude | Testläget i koden: spärren släpper igenom testlägets produkter och stoppar allt annat | `src/aie/pod/testmode.py`, `config/pod.toml [test_mode]` | testerna är gröna och sammanslagna |
| 2 | Claude | 20 egna typografiska designer som PNG, med typsnitt med öppen licens | `products/q4/<nyckel>/`, `assets/fonts/` | filerna finns, med licenserna |
| 3 | Claude | Printify: välj produkt och tryckeri med lägst kostnad till USA och EU, skapa **opublicerade** produkter, läs verkligt baspris och skriv listan | arbetsflödet `pod-prepare`, `products/q4/LISTA.md` | `LISTA.md` har en rad per produkt med marginal; varje produkt under 30 % är struken |
| 4 | **Grundare** | Godkänn D-070: sätt etiketten `founder-approved` på PR:en med DECISIONS.md och slå ihop | GitHub | PR:en är sammanslagen |
| 5 | **Grundare** | Skapa Etsy-butiken och lägg till Printify som produktionspartner | `docs/setup-konton.md` steg 1–2 | butiken finns, och Printify står under Production partners |
| 6 | **Grundare** | Koppla Printify-butiken till Etsy. Printifys butik heter i dag "My new store (disconnected)" | printify.com, My stores, Connect, Etsy | Printify visar butiken som kopplad till Etsy |
| 7 | **Grundare** | Läs `products/q4/LISTA.md`. Stryk det du inte vill sälja, med `~~` runt raden. Skriv sist `GODKÄND – <namn>` och slå ihop | en PR mot `products/q4/LISTA.md` | raden GODKÄND finns på `main` |
| 8 | **Grundare** | Kör arbetsflödet **pod-publish** (Actions, pod-publish, Run workflow). Det publicerar de godkända produkterna från Printify till Etsy, högst 20. Lägg sedan upp Pinterest-texterna ur `LISTA.md` för hand | GitHub Actions och Pinterest | annonserna syns i Etsy-butiken |

**Efter publiceringen:**
- **Ordrar:** `pod-orders` läser nya ordrar från Printify varje dygn och för in dem i ledgern.
- **Meddelanden:** kundmeddelanden på Etsy besvaras av grundarna, eftersom de inte finns i API:t.
- **Efter 30 dagar** slutar testläget. Fortsätt bara med det som sålt, och med ett nytt beslut.

## Det som är pausat
Granskningar, register, scoutens dagliga körningar och utvecklaragentens körningar flera gånger per dag. Scouten och utvecklaragenten körs nu en gång i veckan.
