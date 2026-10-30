# Ekobyn

Buildless dashboard: serve this directory with `python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/dashboard` from `ai-enterprise/`, then visit http://127.0.0.1:8765/.

The six departments have illustrated houses. Select a house or colleague, inspect its exact reported activity, follow the character with the camera, pause animation or toggle speech bubbles. All controls only change the local visualization. No agent, budget, approval or company process is controlled from the page.

`status.json` is produced by the existing daily cycle. The page fetches it every 15 seconds and displays its production timestamp. Walking, proximity hearts and visits are illustrative, not evidence of actual collaboration or continuous execution. If `meeting` is set, active characters gather at the plaza. Emergency stop and protected mode freeze animation. Reduced-motion preferences default to paused. Failed updates retain the previous valid snapshot with a warning.

The site needs all three assets (`index.html`, `world.css`, `world.js`) and the public `status.json`. No external fonts, image services, packages or build step. The existing Pages upload already includes this directory; this change does not enable hosting or real-money operation.

Check the front end with `node --test tests/dashboard_world.cjs` (Node 22+) and the exporter/cycle with `PYTHONPATH=src python3 -m unittest tests.unit.test_dashboard -q`.
