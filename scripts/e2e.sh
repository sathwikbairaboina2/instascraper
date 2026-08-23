#!/usr/bin/env bash
# Run the Playwright suite against a throwaway Compose stack using the fake
# adapter. Requires a running Docker daemon.
#
# scripts/e2e-native.sh does the same thing without Docker.
set -euo pipefail

cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=instascraper-e2e
export IG_ADAPTER=fake
export OUT_DIR=./.e2e/downloads

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.e2e.yml"

rm -rf .e2e
mkdir -p .e2e/data .e2e/downloads

cleanup() {
  $COMPOSE down -v
}
trap cleanup EXIT

$COMPOSE up -d --build
$COMPOSE run --rm api python scripts/seed_e2e.py

for _ in $(seq 1 60); do
  if curl -sf http://localhost:3000/api/status >/dev/null 2>&1; then break; fi
  sleep 1
done

cd web && npx playwright test "$@"
