#!/usr/bin/env bash
# One-command refresh: re-ingest the raw CSVs, run tests, commit, and (if a
# GitHub remote is connected) push so the live site redeploys.
#
#   ./update.sh                      # auto commit message
#   ./update.sh "Add June BSE file"  # custom commit message
#   ./update.sh --fetch              # also pull fresh preferential-issue and
#                                    # insider data from the NSE API first
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--fetch" ]; then
  shift
  echo "▶ Fetching NSE preferential issues"
  python3 pipeline/fetch_nse_pref.py
  echo
  echo "▶ Fetching NSE insider trading (trailing quarter)"
  python3 pipeline/fetch_nse_insider.py --days 90
  echo
fi

echo "▶ Ingesting raw CSVs → docs/data/*.json"
python3 pipeline/ingest.py

echo
echo "▶ Running tests"
python3 tests/run_tests.py

echo
if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
  echo "✓ No changes to commit."
  exit 0
fi

git add -A
msg="${1:-Update data $(date +%Y-%m-%d)}"
git commit -m "$msg" >/dev/null
echo "✓ Committed: $msg"

if git remote | grep -q '^origin$'; then
  git push
  echo "✓ Pushed to GitHub — Pages will redeploy in ~1 minute."
else
  echo "ℹ No 'origin' remote yet. See README.md → 'Connecting to GitHub' to publish."
fi
