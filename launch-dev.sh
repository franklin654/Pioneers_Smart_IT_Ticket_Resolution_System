#!/usr/bin/env bash
# Launch TicketIQ in development mode (hot reload, Vite dev server).
# Usage: ./launch-dev.sh [--build] [--down]
#   --build   force image rebuild before starting
#   --down    stop and remove containers instead of starting

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml"

# ── helpers ────────────────────────────────────────────────────────────────────
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

# ── flags ──────────────────────────────────────────────────────────────────────
BUILD_FLAG=""
DO_DOWN=0

for arg in "$@"; do
  case "$arg" in
    --build) BUILD_FLAG="--build" ;;
    --down)  DO_DOWN=1 ;;
    *) red "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── stop mode ─────────────────────────────────────────────────────────────────
if [[ $DO_DOWN -eq 1 ]]; then
  bold "Stopping TicketIQ dev stack..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES down
  green "Dev stack stopped."
  exit 0
fi

# ── pre-flight checks ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  red "Docker is not installed or not in PATH."
  exit 1
fi

if ! docker compose version &>/dev/null; then
  red "Docker Compose V2 is required (docker compose, not docker-compose)."
  exit 1
fi

if [[ ! -f .env ]]; then
  red ".env file not found. Copy .env.example and fill in the required values:"
  red "  cp .env.example .env"
  exit 1
fi

# ── launch ────────────────────────────────────────────────────────────────────
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES down --remove-orphans 2>/dev/null || true

bold "Starting TicketIQ (dev mode — hot reload enabled)..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up $BUILD_FLAG -d

bold "Waiting for Postgres to be healthy..."
timeout=60
while [[ $timeout -gt 0 ]]; do
  status=$(docker compose ps --format json postgres 2>/dev/null \
    | python3 -c "import sys,json; data=sys.stdin.read().strip(); rows=json.loads('['+data.replace('}\n{','},{').replace('\n','').rstrip(',')+']') if data else []; print(rows[0].get('Health','') if rows else '')" 2>/dev/null || true)
  [[ "$status" == "healthy" ]] && break
  sleep 2
  (( timeout -= 2 ))
done
if [[ $timeout -le 0 ]]; then
  red "Postgres did not become healthy in time. Check: docker compose logs postgres"
  exit 1
fi

green ""
green "✓ TicketIQ dev stack is up!"
bold ""
bold "  Frontend   →  http://localhost:5173  (Vite HMR)"
bold "  API        →  http://localhost:8000  (uvicorn --reload)"
bold "  API docs   →  http://localhost:8000/api/docs"
bold "  Prometheus →  http://localhost:9091"
bold "  Grafana    →  http://localhost:3001  (anonymous admin, no login)"
bold ""
bold "  Source changes in backend/src/ and frontend/src/ reload automatically."
bold ""
bold "  Stop:  ./launch-dev.sh --down"
bold "  Logs:  docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f"
