#!/usr/bin/env bash
# start.sh — start the resume tailor server and n8n together.
# Usage: ./start.sh

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/server.log"

# ── Kill any leftover server from a previous run ──────────────────────────────
if [ -f "$DIR/.server.pid" ]; then
    OLD_PID=$(cat "$DIR/.server.pid")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping previous server (PID $OLD_PID)..."
        kill "$OLD_PID"
    fi
    rm -f "$DIR/.server.pid"
fi

# ── Start Flask server in background ─────────────────────────────────────────
echo "Starting resume tailor server on http://localhost:5001..."
cd "$DIR"
python3 server.py >> "$LOG" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$DIR/.server.pid"

# Wait until /health responds (max 10s)
for i in $(seq 1 20); do
    if curl -s http://localhost:5001/health | grep -q "ok"; then
        echo "Server ready (PID $SERVER_PID). Logs → $LOG"
        break
    fi
    sleep 0.5
done

if ! curl -s http://localhost:5001/health | grep -q "ok"; then
    echo "ERROR: Server did not start. Check $LOG"
    exit 1
fi

# ── Trap: kill server when this script exits (Ctrl-C or n8n stops) ────────────
cleanup() {
    echo ""
    echo "Shutting down server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null
    rm -f "$DIR/.server.pid"
}
trap cleanup EXIT

# ── Start n8n (foreground — blocks until Ctrl-C) ─────────────────────────────
echo "Starting n8n..."
echo ""
n8n start
