# vendor: tredjepartsfiler i kommandocentralen (D-084)

Grundarna valde biblioteken 2026-11-09. Filerna hämtades som färdigbyggda filer, utan npm och utan att klona repona.
- **Varifrån de laddas:** från serverns egen adress (`/vendor/...`). Inget laddas från ett CDN, så Content-Security-Policy förblir `default-src 'self'`. Sedan Command Center (2026-11-09) ligger mappen i `ai-enterprise/command-center/vendor/` och laddas från `/vendor/...`.
- **Oförändrade:** filerna är exakt som de hämtades. SHA-256 står nedan, och testet `tests/unit/test_dashboard_server.py` kontrollerar att de stämmer.
- **Uppdatera ett bibliotek:** lägg den nya versionen i en ny versionsmapp, uppdatera sökvägen i `command-center/index.html` och tabellen nedan, och ta bort den gamla mappen i samma PR.

| Fil | Bibliotek och version | Källa | Licens | Syfte | SHA-256 |
|---|---|---|---|---|---|
| `gsap/3.15.1/gsap.min.js` | GSAP 3.15.1, kärnan (taggad 2026-11-04, `latest` på npm) | https://raw.githubusercontent.com/greensock/GSAP/3.15.1/dist/gsap.min.js | GSAP Standard "No Charge" License, se `gsap/3.15.1/LICENSE.md` | Alla animationer: panelernas inträde, sidövergångar, uppräknande siffror, statusbyten, och radarns rörelser när radarn byggs | `3d1bea374ab1b703cc5c4105358eec63c4465efdc573931dc116e34a0a190c1b` |
| `gsap/3.15.1/LICENSE.md` | — | skriven här med hänvisning till https://gsap.com/standard-license | — | Licensuppgift. GSAP har ingen egen licensfil | — |
| `lenis/1.3.27/lenis.min.js` | Lenis 1.3.27 (släppt 2026-10-15, `latest` på npm) | npm-paketet `lenis@1.3.27`, filen `dist/lenis.min.js`, hämtad över https från jsDelivr och kontrollerad mot unpkg (samma SHA-256). GitHub-repot innehåller ingen byggd fil | MIT, se `lenis/1.3.27/LICENSE` | Mjuk scroll för sidans huvudscroll, bara på desktop | `80f53e77f1c13e379fc246d2b5e299188e20bcb2b2fe7ebb13e8e8c7563a6da7` |
| `lenis/1.3.27/lenis.css` | Lenis 1.3.27 | npm-paketet `lenis@1.3.27`, `dist/lenis.css` | MIT | Lenis rekommenderade CSS (bland annat `data-lenis-prevent`) | `2f668ae84a668327f246faf8a770383a2bf69196d214290fbc4d5548910606c5` |
| `lenis/1.3.27/LICENSE` | Lenis | https://raw.githubusercontent.com/darkroomengineering/lenis/v1.3.27/LICENSE | MIT | Licensfil | `7d1896b31f2eed9f286b05faca067c4e35b2f109ae7c4ed5105220e2d2820228` |
| `react-bits/LICENSE.md` | React Bits, commit `b0422bb` (2026-11-08) | https://raw.githubusercontent.com/davidhdev/react-bits/main/LICENSE.md | MIT + Commons Clause | Licensen för de tre effekter som är ombyggda i `command-center/js/effects.js` | `4bdd1fa59a6b7d5954bc3b213dbc34e455c635a94bbcecf9293553797d0fad02` |

## Det som inte används
- **GSAP:s ScrollTrigger** hämtades inte. Sidorna har inga scrollstyrda animationer, och panelerna kommer in när sidan laddas. Den hämtas om ett senare steg behöver den.
- **React Bits installeras inte,** eftersom vi inte använder React. Tre effekter är ombyggda i vanlig JavaScript och CSS i `command-center/js/effects.js` och `command-center/assets/css/app.css`. Källan och licensen står i en kommentar överst i filen.
  - **CountUp** (`src/content/TextAnimations/CountUp/CountUp.jsx`) blev `countUp`. Siffror räknas upp en gång när de syns, med ease-out och utan fjädring. Skärmläsare får slutvärdet.
  - **SpotlightCard** (`src/content/Components/SpotlightCard/SpotlightCard.jsx`) blev `spotlight`. Ett mjukt guldljus följer pekaren och lyser upp kanten. Det fungerar bara med mus, och används på väntande godkännanden nu och på agentkorten i D3.
  - **AnimatedList** (`src/content/Components/AnimatedList/AnimatedList.jsx`, varianten "fade") blev `listIn` och `listAdd`. Raderna tonar in med 4 px rörelse. `listAdd` är till för live-flödet i D2.

## Licensvillkor att följa
- **React Bits (MIT + Commons Clause):**
  - Komponenterna får användas som en del av en applikation, även kommersiellt.
  - Upphovsrättsraden och licenstexten ska följa med kopior av väsentliga delar. Det görs genom `react-bits/LICENSE.md` och kommentaren i `effects.js`.
  - Vi får **inte** sälja, underlicensiera eller sprida komponenterna själva, varken ensamma, i ett paket eller som en portad version.
  - Repot är publikt tills det görs privat (D-074). De ombyggda effekterna ligger bara som en del av appen och publiceras inte som ett eget bibliotek.
- **GSAP:** upphovsrättsmärkningen i `gsap.min.js` får inte tas bort, och GSAP får inte användas i ett verktyg för att bygga animationer som konkurrerar med Webflow.
- **Lenis (MIT):** licensfilen följer med.

## Regler för rörelse
Reglerna står i `docs/dashboard/DESIGN.md` under "Rörelse".
- **Längd och kurva:** rörelserna är korta, 0,15–0,35 s och sällan upp till 1,1 s för siffror. De använder ease-out och studsar aldrig.
- **Mening:** inget rör sig utan att betyda något.
- **`prefers-reduced-motion`:** då visas slutläget direkt och Lenis är avstängt.
- **Lenis:**
  - **På:** bara på desktop med mus.
  - **Av:** på touch och vid reducerad rörelse.
  - **Aldrig i** tabeller, chatt, modaler och rullbara paneler, alltså element som är märkta `data-lenis-prevent`, `table`, `dialog`, `.chat` eller `.scroll-panel`.
