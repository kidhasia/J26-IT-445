#!/usr/bin/env bash
# Start the LUMI API locally for development.
# Uses the project's .venv (Python 3.12) and a local-only API key unless LUMI_API_KEYS is already set.
set -euo pipefail
cd "$(dirname "$0")/.."

export LUMI_API_KEYS="${LUMI_API_KEYS:-dev:local-dev-key-not-for-production}"
echo "Local API key for testing:  Authorization: Bearer ${LUMI_API_KEYS#*:}"
echo "Interactive docs:           http://localhost:${PORT:-8000}/docs"

exec .venv/bin/uvicorn lumi.main:app --reload --port "${PORT:-8000}"
