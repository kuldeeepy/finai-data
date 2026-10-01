# Fails when fund holdings are old, the monthly VPS job failed or stopped running, or SBI rates are more than 5 days old.
import csv, datetime as dt, json, sys
today = dt.date.today()
funds = json.load(open('data/funds.json'))
holdings_age = (today - dt.date.fromisoformat(funds['asOf'])).days
stale = [f['id'] for f in funds['funds'] if (today - dt.date.fromisoformat(f['asOf'])).days > 75]
rows = [r for r in csv.DictReader(open('data/sbi-usd-ttbr.csv')) if float(r['TT BUY'] or 0) > 0]
rates_age = (today - dt.date.fromisoformat(rows[-1]['DATE'][:10])).days
problems = []
if holdings_age > 75: problems.append(f'fund holdings are {holdings_age} days old (as of {funds["asOf"]})')
if stale: problems.append(f'{len(stale)} funds stale: {", ".join(stale)}')
if rates_age > 5: problems.append(f'SBI rates are {rates_age} days old')
status = json.load(open('data/holdings-status.json'))
ran = (today - dt.date.fromisoformat(status['lastRun'][:10])).days
if status['exit'] == 1: problems.append(f'last holdings run failed and wrote nothing ({status["lastRun"]})')
if status['exit'] == 2: problems.append('last holdings run left some funds stale, see the run log on the VPS')
if ran > 40: problems.append(f'holdings job has not run for {ran} days (VPS down?)')
if problems: sys.exit('\n'.join(problems))
print(f'ok: holdings as of {funds["asOf"]} ({len(funds["funds"])} funds), rates {rates_age}d old')
