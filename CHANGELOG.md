# CHANGELOG

## [0.0.4] — 2026-10-21 — Kanalregister och självständig utredning
### Tillagt
- D-011: agenterna utreder själva nya kanaler och lösningar; grundare godkänner.
- `docs/channels.md`: mall + Gumroad, Etsy och Fiverr.
- Krav FR-25 (totalt 79 krav).

## [0.0.4] — 2026-10-21 — Fiverr, forskningskö och konversationsarkiv
### Tillagt
- Fiverr som tjänstekanal i D-010. D-011 (systemet utreder öppna frågor), D-012 (sessioner arkiveras).
- `research/QUESTIONS.md` (R-01…R-10), `docs/conversations/` med första sessionen.
- Krav FR-25, FR-26 (totalt 80 krav).

## [0.0.3] — 2026-10-21 — Försäljningsplattformar
### Tillagt
- D-010: Gumroad och Etsy som försäljningskanaler (avgifter, moms, AI-regler, DAC7).
- Krav SR-18 och ER-23 (totalt 78 krav).

## [0.0.2] — 2026-10-21 — Gratis modeller och skatt
### Tillagt
- D-008 (gratis språkmodeller via ProviderRouter, ersätter D-005), D-009 (betalda API:er finansieras av realiserad vinst), D-010 (skattespår utan aktiebolag).
- Krav ER-18…ER-22 och DR-12…DR-13 (totalt 76 krav).
- `scripts/llm_smoke_test.py` + `tests/unit/test_llm_smoke.py` (8 tester, totalt 18 gröna).
### Ändrat
- ARCHITECTURE.md: avsnitt om gratis modeller, ProviderRouter, uppgradering till betalda API:er och Tax Engine. Q-05 och Q-06 omformulerade.

## [0.0.1] — 2026-10-21 — Fas 0 påbörjad
### Tillagt
- CONSTITUTION.md (v1.0, oförändrad kopia av grundarnas master prompt).
- REQUIREMENTS.md: 69 krav (24 FR, 17 SR, 17 ER, 11 DR).
- ARCHITECTURE.md: arkitekturförslag, verktygsregister, analys av modellåtkomst.
- DECISIONS.md: D-001…D-007 (föreslagna), Q-01…Q-08.
- ROADMAP.md, PROJECT_STATUS.md, README.md, docs/setup.md, docs/environment.md.
- scripts/check_env.py + tests/unit/test_check_env.py (10 tester, gröna i Claudes Linux-miljö).
