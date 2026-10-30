# Granskning före listning (MÅSTE göras av en grundare)

**Status: INTE KLAR ATT LISTA.** Texten i `product.md` är skriven av Groq (`openai/gpt-oss-120b`) i körningen
https://github.com/robin100a541-prog/AI-Eco-systems/actions/runs/41055312302 (2026-10-30). Den är oförändrad.
Listningen lovar att en människa har granskat produkten, så följande måste rättas först:

| Var | Fel i modellens text | Rätt (kontrollera hos Skatteverket) |
|---|---|---|
| Avsnitt 1, "Skatteplanering" | "Vinsten beskattas som inkomst av tjänst" | Enskild firma beskattas som inkomst av **näringsverksamhet** (NE-bilaga), vilket avsnitt 4.4 själv säger. |
| Avsnitt 3 och checklistan punkt 4 | Momsregistrering "obligatorisk från 30 000 kr" | Gränsen för momsbefrielse är **120 000 kr** per år sedan 2025 (samma gräns som D-010 bevakar). |
| Avsnitt 3, momssatser | "Livsmedel, restaurang 12 %", "Böcker 6 %" | Kontrollera aktuella satser; de har ändrats tillfälligt för livsmedel. |
| Avsnitt 4.1 | Fortnox listas som gratis | Fortnox är betalt; kontrollera varje programs pris. |
| Avsnitt 5 | "F-skattenummer 123456-7890" | Det finns inget separat F-skattenummer; fakturan ska ange att företaget **godkänts för F-skatt**. |
| Avsnitt 5 | Exempel på personnummer, IBAN och adresser | Ersätt med tydligt påhittade platshållare (t.ex. ÅÅMMDD-XXXX). |
| Avsnitt 6, punkt 12 | "Senast 31 maj" | Kontrollera deklarationsdatum för enskild firma (vanligen 2 maj, eller senare med ombud). |

Efter rättning: skriv om `product.pdf` med `python -c "from aie.pilot.writer import write_pdf; ..."` eller kör
`aie pilot ideas` igen och jämför. Ta bort raden "INTE KLAR ATT LISTA" när granskningen är gjord.
