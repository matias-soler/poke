#!/usr/bin/env bash
# adb-style wrapper: auto-starts poked when needed and forwards client commands.
#
# Usage:
#   ./poke.sh start-server           start poked in the background
#   ./poke.sh kill-server            stop the running poked
#   ./poke.sh restart-server         kill + start
#   ./poke.sh server-status          print pid / running state
#   ./poke.sh <any poke subcommand>  auto-starts poked if needed, then runs `poke ...`
#
# Examples:
#   ./poke.sh press a
#   ./poke.sh unpress a
#   ./poke.sh status
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

VENV="$REPO/.venv"
if [[ ! -d "$VENV" ]]; then
    echo "poke.sh: .venv not found; run 'python3 -m venv .venv && .venv/bin/pip install -e .[test]' first" >&2
    exit 1
fi

POKED="$VENV/bin/poked"
POKE="$VENV/bin/poke"
CONFIG="$REPO/config.toml"

SOCKET_DIR="${XDG_RUNTIME_DIR:-$HOME/.poke}"
SOCKET="$SOCKET_DIR/poked.sock"
PIDFILE="$SOCKET_DIR/poked.pid"
LOGFILE="$SOCKET_DIR/poked.log"

mkdir -p "$SOCKET_DIR"

is_running() {
    [[ -f "$PIDFILE" ]] || return 1
    local pid
    pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null
}

start_server() {
    if is_running; then
        echo "* poked already running (pid $(cat "$PIDFILE")) *"
        return 0
    fi
    rm -f "$PIDFILE" "$SOCKET"
    nohup "$POKED" --config "$CONFIG" >"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 50); do
        if [[ -S "$SOCKET" ]]; then
            echo "* poked started (pid $(cat "$PIDFILE")) *"
            return 0
        fi
        if ! is_running; then
            echo "poked exited during startup; see $LOGFILE" >&2
            tail -n 20 "$LOGFILE" >&2 || true
            rm -f "$PIDFILE"
            return 1
        fi
        sleep 0.1
    done
    echo "poked failed to create socket within 5s; see $LOGFILE" >&2
    return 1
}

kill_server() {
    if ! is_running; then
        echo "* poked not running *"
        rm -f "$PIDFILE"
        return 0
    fi
    local pid
    pid=$(cat "$PIDFILE")
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PIDFILE"
            echo "* poked stopped *"
            return 0
        fi
        sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$PIDFILE" "$SOCKET"
    echo "* poked killed (SIGKILL) *" >&2
}

ensure_running() {
    if ! is_running; then
        echo "* daemon not running; starting it now at $SOCKET *" >&2
        start_server >&2
    fi
}

case "${1:-}" in
    start-server)
        start_server
        ;;
    kill-server|stop-server)
        kill_server
        ;;
    restart-server)
        kill_server
        start_server
        ;;
    server-status)
        if is_running; then
            echo "running (pid $(cat "$PIDFILE"), socket $SOCKET)"
        else
            echo "not running"
            exit 1
        fi
        ;;
    ""|--help|-h|help)
        cat <<EOF
poke.sh — adb-style wrapper around poked + poke

Server commands:
  start-server     Start poked in the background.
  kill-server      Stop the running poked (alias: stop-server).
  restart-server   Kill, then start.
  server-status    Print pid and socket if running; exit 1 otherwise.

Client commands (auto-start the daemon if not running):
  press <button>      e.g. ./poke.sh press a
  unpress <button>
  status
  stop
  raw-turn <motor> <power> <degrees>

Paths:
  socket  $SOCKET
  pidfile $PIDFILE
  log     $LOGFILE
EOF
        ;;
    *)
        ensure_running
        exec "$POKE" "$@"
        ;;
esac
