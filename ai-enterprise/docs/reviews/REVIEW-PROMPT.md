# Oberoende granskning före Fas 7 (D-055)

**Status:** ingen granskning är gjord ännu (2026-10-30). Det här är grundaråtgärden som återstår.

Enligt D-055 ska kod som rör ledger, budget, skatt, stopp och behörigheter granskas av någon som inte
skrev den innan riktiga pengar används. En **ny** Claude-session (ny chatt, inget delat sammanhang med
sessionerna som byggde koden) räknas som oberoende granskare.

## Så gör du (grundare)
1. Öppna en ny Claude Code-session på repot `robin100a541-prog/AI-Eco-systems`, gren `main`.
2. Klistra in prompten nedan, oförändrad.
3. Sessionen skriver `ai-enterprise/docs/reviews/REVIEW-<datum>.md` och öppnar en PR med den.
4. Slå ihop PR:en. Nästa byggsession åtgärdar alla fynd märkta `high` eller `critical` innan Fas 7.

## Prompten

```text
Du är oberoende granskare enligt D-055 i robin100a541-prog/AI-Eco-systems (projektet i ai-enterprise/).
Du har inte skrivit koden. Läs CONSTITUTION.md, DECISIONS.md (D-016, D-049, D-055, D-059, D-063) och
REQUIREMENTS.md först.

Granska säkerhetskritisk kod som ska användas med riktiga pengar i Fas 7:
- src/aie/ledger/ (append-only, idempotens, valutaseparation SIM/riktig valuta, ER-01, ER-08, ER-15)
- src/aie/budget/ (budgetmotorn, kapitalposition, reserv, tak, ER-02, §5)
- src/aie/tax/ (skattereserv, momsbevakning, arkiv, D-010)
- src/aie/risk/ och stoppen: stop-loss, nödstopp (kill switch), skyddat läge
- src/aie/authorization/ och config/permissions.toml (default deny, SR-01, SR-02)
- src/aie/pilot/ (piloten: godkännande, import av försäljning, avstämning, stoppregler)
- src/aie/llm/gateway.py (inga hemligheter i prompter, bara gratisleverantörer, DR-13)
- alla PR:er med etiketten `kräver-oberoende-granskning`

För varje fynd: fil och rad, vad som kan gå fel (konkret scenario), allvarlighet
(critical/high/medium/low) och föreslagen åtgärd. Kör hela testsviten
(`cd ai-enterprise && PYTHONPATH=src python -m unittest discover -s tests`) och visa utfallet.
Ändra ingen kod. Skriv resultatet till ai-enterprise/docs/reviews/REVIEW-<ÅÅÅÅ-MM-DD>.md med en
sammanfattningstabell överst, och öppna en PR med bara den filen.
```
