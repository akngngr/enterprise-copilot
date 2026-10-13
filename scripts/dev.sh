#!/usr/bin/env bash
# Local dev launcher: FastAPI on :8000, Streamlit on :8501.
# Usage:  ./scripts/dev.sh start | stop | status
set -uo pipefail

cd "$(dirname "$0")/.."
PY=./venv/bin
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-8501}"
RUN_DIR="${TMPDIR:-/tmp}/enterprise-copilot-dev"
mkdir -p "$RUN_DIR"

stop() {
    # Kill by PID from the pidfiles rather than by pattern: a pattern like
    # `streamlit` also matches the shell running this script.
    local n=0
    for f in "$RUN_DIR"/*.pid; do
        [ -e "$f" ] || continue
        local pid; pid=$(cat "$f" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && n=$((n + 1))
        fi
        rm -f "$f"
    done
    sleep 2
    echo "stopped $n process(es)"
}

start() {
    set -a; . ./.env; set +a

    "$PY/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" \
        >"$RUN_DIR/api.log" 2>&1 &
    echo $! >"$RUN_DIR/api.pid"

    "$PY/streamlit" run app/frontend.py \
        --server.address=127.0.0.1 --server.port="$UI_PORT" --server.headless=true \
        >"$RUN_DIR/ui.log" 2>&1 &
    echo $! >"$RUN_DIR/ui.pid"

    # Wait for both to answer rather than sleeping a fixed amount.
    local waited=0
    while [ "$waited" -lt 60 ]; do
        local api ui
        api=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health" 2>/dev/null)
        ui=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$UI_PORT/" 2>/dev/null)
        if [ "$api" = "200" ] && [ "$ui" = "200" ]; then
            echo "ready in ${waited}s"
            return 0
        fi
        sleep 1; waited=$((waited + 1))
    done

    echo "did not become ready in 60s"
    echo "--- api.log ---"; tail -15 "$RUN_DIR/api.log"
    echo "--- ui.log ---";  tail -15 "$RUN_DIR/ui.log"
    return 1
}

status() {
    for f in "$RUN_DIR"/*.pid; do
        [ -e "$f" ] || continue
        pid=$(cat "$f")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$(basename "$f" .pid): running (pid $pid)"
        else
            echo "$(basename "$f" .pid): dead (pid $pid)"
        fi
    done
    echo "api  -> $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health" 2>/dev/null)"
    echo "ui   -> $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$UI_PORT/" 2>/dev/null)"
}

case "${1:-start}" in
    start)  start ;;
    stop)   stop ;;
    restart) stop; start ;;
    status) status ;;
    logs)   tail -40 "$RUN_DIR/ui.log" ;;
    *) echo "usage: $0 start|stop|restart|status|logs"; exit 2 ;;
esac