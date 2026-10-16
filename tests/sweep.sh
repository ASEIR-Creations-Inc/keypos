#!/bin/bash
# Every suite against the test copy (run ./testenv.sh up first), in the order they need.
# Keeps going past a failing suite and prints a summary; exits 1 if any failed.
cd "$(dirname "$0")"
export CHROME=${CHROME:-/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome}
export BASE=${BASE:-http://127.0.0.1:8095}
SUITES=(
  "python3 check-shell.py" "python3 test-smoke-api.py"
  "python3 test-phase2-api.py" "python3 test-phase3-api.py" "python3 test-phase4-api.py" "python3 test-fixes-api.py"
  "node test-tour.js" "node test-phase2.js" "node test-phase3.js" "node test-phase4.js" "node test-fixes.js"
  "node test-phase5.js" "node test-phase6.js" "node test-daysheet.js" "node test-sheetapp.js" "node test-sheetedit.js" "node test-sheetblocks.js" "node test-sessions.js" "node test-inventory.js" "node test-cosmetic.js"
  "node test-phase1.js"
)
failed=()
for suite in "${SUITES[@]}"; do
  echo "=== $suite"
  $suite || failed+=("$suite")
done
echo
if [ ${#failed[@]} -eq 0 ]; then echo "SWEEP GREEN: ${#SUITES[@]} suites"; else printf 'SWEEP FAILED: %s\n' "${failed[@]}"; exit 1; fi
