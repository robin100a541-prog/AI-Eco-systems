# Codex: tekniskt arbete inför driftsättning — 2026-10-30

## Grundarens meddelande (ordagrant)

> Can't you do most of these things?

## Svar och genomfört arbete

Codex svarade att de tekniska delarna kan utföras och började rätta granskningsfynden. Detta uppfattas som ny instruktion att utföra fixarna efter det tidigare beskedet att avvakta. Konton, identitet, skattebesked, externa villkor och beslut om verkliga pengar lämnas till grundaren.

H1–H3 och M2 har rättats i en egen PR: atomär pilotimport med savepoints, händelsedatum separat från registreringsdatum, returer som separata händelser och idempotenta avstämningsincidenter. Migration 34 reserverades och pushades före kodändringarna. Inga riskvärden eller behörighetsmandat ändrades.

Verifiering: 746 tester OK på Python 3.15.0 (82,203 s), inklusive 10 nya tester för avbrott, returer, årsskifte, ledgeravstämning, ogiltiga data, savepoints och uppgradering av schema 33. Rapporten är inte en oberoende granskning av den nya koden.
