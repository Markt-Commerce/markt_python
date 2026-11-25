#!/usr/bin/env bash
# One command from nothing to a seeded local backend for the product video.
#
#   scripts/demo_up.sh           # build/start, migrate, seed (idempotent)
#   scripts/demo_up.sh --fresh   # wipe the demo database first (undoes
#                                # orders placed during earlier takes)
#   scripts/demo_up.sh --down    # stop everything (keeps data)
#
# API on http://localhost:8000/api/v1, seeded media on http://localhost:8090.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker-compose.demo.yml)

case "${1:-}" in
  --down) "${COMPOSE[@]}" down; exit 0 ;;
  --fresh) "${COMPOSE[@]}" down -v --remove-orphans ;;
  "") ;;
  *) echo "usage: $0 [--fresh|--down]" >&2; exit 2 ;;
esac

mkdir -p demo/media demo/images
"${COMPOSE[@]}" up -d --build postgres redis media api worker

printf "waiting for the API"
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8000/api/v1/health >/dev/null; then echo " ok"; break; fi
  printf "."; sleep 2
done
curl -sf http://localhost:8000/api/v1/health >/dev/null || { echo " API never came up"; "${COMPOSE[@]}" logs --tail 50 api; exit 1; }

run() { "${COMPOSE[@]}" exec -T -e MARKT_DEMO=1 api "$@"; }

run flask db upgrade
if [ "$(run python -c 'from main.setup import create_flask_app
from app.categories.models import Category
with create_flask_app().app_context(): print(Category.query.count())' 2>/dev/null | tail -1)" = "0" ]; then
  run flask populate-categories
fi
# --allow-remote: these scripts treat any DB_HOST but localhost as remote; here
# it is the demo container ("postgres"), which is as local as it gets.
run python scripts/seed_delivery_areas.py --allow-remote --activate
run python scripts/seed_markets_and_areas.py --allow-remote
run python scripts/seed_demo.py 2>&1 | grep -vE "\[(INFO|WARNING)\]|^\[20|^\s*$"

echo
echo "Backend ready: http://localhost:8000/api/v1  (media: http://localhost:8090)"
