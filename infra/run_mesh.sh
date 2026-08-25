#!/usr/bin/env bash
# Bring the three local card specimens up, one per port.
#
#   ./infra/run_mesh.sh start     # start all three (direct mode, no credentials)
#   ./infra/run_mesh.sh stop
#   ./infra/run_mesh.sh status
#
# They serve cards and echo messages. No model, no credentials, no spend --
# which is what lets them be the control the deployed cards are read against.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# System interpreter, not a virtualenv -- see CLAUDE.md.
PYTHON="${PYTHON:-python3}"
RUN_DIR="${RUN_DIR:-$REPO/.run}"
AGENTS=("gcp:11001" "aws:11002" "azure:11003")

mkdir -p "$RUN_DIR"

start() {
  for entry in "${AGENTS[@]}"; do
    local name="${entry%%:*}" port="${entry##*:}"
    local pidfile="$RUN_DIR/$name.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      echo "$name already running (pid $(cat "$pidfile"))"
      continue
    fi
    env PORT="$port" \
      nohup "$PYTHON" -m "agents.$name.server" \
      >"$RUN_DIR/$name.log" 2>&1 &
    echo $! >"$pidfile"
    echo "$name starting on :$port (pid $!)"
  done
  echo "waiting for health..."
  for entry in "${AGENTS[@]}"; do
    local name="${entry%%:*}" port="${entry##*:}"
    local pidfile="$RUN_DIR/$name.pid" pid
    pid="$(cat "$pidfile" 2>/dev/null || echo 0)"
    for _ in $(seq 1 40); do
      # The pid check comes first, and it is the whole point. A health check
      # alone says only that *something* answers on that port. On 2026-08-24
      # this script reported three agents ready while all three had died on
      # "address already in use" -- another project's mesh was on those ports,
      # and the first card comparison this repo produced was of the wrong
      # agents. A start that cannot tell whose server it reached is not a start.
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "  $name DIED on startup -- see $RUN_DIR/$name.log" >&2
        tail -3 "$RUN_DIR/$name.log" >&2 || true
        break
      fi
      if curl -sf -m 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
        echo "  $name ready"
        break
      fi
      sleep 0.5
    done
  done
}

stop() {
  for entry in "${AGENTS[@]}"; do
    local name="${entry%%:*}"
    local pidfile="$RUN_DIR/$name.pid"
    if [[ -f "$pidfile" ]]; then
      local pid
      pid="$(cat "$pidfile")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" && echo "$name stopped (pid $pid)"
      fi
      rm -f "$pidfile"
    fi
  done
}

status() {
  for entry in "${AGENTS[@]}"; do
    local name="${entry%%:*}" port="${entry##*:}"
    if curl -sf -m 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "$name  :$port  up"
    else
      echo "$name  :$port  DOWN   (see $RUN_DIR/$name.log)"
    fi
  done
}

# Stop one agent, to exercise degradation rather than assert it.
kill_one() {
  local name="${1:?usage: kill <gcp|aws|azure>}"
  local pidfile="$RUN_DIR/$name.pid"
  [[ -f "$pidfile" ]] || { echo "$name is not running" >&2; return 1; }
  local pid; pid="$(cat "$pidfile")"
  kill "$pid" 2>/dev/null && echo "$name killed (pid $pid)"
  rm -f "$pidfile"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  kill) kill_one "${2:-}" ;;
  *) echo "usage: $0 {start|stop|restart|status|kill <agent>}" >&2; exit 2 ;;
esac
