# D-057 Research läser kända offentliga webbsidor; inget sök-API förrän R-11 är utrett (förslag)

- **Status:** Föreslagen. Det är inget beslut förrän en grundare har godkänt det och det står i `DECISIONS.md`.
- **Föreslagen av:** Claude (session med Yorgo, arbetsorder 02, PR 5), 2026-10-28
- **Bygger på:** D-011, D-014, D-008
- **Gäller:** SR-06, SR-07, SR-08, SR-02, DR-13, §37

## Problemet
`research.search` fanns bara som ett namn i behörigheterna. Research kunde inte läsa en enda källa,
så "Utred möjlighet" byggde helt på det grundarna klistrade in.

## Förslag
1. **`WebReader`** (`src/aie/research/web.py`) läser en offentlig sida med `urllib`, bakom `AuthorizationEngine`. Därmed gäller rollens mandat, nödstoppet och skyddat läge.
2. **Bara läsning:** GET, ingen inloggning, inga formulär, inga konton, inga betalningar och ingen publicering.
3. **Bara kända värdar** i `config/research.toml`. Det är källorna i registret och Skatteverket. En ny värd läggs till i en PR när villkoren för den är lästa.
4. **SSRF-skydd:** varje adress som värden pekar på måste vara offentlig, även efter varje omdirigering. Högst 3 omdirigeringar.
5. **Gränser och regler:**
   - `robots.txt` följs.
   - Högst 50 hämtningar per dag för alla agenter tillsammans.
   - Högst 500 kB per svar (längre svar kortas av och märks), och 10 sekunders tidsgräns.
   - Bara text, HTML, JSON och XML.
6. **Spårbarhet:** varje försök sparas med URL, datum, utfall, SHA-256 och texten (migration 30, append-only). Innehållet returneras som `ExternalContent`, alltså opålitlig data som aldrig ger behörighet. Försök att styra agenten loggas (SR-06).
7. **Sök-API:** frågan är registrerad som **R-11** i `research/QUESTIONS.md`. Kandidaterna är listade som obekräftade. Inget är kopplat in.
8. **Kommandon:** `python -m aie research fetch <url> --agent <id>` och `python -m aie research history`.

## Att avgöra
- Om listan med värdar och dagskvoten 50 är rimliga.
- Vem som läser villkoren för ett gratis sök-API (R-11) innan något kopplas in.

## Kostnad och risk
- **Kostnad:** ingen. Inga API:er och inga konton.
- **Risk:** en DNS-ändring mellan kontrollen och anslutningen kan inte uteslutas helt. Därför tillåts bara kända värdar.

## Tester
`tests/unit/test_web.py`: 8 tester, alla med ett låtsasnät och inga nätverksanrop. De visar att:
- en sida sparas och ramas in som opålitlig data
- instruktioner i en sida flaggas och inte ger någon behörighet
- fel schema, inloggningsuppgifter, fel port och okända värdar stoppas
- privata adresser stoppas, även efter omdirigering
- `robots.txt` följs
- dagskvot, storleksgräns, innehållstyp, felkoder och antal omdirigeringar begränsas
- roller utan verktyget och nödstopp ger nej
- skyddat läge ger nej
