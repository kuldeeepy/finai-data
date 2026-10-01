# Refuse a rates file that shrank, went stale, or has a USD/INR rate outside a sane band.
import csv, datetime as dt, sys
new, old = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open(new)) if float(r['TT BUY'] or 0) > 0]
prev = sum(1 for _ in open(old)) if old else 0
last = rows[-1]
rate, day = float(last['TT BUY']), dt.date.fromisoformat(last['DATE'][:10])
problems = []
if sum(1 for _ in open(new)) < prev: problems.append(f'file shrank ({prev} → fewer rows)')
if not 70 <= rate <= 130: problems.append(f'rate {rate} outside 70–130')
if (dt.date.today() - day).days > 5: problems.append(f'last rate is from {day}')
prev_rate = float(rows[-2]['TT BUY'])
if abs(rate - prev_rate) / prev_rate > 0.03: problems.append(f'rate moved {prev_rate} → {rate} in a day')
if problems: sys.exit('rates rejected: ' + '; '.join(problems))
print(f'ok: {rate} on {day}, {len(rows)} rows')
