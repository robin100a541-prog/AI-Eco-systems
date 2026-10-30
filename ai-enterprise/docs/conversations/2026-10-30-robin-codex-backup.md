# Codex: backup och återställningsövning — 2026-10-30

Grundarens uppdrag i samma session: "Can't you do most of these things?"

Codex implementerade privat SQLite-backup med online-backup-API:t, filmanifest och återställningsövning
i en temporär mapp. Ingen befintlig databas återställs över eller raderas. Saknad källa ger fel.
Sex riktade tester gick igenom: WAL-innehåll, ledger/godkännanden/audit, orörd driftdata, korrupt
backup, omhashad men trasig revisionskedja och CLI. Full testsvit och CI dokumenteras i PR:en.
Grundaren behöver fortfarande välja en privat plats utanför datorn för en extra kopia.
Ingen riktig pilotdatabas eller personlig försäljningsdata användes; testerna skapade egna filer.
