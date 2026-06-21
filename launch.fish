#!/usr/bin/env fish
# Launch TicketIQ in production mode (nginx, pre-built assets).
# Usage: ./launch.fish [--build] [--down]
#   --build   force image rebuild before starting
#   --down    stop and remove containers instead of starting

set SCRIPT_DIR (dirname (status --current-filename))
cd $SCRIPT_DIR

# ── helpers ────────────────────────────────────────────────────────────────────
function red;   printf '\033[0;31m%s\033[0m\n' $argv; end
function green; printf '\033[0;32m%s\033[0m\n' $argv; end
function bold;  printf '\033[1m%s\033[0m\n' $argv; end

# ── flags ──────────────────────────────────────────────────────────────────────
set BUILD_FLAG ""
set DO_DOWN 0

for arg in $argv
  switch $arg
    case --build
      set BUILD_FLAG --build
    case --down
      set DO_DOWN 1
    case '*'
      red "Unknown argument: $arg"
      exit 1
  end
end

# ── stop mode ─────────────────────────────────────────────────────────────────
if test $DO_DOWN -eq 1
  bold "Stopping TicketIQ stack..."
  docker compose down
  green "Stack stopped."
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
bold "Starting TicketIQ (production mode)..."
docker compose up $BUILD_FLAG -d

bold "Waiting for services to be healthy..."
for service in postgres api
  set timeout 60
  while test $timeout -gt 0
    set status (docker compose ps --format json $service 2>/dev/null \
      | python3 -c "import sys,json; data=sys.stdin.read().strip(); rows=json.loads('['+data.replace('}\n{','},{').replace('\n','').rstrip(',')+']') if data else []; print(rows[0].get('Health','') if rows else '')" 2>/dev/null; or echo "")
    if test "$status" = healthy
      break
    end
    sleep 2
    set timeout (math $timeout - 2)
  end
  if test $timeout -le 0
    red "Service '$service' did not become healthy in time."
    red "Check logs: docker compose logs $service"
    exit 1
  end
end

green ""
green "✓ TicketIQ is up!"
bold ""
bold "  Frontend   →  http://localhost"
bold "  API docs   →  http://localhost:8000/api/docs"
bold "  Prometheus →  http://localhost:9090"
bold "  Grafana    →  http://localhost:3000"
bold ""
bold "  Stop:  ./launch.fish --down"
bold "  Logs:  docker compose logs -f"
