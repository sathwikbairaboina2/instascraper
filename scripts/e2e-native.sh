#!/usr/bin/env bash
# Run the Playwright suite without Docker: uvicorn + next dev on the host,
# against an isolated .e2e/ data directory and the fake adapter.
#
# This is the path verified during development. scripts/e2e.sh is the
# Compose equivalent.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python

export DB_PATH=../.e2e/data/app.db
export MEDIA_DIR=../.e2e/data/media
export SESSION_DIR=../.e2e/data/session
export OUT_DIR_CONTAINER=../.e2e/downloads
export IG_ADAPTER=fake
export PAGE_SIZE=36
export IG_MIN_INTERVAL=0

# Kill whatever is listening on a port, process tree included.
# `kill $!` is not enough: npx and uvicorn both spawn children that survive
# it on Windows, and a leaked server silently serves the next run.
kill_port() {
  local port="$1"
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "
      Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue }
    " >/dev/null 2>&1 || true
  else
    lsof -ti tcp:"$port" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  fi
}

cleanup() {
  kill_port 3000
  kill_port 8000
}
trap cleanup EXIT

# Kill leftovers BEFORE touching .e2e: a server still holding the SQLite
# file makes the rm fail, and set -e then aborts the whole run.
cleanup

rm -rf .e2e
mkdir -p .e2e/data .e2e/downloads

(cd api && "../$PY" scripts/seed_e2e.py)

(cd api && "../$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1) &

(cd web && API_ORIGIN=http://127.0.0.1:8000 npx next dev -H 127.0.0.1 -p 3000) &

for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:3000/api/status >/dev/null 2>&1; then break; fi
done

cd web && npx playwright test "$@"
