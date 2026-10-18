#!/usr/bin/env bash
# Double-click this file in Finder to start LUMI and open the demo page in your browser.
cd "$(dirname "$0")/.." || exit 1
pkill -f "uvicorn lumi.main:app" 2>/dev/null || true   # stop an older copy, if one is still running
sleep 1
# Set LUMI_NO_BROWSER=1 to start the server without opening a browser window (used for testing).
( for _ in $(seq 1 30); do curl -s -o /dev/null localhost:8000/health && break; sleep 1; done; [ -n "${LUMI_NO_BROWSER:-}" ] || open "http://localhost:8000/" ) &
exec ./scripts/run_dev.sh
