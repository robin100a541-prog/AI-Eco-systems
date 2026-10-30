# 7c: beslutskvalitet med språkmodell (riktig körning på Groq)

Körning: https://github.com/robin100a541-prog/AI-Eco-systems/actions/runs/41055312302 (2026-10-30, `pilot-groq.yml`),
modell `groq/openai/gpt-oss-120b` via `LLMGateway`. Utdata nedan är kopierad från loggen.

Produktförslag: källa **rule** (groq/openai/gpt-oss-120b). Reserv: IdeaError: bara 1 giltiga förslag av 3

Avvisade förslag: expected_net_90d_usd 2025 stämmer inte med kodens beräkning 1947.00; expected_net_90d_usd 2260 stämmer inte med kodens beräkning 2058.00

| Roll | Giltigt svar | Kommentar |
|---|---|---|
| cfo-1 | ja |  |
| cro-1 | ja |  |
| ceo-1 | nej, regel användes | IdeaError: expected_net_90d_usd 78.48 stämmer inte med 82.40 |

- Risk borde invända mot: inget
- Risk invände mot: inget
- Invändningarna räckte: ja
- Tvister: 0 (eskalerade till CEO)
- Valt förslag: f-skatt-guide

| Förslag | Pris USD | Avgift USD | Netto/st USD | Förväntat netto 90 d USD | Största förlust USD |
|---|---|---|---|---|---|
| frilans-fakturamall | 9.00 | 1.40 | 7.60 | 76.00 | 0.00 |
| hushallsbudget-mall | 5.00 | 1.00 | 4.00 | 48.00 | 0.00 |
| f-skatt-guide | 12.00 | 1.70 | 10.30 | 82.40 | 0.00 |

Efterfrågan är OVERIFIERAD i alla förslag (D-063).

Produktens text: model:groq/openai/gpt-oss-120b.

Beslut: Decision #1 för uppgift 1; vald produkt f-skatt-guide

## Bedömning

| Kontroll | Utfall |
|---|---|
| Alla fält i §20 steg 7 (CEO) | Modellen gav fälten, men **siffrorna stämde inte**: förväntat netto 78,48 i stället för 82,40 USD. Avvisat i kod, regeln beslutade. |
| Siffror som stämmer (produktagenten) | 2 av 3 förslag hade fel förväntat netto (modellen räknade fel på avgiften). Avvisade i kod; med bara 1 giltigt förslag användes regelförslagen. |
| CFO och risk | Giltiga, kompletta bedömningar för alla tre förslag. |
| Invände risk där den borde? | Ja. Inget förslag hade förskottskostnader, så det fanns inget att invända mot. Fallet där risk *missar* en invändning täcks av testet `test_missed_objection_is_flagged`. |
| Produkttexten | Skriven av modellen, men den har **sakfel** (moms- och skatteregler); se `products/f-skatt-guide/GRANSKNING.md`. Det går inte att validera i kod, så en grundare måste granska innan listning. |

**Validering i kod som redan finns för varje fält modellen missade:** förväntat netto (förslag och CEO), budget mot
största förlust, obligatoriska fält, riskklass och att CEO inte får välja ett förslag som risk invänt mot
(`src/aie/pilot/product.py: parse_idea`, `src/aie/pilot/decide.py: _ceo_draft`). Ett felaktigt svar avvisas,
och regeln för rollen används.
