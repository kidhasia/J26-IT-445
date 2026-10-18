#!/usr/bin/env bash
# Start the LUMI API and the local demo page for development.
# Uses the project's .venv (Python 3.12) and a local-only API key unless LUMI_API_KEYS is already set.
# If no skin model is configured, the newest trained checkpoint under models/skin_pad_ufes20/ is used (if any).
set -euo pipefail
cd "$(dirname "$0")/.."

DEV_KEY="local-dev-key-not-for-production"
export LUMI_API_KEYS="${LUMI_API_KEYS:-dev:$DEV_KEY}"
export LUMI_DEMO_UI="${LUMI_DEMO_UI:-1}"
# Pre-fill the key in the demo page only when the throw-away development key is in use.
if [ "$LUMI_API_KEYS" = "dev:$DEV_KEY" ]; then export LUMI_DEMO_UI_KEY="${LUMI_DEMO_UI_KEY:-$DEV_KEY}"; fi

if [ -z "${LUMI_SKIN_MODEL_PATH:-}" ]; then
  # Only folders that really contain a checkpoint count (the folder also holds a cache/ directory). Run ids are dates, so the last sorts newest.
  latest="$(ls models/skin_pad_ufes20/*/checkpoint.pt 2>/dev/null | sort | tail -1 || true)"
  if [ -n "$latest" ]; then export LUMI_SKIN_MODEL_PATH="$PWD/$latest"; fi
fi

PORT="${PORT:-8000}"
echo "Demo page:        http://localhost:$PORT/"
echo "API docs:         http://localhost:$PORT/docs"
echo "API key (local):  ${LUMI_API_KEYS#*:}"
echo "Skin model:       ${LUMI_SKIN_MODEL_PATH:-none (skin photos will get a 503 'model_unavailable' answer)}"
echo "Stop the server with Ctrl+C."

exec .venv/bin/uvicorn lumi.main:app --reload --port "$PORT"
