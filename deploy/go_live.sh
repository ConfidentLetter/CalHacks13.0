#!/usr/bin/env bash
# One command to put StudBud online from this Mac via a free Cloudflare quick tunnel.
# Starts the backend (:8000) and the site (:4173) if they are not already running,
# then opens the tunnel and prints the public https://….trycloudflare.com address.
# Keep this window open; Ctrl+C takes the site offline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/synapse_vision/runtime"
mkdir -p "$LOG"

up() { curl -s -o /dev/null -m 3 "$1"; }

if up http://127.0.0.1:8000/api/status; then
  echo "✓ backend already running on :8000"
else
  echo "… starting backend on :8000"
  pkill -f "ffmpeg -hide_banner" 2>/dev/null || true   # a stale Desk View reader keeps the camera black
  (cd "$ROOT/synapse_vision" && source .venv/bin/activate && source env.sh \
    && nohup uvicorn bridge.server:app --host 127.0.0.1 --port 8000 >> "$LOG/server.log" 2>&1 &)
  for _ in $(seq 1 40); do up http://127.0.0.1:8000/api/status && break; sleep 1; done
  up http://127.0.0.1:8000/api/status || { echo "✗ backend did not start, see $LOG/server.log"; exit 1; }
  echo "✓ backend up"
fi

if up http://127.0.0.1:4173/; then
  echo "✓ site already running on :4173"
else
  echo "… building and starting the site on :4173"
  (cd "$ROOT/frontend" && npm run build >/dev/null && nohup npx vite preview --port 4173 >> "$LOG/preview.log" 2>&1 &)
  for _ in $(seq 1 30); do up http://127.0.0.1:4173/ && break; sleep 1; done
  up http://127.0.0.1:4173/ || { echo "✗ site did not start, see $LOG/preview.log"; exit 1; }
  echo "✓ site up"
fi

up http://127.0.0.1:4173/api/status || { echo "✗ the site cannot reach the backend through its proxy"; exit 1; }
echo "✓ site → backend proxy works"
echo
echo "Opening the Cloudflare tunnel. Your public address is the https://….trycloudflare.com line below."
echo "Anyone with it can use the app, see the desk camera stream, and spend the Claude key. Ctrl+C to go offline."
echo
exec cloudflared tunnel --url http://127.0.0.1:4173 --no-autoupdate
