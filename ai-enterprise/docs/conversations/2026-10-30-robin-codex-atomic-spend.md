# Codex: H4/M1 — 2026-10-30

Grundarens uppdrag i samma session: "Can't you do most of these things?"

Utgiftskontroll, godkännandeförbrukning och ledgerpost har kopplats i en atomär metod. Arbetscykeln använder den, med bevarad riskklass/kategori och ny mandatkontroll. Migration 35 reserverades och pushades före implementationen. Inga riskvärden eller mandat ändrades.

750 tester OK på Python 3.15.0 (71,401 s), inklusive fyra nya samtidighets-/avbrotts-/klassificeringstester. Tidigare godkännandetest har uppdaterats: en förhandsbedömning lämnar godkännandet oanvänt; den atomära bokföringen förbrukar det en gång. Klassificering anges uttryckligen i testförfrågningar. Oberoende granskning före riktiga pengar kvarstår.
