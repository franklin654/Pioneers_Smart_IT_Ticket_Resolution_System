#!/usr/bin/env fish
# Launch TicketIQ in development mode (hot reload, Vite dev server).
# Usage: ./launch-dev.fish [--build] [--down]
#   --build   force image rebuild before starting
#   --down    stop and remove containers instead of starting

set SCRIPT_DIR (dirname (status --current-filename))
cd $SCRIPT_DIR

set COMPOSE_FILES -f docker-compose.yml -f docker-compose.dev.yml

# ── helpers ────────────────────────────────────────────────────────────────────
function red;   printf '\033[0;31m%s\033[0m\n' $argv; end
function green; printf '\033[0;32m%s\033[0m\n' $argv; end
function bold;  printf '\033[1m%s\033[0m\n' $argv; end

# ── flags ──────────────────────────────────────────────────────────────────────
set do_build 0
set do_down 0

for arg in $argv
  switch $arg
    case --build
      set do_build 1
    case --down
      set do_down 1
    case '*'
      red "Unknown argument: $arg"
      exit 1
  end
end

# ── stop mode ─────────────────────────────────────────────────────────────────
if test $do_down -eq 1
  bold "Stopping TicketIQ dev stack..."
  docker compose $COMPOSE_FILES down
  green "Dev stack stopped."
  exit 0
end

# ── pre-flight checks ─────────────────────────────────────────────────────────
if not command -q docker
  red "Docker is not installed or not in PATH."
  exit 1
end

if not docker compose version &>/dev/null
  red "Docker Compose V2 is required (docker compose, not docker-compose)."
  exit 1
end

if not test -f .env
  red ".env file not found. Copy .env.example and fill in the required values:"
  red "  cp .env.example .env"
  exit 1
end

# ── launch ────────────────────────────────────────────────────────────────────
docker compose $COMPOSE_FILES down --remove-orphans 2>/dev/null; or true

bold "Starting TicketIQ (dev mode — hot reload enabled)..."
if test $do_build -eq 1
  docker compose $COMPOSE_FILES up --build -d
else
  docker compose $COMPOSE_FILES up -d
end

bold "Waiting for Postgres to be healthy..."
set svc_timeout 60
while test $svc_timeout -gt 0
  set health (docker compose ps --format json postgres 2>/dev/null \
    | python3 -c "import sys,json; data=sys.stdin.read().strip(); rows=json.loads('['+data.replace('}\n{','},{').replace('\n','').rstrip(',')+']') if data else []; print(rows[0].get('Health','') if rows else '')" 2>/dev/null; or echo "")
  if test "$health" = healthy
    break
  end
  sleep 2
  set svc_timeout (math $svc_timeout - 2)
end
if test $svc_timeout -le 0
  red "Postgres did not become healthy in time. Check: docker compose logs postgres"
  exit 1
end

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
bold "  Stop:  ./launch-dev.fish --down"
bold "  Logs:  docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f"
