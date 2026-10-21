#!/usr/bin/env bash
# Run this 10 minutes before a demonstration. It only READS things and prints OK / PROBLEM lines; it changes nothing.
cd "$(dirname "$0")/.." || exit 1
bad=0
ok()   { echo "OK       $1"; }
prob() { echo "PROBLEM  $1"; bad=1; }

[ -x .venv/bin/python ] && ok "Python environment found" || prob "no .venv: see README for setup"
ls models/skin_pad_ufes20/*/checkpoint.pt >/dev/null 2>&1 && ok "trained skin model found" || prob "no trained skin model in models/ (retrain: docs/MODEL_CARD_skin_pad_ufes20.md section 8)"
command -v tesseract >/dev/null && ok "Tesseract (text reading) installed" || prob "Tesseract missing: brew install tesseract"
ls data/synthetic/lab_reports/syn_0001_complete.png >/dev/null 2>&1 && ok "synthetic lab reports found" || prob "no synthetic reports: .venv/bin/python scripts/make_synthetic_lab_reports.py"
ls data/raw/PAD-UFES-20/images/imgs_part_1/*.png >/dev/null 2>&1 && ok "practice skin photos found" || prob "no practice skin photos: pick any PNG/JPEG under 10 MB"
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome installed (needed only for the browser smoke test)" || echo "NOTE     Chrome not found: the browser smoke test cannot run, the demo itself can"
if curl -s -o /dev/null localhost:8000/health; then
  ok "server is running: $(curl -s localhost:8000/health | head -c 120)"
else
  echo "NOTE     server is not running yet: double-click scripts/start_demo.command"
fi
git status --short | head -5 | sed 's/^/NOTE     uncommitted: /'
[ "$bad" = 0 ] && echo "READY" || echo "FIX THE PROBLEMS ABOVE FIRST"
exit $bad
