# Live-status — 2026-10-30

Robin vill se vad agenterna faktiskt gör live, vad de borde göra och möten där deltagarna samlas, utan löpande tokenspill.

Byggt en valbar, offentlig observatör kring samma gateway/webbläsare och simulationens arbetssteg. Den lägger inga nya modell- eller webbanrop och ändrar inga kvoter eller körscheman. Daily-cycle skriver status under arbetet; simulate och pilot discover kan kopplas till samma lokala JSON-fil med --dashboard.

Gör nu är faktisk kodfas, Borde göra är en uttryckligen märkt rollplan och Senaste rapport är historik. Endast faktiska deltagare i konfliktcykelns bedömningsmöte går till torget. Öppna tvister är inte i sig levande möten. Telemetrin exporterar inga råa instruktioner, svar, uppgiftstitlar eller felorsaker.

Heartbeat-tråden läser bara en cachad snapshot, aldrig SQLite. Vid tio sekunders uteblivet livstecken visar UI kontaktbortfall och fryser figurerna. JSON ersätts atomärt, en skrivare äger varje fil och skrivfel får inte ändra företagets arbete.

Lokalt verifierat med beroendefria Node-tester och Python-tester, bland annat en skriptad fyra dagars konfliktcykel med CFO/CRO/CEO. Alla modell-/nätverksanrop är testdubblar eller den skriptade providern. GitHub Pages är statiskt; riktig fjärr-live kräver separat backend och ingår inte här.
