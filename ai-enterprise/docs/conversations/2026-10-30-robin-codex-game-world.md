# Ekobyn — 2026-10-30

Robin bad om en rejäl uppdatering till ett tecknat spel där varje avdelning har en bas och hus, agenter kan gå runt och interagera, och deras aktiviteter alltid syns.

Byggt direkt i den befintliga dashboarden med SVG, CSS och beroendefri JavaScript. Visningen är kopplad till samma offentliga statusdata som tidigare; animerade promenader och sociala möten är märkta som illustrationer. Datakällans faktiska aktivitet finns i bubblor, agentpanel och aktivitetslista. Ingen kontinuerlig körning, pilot eller publicering aktiveras av detta.

Verifiering: åtta Node-regressionstester (rörelse, paus, stopp, följkamera, uppdatering/fel, tomma/nya avdelningar, textinjektion), sex exporter-/cykeltester samt lokal webbläsarkontroll. Se PR för CI.
