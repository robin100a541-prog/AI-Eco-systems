# PROJECT_STATUS

**Senast uppdaterad:** 2026-10-21 av Claude (session med Yorgo)
**Aktuell fas:** Fas 0 — Krav och tekniska förutsättningar
**Fasstatus:** Claudes del klar · väntar på grundarna (uppgift 0.5–0.8 i ROADMAP.md)

## Läs detta först (för den som öppnar en ny Claude-konversation)
1. Ge Claude hela repot eller åtminstone: CONSTITUTION.md, PROJECT_STATUS.md, DECISIONS.md, ARCHITECTURE.md, REQUIREMENTS.md.
2. Skriv: *"Fortsätt projektet enligt PROJECT_STATUS.md."*
3. Claude har **ingen** kännedom om den andra grundarens konversationer. Allt som gäller står i filerna.

## Vad som finns (verifierat)
| Sak | Bevis |
|---|---|
| Kravlista FR/SR/ER/DR, 79 krav | REQUIREMENTS.md |
| Arkitekturförslag + verktygsregister med licenser, gratis modeller och skattemodul | ARCHITECTURE.md |
| Beslut D-001…D-010 (föreslagna, D-005 ersatt av D-008), 8 öppna frågor | DECISIONS.md |
| `scripts/check_env.py` + `scripts/llm_smoke_test.py`, 18 enhetstester | `python3 -m unittest discover -s tests -v` → 18 OK (körd 2026-10-21 i Claudes Linux-sandlåda, Python 3.13) |

## Ändrat 2026-10-21 på Yorgos begäran
- Agenterna ska använda **gratis språkmodeller** från start (D-008). Betalda API:er får köpas först när systemet har realiserad vinst (D-009).
- Skatt ska hanteras **utan att öppna aktiebolag**; systemet räknar och reserverar skatt per skattespår (D-010).
- Gumroad och Etsy tillagda som försäljningskanaler; de sköter moms mot köpare men inkomstskatten är kvar hos er (D-010, tillägg).
- Fiverr tillagt som kanal för tjänster. Öppna frågor utreds av systemet självt (D-011, `research/QUESTIONS.md`).
- Alla sessioner arkiveras i `docs/conversations/` (D-012).
- **GitHub är inte kopplat än** — repot finns lokalt med en första commit och väntar på att pushas.
- Fiverr tillagd; kanalregister i `docs/channels.md`. Agenterna ska själva kunna utreda nya kanaler och lösningar, med godkännande av grundarna (D-011).

## Vad som INTE är gjort / inte verifierat
- Skripten är **inte** körda på Yorgos eller Robins datorer. Windows/macOS-grenarna för RAM-avläsning är oprövade.
- Inget gratis-API har anropats på riktigt — Claudes miljö blockerar dem. `llm_smoke_test.py` är testat mot en falsk server.
- Skattespåren i D-010 är inte bekräftade av Skatteverket.
- Inget GitHub-repo finns ännu.
- Inga beslut är godkända. Ingen beslutsfördelning mellan grundarna är fastställd.
- Ingen applikationskod (Fas 1) finns.

## Nästa åtgärder
| # | Vad | Vem |
|---|---|---|
| 1 | Kör `check_env.py`, klistra in resultatet i `docs/environment.md` | Yorgo och Robin (var för sig) |
| 1b | Skapa gratis Groq-nyckel, kör `llm_smoke_test.py --provider groq`, klistra in resultatet | Minst en av er |
| 2 | Skapa privat GitHub-repo, bjud in den andra, pusha | En av er |
| 3 | Kryssa i godkännanden i DECISIONS.md, besvara Q-01 | Båda |
| 4 | Starta Fas 1, uppgift 1.1–1.2 | Claude + den som har tid |

## Blockerare
Inga tekniska. Fas 1 kan börja när punkt 1–3 är klara.
