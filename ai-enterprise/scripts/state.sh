#!/usr/bin/env bash
# Krypterad kopia av en databas i Cloudflare KV (Command Center Del 1, DATA.md avsnitt 7).
#   scripts/state.sh pull <namn> <databasfil>   # bara om filen saknas (cachen missade): hämta och dekryptera
#   scripts/state.sh push <namn> <databasfil>   # efter körningen: checkpoint, kryptera och ladda upp
# Kryptering: openssl AES-256-CBC med PBKDF2 (200 000 varv) och nyckeln i STATE_KEY. Klartext lämnar aldrig runnern.
# Saknas STATE_KEY eller Cloudflare-hemligheterna hoppas steget över utan fel: agenterna stoppas aldrig av det här.
set -uo pipefail
action="$1"; name="$2"; db="$3"
enc="${RUNNER_TEMP:-/tmp}/state-${name}.enc"

if [ -z "${STATE_KEY:-}" ] || [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "state ${action} ${name}: STATE_KEY eller CLOUDFLARE_API_TOKEN saknas; hoppar över"
  exit 0
fi

case "$action" in
  pull)
    if [ -s "$db" ]; then echo "state pull ${name}: databasen finns redan (cache)"; exit 0; fi
    python -m aie state get "$name" "$enc"; rc=$?
    if [ $rc -eq 3 ]; then echo "::warning::state pull ${name}: ingen kopia i KV; en ny databas skapas"; exit 0; fi
    if [ $rc -ne 0 ]; then echo "::error::state pull ${name}: kunde inte hämta kopian ur KV"; exit 0; fi
    mkdir -p "$(dirname "$db")"
    if openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:STATE_KEY -in "$enc" -out "$db"; then
      echo "state pull ${name}: återställd från KV"
    else
      rm -f "$db"; echo "::error::state pull ${name}: dekrypteringen misslyckades (fel STATE_KEY?)"
    fi
    rm -f "$enc"
    ;;
  push)
    if [ ! -s "$db" ]; then echo "state push ${name}: ingen databas"; exit 0; fi
    python - "$db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
PY
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:STATE_KEY -in "$db" -out "$enc" \
      && python -m aie state put "$name" "$enc"
    rm -f "$enc"
    ;;
  *) echo "okänd åtgärd $action"; exit 2 ;;
esac
exit 0
