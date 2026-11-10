#!/usr/bin/env bash
# The local web demo, all on this Mac:
#   browser -> Vite dev server :5180 (frontend/, proxies /api) -> backend :8010
#
# The backend runs from this checkout with the settings in .env (AI
# provider, database: the demo database, backend/ticketapp.db unless
# DB_PATH says otherwise). Pid files and logs go to .local/webdemo/
# (gitignored). Ports 8000 and 5173 are left free for other work.
#
# Usage: scripts/webdemo.sh start | stop | status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/.local/webdemo"
BACKEND_PORT=8010
FRONTEND_PORT=5180

mkdir -p "$STATE"

running() { [ -f "$STATE/$1.pid" ] && kill -0 "$(cat "$STATE/$1.pid")" 2>/dev/null; }
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for() {  # name url seconds
  for _ in $(seq "$3"); do
    curl -s --noproxy '*' -m 2 -o /dev/null "$2" && { echo "$1: up ($2)"; return; }
    sleep 1
  done
  echo "$1: not answering, see $STATE/$1.log"; exit 1
}

start_backend() {
  if running backend; then echo "backend: already running"; return; fi
  if listening $BACKEND_PORT; then echo "backend: port $BACKEND_PORT is taken by another process"; exit 1; fi
  [ -f "$ROOT/.env" ] || { echo "backend: no .env (copy .env.example and fill it in)"; exit 1; }
  [ -x "$ROOT/.venv/bin/uvicorn" ] || { echo "backend: no .venv (see README: Run locally)"; exit 1; }
  echo "backend: starting on :$BACKEND_PORT"
  (
    cd "$ROOT"
    nohup .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port $BACKEND_PORT \
      >"$STATE/backend.log" 2>&1 </dev/null &
    echo $! >"$STATE/backend.pid"
  )
  wait_for backend "http://127.0.0.1:$BACKEND_PORT/health" 60
}

start_frontend() {
  if running frontend; then echo "frontend: already running"; return; fi
  if listening $FRONTEND_PORT; then echo "frontend: port $FRONTEND_PORT is taken by another process"; exit 1; fi
  [ -d "$ROOT/frontend/node_modules" ] || { echo "frontend: run npm install in frontend/ first"; exit 1; }
  echo "frontend: starting on :$FRONTEND_PORT"
  (
    cd "$ROOT/frontend"
    API_PROXY="http://localhost:$BACKEND_PORT" \
      nohup npm run dev -- --port $FRONTEND_PORT --strictPort >"$STATE/frontend.log" 2>&1 </dev/null &
    echo $! >"$STATE/frontend.pid"
  )
  wait_for frontend "http://localhost:$FRONTEND_PORT/" 60
}

stop_one() {
  if running "$1"; then
    # npm starts vite as a child: stop the children too.
    pkill -P "$(cat "$STATE/$1.pid")" 2>/dev/null || true
    kill "$(cat "$STATE/$1.pid")" 2>/dev/null || true
    echo "$1: stopped"
  else
    echo "$1: not running"
  fi
  rm -f "$STATE/$1.pid"
}

status_one() {  # name port
  if running "$1"; then
    echo "$1: running (pid $(cat "$STATE/$1.pid"), port $2)"
  elif listening "$2"; then
    echo "$1: not started by this script, but port $2 is in use"
  else
    echo "$1: stopped"
  fi
}

case "${1:-}" in
  start)
    start_backend
    start_frontend
    echo "open http://localhost:$FRONTEND_PORT"
    ;;
  stop)
    stop_one frontend
    stop_one backend
    ;;
  status)
    status_one backend $BACKEND_PORT
    status_one frontend $FRONTEND_PORT
    ;;
  *)
    echo "usage: scripts/webdemo.sh start | stop | status"; exit 2 ;;
esac
