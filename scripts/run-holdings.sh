#!/usr/bin/env bash
# Monthly fund holdings refresh, run by cron on the Mumbai VPS (Indian IP: fund house sites accept it).
# Always records the outcome in data/holdings-status.json so the weekly Freshness check can alert on failures.
set -u
cd "$(dirname "$0")/.."
git pull -q --rebase
out=$(.venv/bin/python scripts/amc.py "$@" 2>&1); code=$?
echo "$out" | tail -40
python3 - "$code" <<'PY'
import datetime as dt, json, sys
json.dump({'lastRun': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'exit': int(sys.argv[1])}, open('data/holdings-status.json', 'w'))
PY
git add data/funds.json data/holdings-status.json
git -c user.name="finai-data vps" -c user.email="vps@users.noreply.github.com" commit -q -m "Fund holdings run $(date +%F) (exit $code)" && git push -q
