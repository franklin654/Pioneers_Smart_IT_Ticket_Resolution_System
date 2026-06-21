#!/usr/bin/env bash
# Launch TicketIQ in production mode (nginx, pre-built assets).
# Usage: ./launch.sh [--build] [--down]
#   --build   force image rebuild before starting
#   --down    stop and remove containers instead of starting

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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
  bold "Stopping TicketIQ stack..."
  docker compose down
  green "Stack stopped."
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
# Tear down any stale containers first to avoid "port already in use" errors
# from a previous interrupted startup leaving containers in Created state.
docker compose down --remove-orphans 2>/dev/null || true

bold "Starting TicketIQ (production mode)..."
# shellcheck disable=SC2086
docker compose up $BUILD_FLAG -d

bold "Waiting for services to be healthy..."
for service in postgres api; do
  timeout=60
  while [[ $timeout -gt 0 ]]; do
    status=$(docker compose ps --format json "$service" 2>/dev/null \
      | python3 -c "import sys,json; data=sys.stdin.read().strip(); rows=json.loads('['+data.replace('}\n{','},{').replace('\n','').rstrip(',')+']') if data else []; print(rows[0].get('Health','') if rows else '')" 2>/dev/null || true)
    [[ "$status" == "healthy" ]] && break
    sleep 2
    (( timeout -= 2 ))
  done
  if [[ $timeout -le 0 ]]; then
    red "Service '$service' did not become healthy in time."
    red "Check logs: docker compose logs $service"
    exit 1
  fi
done

green ""
green "✓ TicketIQ is up!"
bold ""
bold "  Frontend   →  http://localhost"
bold "  API docs   →  http://localhost:8000/api/docs"
bold "  Prometheus →  http://localhost:9090"
bold "  Grafana    →  http://localhost:3000"
bold ""
bold "  Stop:  ./launch.sh --down"
bold "  Logs:  docker compose logs -f"
