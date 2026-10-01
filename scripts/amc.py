# Builds src/data/funds.json from each AMC's official monthly portfolio disclosure (SEBI-mandated Excel files).
# Setup: python3 -m venv .venv && .venv/bin/pip install pandas openpyxl xlrd
# Run:   python scripts/amc.py [--month 2026-08] [--dry]   (default month: the previous calendar month)
# Exit:  0 = all funds fresh, 2 = written but some funds kept last month's data or were skipped, 1 = nothing written.
# A fund that fails keeps its previous entry (with its old asOf) so one broken AMC link never drops it from the site.
import calendar, datetime as dt, functools, io, json, re, sys, tempfile, urllib.parse, urllib.request, zipfile
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/funds.json'
SOURCES = json.loads((Path(__file__).parent / 'sources.json').read_text())
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'}
TMP = Path(tempfile.gettempdir()) / 'finai-holdings'
TMP.mkdir(exist_ok=True)
NON_EQUITY = re.compile(r'debt|money market|treps|reverse repo|cblo|government|treasury|t-bill|derivative|future|option|mutual fund unit|reit|invit|investment trust|cash|net (current|receivable)|margin|fixed deposit|commercial paper|certificate of deposit|bond|debenture', re.I)


def month_fields(arg):
    if arg: y, m = map(int, arg.split('-'))
    else: t = dt.date.today().replace(day=1) - dt.timedelta(days=1); y, m = t.year, t.month
    last = dt.date(y, m, calendar.monthrange(y, m)[1])
    nxt = last + dt.timedelta(days=1)
    d = last.day
    return {'Y': y, 'y': f'{y % 100:02}', 'm': f'{m:02}', 'd': d, 'dth': f"{d}{'st' if d == 31 else 'th'}", 'Month': last.strftime('%B'),
            'month': last.strftime('%B').lower(), 'Mon': last.strftime('%b'), 'mon': last.strftime('%b').lower(),
            'nY': nxt.year, 'nm': f'{nxt.month:02}', 'nmon': nxt.strftime('%b').lower(), 'asOf': last.isoformat()}


def http(url, data=None, headers={}):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers=UA | ({'Content-Type': 'application/json'} if data is not None else {}) | headers)
    with urllib.request.urlopen(req, timeout=120) as r: return r.read()


def fetch(url):
    # Cached in the OS temp dir so reruns don't redownload.
    path = TMP / re.sub(r'[^A-Za-z0-9._-]+', '_', url.split('?')[0])[-150:]
    if not path.exists():
        data = http(url)
        if data[:2] != b'PK' and data[:4] != bytes.fromhex('d0cf11e0'): raise ValueError(f'not an Excel/zip file (soft 404?): {url}')  # xlsx/zip or legacy xls
        path.write_bytes(data)
    return path


# One resolver per AMC that hides its file behind an API: returns the download URL for the month.
@functools.cache
def icici_url(Month, Y):
    body = {'categoryId': '26a073d7-08d2-4a95-95fa-f83a4ee51e40', 'schemeCategory': '', 'userType': 'Investor', 'fileType': 'All', 'page': '1', 'size': '50', 'filter': [], 'categoryName': 'OTHERS'}
    hdr = {'origin': 'https://www.icicipruamc.com', 'referer': 'https://www.icicipruamc.com/', 'accept': 'application/json, text/plain, */*', 'sourceurl': 'DOWNLOADS', 'env': 'api'}
    files = json.loads(http('https://apimf.icicipruamc.com/nms/v1/downloads/files', body, hdr))['success']['data']['files']
    f = next((f for f in files if f['title']['text'].strip().lower() == f'monthly portfolio disclosure {Month} {Y}'.lower()), None)
    if not f: raise LookupError(f'ICICI has no file for {Month} {Y} yet')
    return 'https://www.icicipruamc.com/blob' + urllib.parse.quote(f['url'])  # without /blob it redirects to a dead host


@functools.cache
def axis_url(Month, Y, d, m):
    token = json.loads(http('https://www.axismf.com/cms/token', {}))['data']['token']
    body = {'sdType': 'yearMonthSchemeDocs', 'sdID': 'sdMonthSchemePortfolio', 'year': str(Y), 'month': Month, 'schemeCode': 'Consolidated'}
    docs = json.loads(http('https://www.axismf.com/cms/get-scheme-documents', body, {'authorization': token}))['data']['documentList']
    f = next((f for f in docs if f['documentName'].strip() == f'Monthly Portfolio {d}-{m}-{Y}'), None)
    if not f: raise LookupError(f'Axis has no monthly portfolio for {d}-{m}-{Y} yet')
    return f['docuementURL']  # sic


@functools.cache
def uti_url(Month, Y):
    rows = json.loads(http(f'https://www.utimf.com/api/get-consolidate-portfolio-disclosure?year={Y}&month={Month}'))['rows']
    if not rows: raise LookupError(f'UTI has no file for {Month} {Y} yet')
    return rows[0]['url']


@functools.cache
def uti_book(path):
    # One EXPOSURE sheet holding every scheme, each wrapped in "SCHEME CODExxxSTARTS" ... "ENDS" rows.
    with zipfile.ZipFile(path) as z:
        df = pd.read_excel(io.BytesIO(z.read(next(n for n in z.namelist() if re.search(r'exposure', n, re.I)))), header=None)
    starts = [i for i, v in df[0].items() if re.fullmatch(r'SCHEME CODE\w+STARTS', str(v).strip())] + [len(df)]
    return {str(df.iat[a, 0]): df.iloc[a:b].reset_index(drop=True) for a, b in zip(starts, starts[1:])}


def load_book(s, M):
    src = s.get('source', 'url')
    if src == 'uti': return uti_book(fetch(uti_url(M['Month'], M['Y'])))
    if src == 'hdfc':  # listing page is Akamai-blocked but the files are public and named predictably
        url = f"https://files.hdfcfund.com/s3fs-public/{M['nY']}-{M['nm']}/" + urllib.parse.quote(f"Monthly {s['file']} - {M['d']} {M['Month']} {M['Y']}.xlsx")
    elif src == 'icici': url = icici_url(M['Month'], M['Y'])
    elif src == 'axis': url = axis_url(M['Month'], M['Y'], M['d'], M['m'])
    else: url = s['url'].format(**M)
    return open_book(fetch(url), s.get('member'))


def open_book(path, member=None):
    data = path.read_bytes()
    if data[:2] == b'PK' and member:  # zip of per-scheme files
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next(n for n in z.namelist() if re.search(member, n.split('/')[-1], re.I))
            data = z.read(name)
    return pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)


def pick_sheet(book, sheet):
    if sheet in book: return book[sheet]
    # Otherwise match a regex against the sheet name or its first rows (scheme title).
    for name, df in book.items():
        head = ' '.join(str(v) for v in df.head(6).values.ravel() if pd.notna(v))
        if re.search(sheet, name, re.I) or re.search(sheet, head, re.I): return df
    raise KeyError(f'no sheet matching {sheet!r} in {list(book)[:10]}')


def parse(df):
    # Header row = the first row with a cell saying ISIN; columns found by their labels.
    hr = next(i for i, row in df.iterrows() if any(str(v).strip().upper() == 'ISIN' or str(v).strip().upper().startswith('ISIN') for v in row))
    hdr = [re.sub(r'\s+', ' ', str(v)).strip().lower() for v in df.iloc[hr]]
    c_isin = next(i for i, h in enumerate(hdr) if h.startswith('isin'))
    c_name = next(i for i, h in enumerate(hdr) if re.search(r'name|instrument|issuer|company|security', h) and i != c_isin)
    c_pct = next(i for i, h in enumerate(hdr) if re.search(r'% ?(to|of)? ?(net ?assets|nav|aum)|%.*net asset|% to nav|% of nav', h))
    rows, in_equity = [], True
    for _, row in df.iloc[hr + 1:].iterrows():
        name, isin, pct = str(row.iloc[c_name]).strip(), str(row.iloc[c_isin]).strip().upper(), row.iloc[c_pct]
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', isin):
            if name and name != 'nan':  # section heading: equity until a non-equity block starts
                if NON_EQUITY.search(name) and not re.search(r'equity', name, re.I): in_equity = False
                elif re.search(r'equity|foreign sec', name, re.I) and not NON_EQUITY.search(name): in_equity = True
            continue
        if not in_equity: continue
        try: w = float(pct)
        except (TypeError, ValueError): continue
        # Indian equity shares have security code 01 (chars 8-9); IN9 = partly paid; non-IN = foreign stock.
        if isin.startswith('INE') and isin[7:9] != '01' or isin.startswith('IN') and not isin.startswith(('INE', 'IN9')): continue  # IN0.. = govt securities
        if w > 0: rows.append((isin, name, w))
    return rows


def clean_name(n):
    n = re.sub(r'^EQ\s*-\s*', '', n.strip(), flags=re.I)  # UTI prefixes every stock with "EQ - "
    n = re.sub(r'\s*\((partly paid|pp|rights?)[^)]*\)', '', n, flags=re.I)
    n = re.sub(r'[\s,]+(limited|ltd|inc|corp(oration)?|plc|co\.? ltd)\.?$', '', n.strip(), flags=re.I)
    return re.sub(r'\s+', ' ', n).strip()


def pretty(isin, n):
    if not isin.startswith('IN'):  # foreign listings carry share-class noise: "Alphabet Inc A", "Amazon Com"
        while True:
            m = re.sub(r'[\s,]+(registered shares|ordinary shares|common stock|class [a-c]|adr|inc\.?|com|corp\.?|co\.?|plc|sa|nv|ag|ltd\.?|[a-c])$', '', n, flags=re.I)
            if m == n: break
            n = m
    if n.isupper():  # ALL-CAPS names: title-case words, keep short or vowel-less ones (ITC, NHPC) as acronyms
        n = ' '.join(w.lower() if w in ('AND', 'OF') else w if len(w) <= 4 or not re.search(r'[AEIOU]', w) else w.capitalize() for w in n.split())
    return n


M = month_fields(sys.argv[sys.argv.index('--month') + 1] if '--month' in sys.argv else None)
print(f"portfolio month {M['asOf']}", flush=True)
prev = {f['id']: f for f in json.loads(OUT.read_text())['funds']} if OUT.exists() else {}

funds, problems = [], 0
for s in SOURCES['funds']:
    try:
        rows = parse(pick_sheet(load_book(s, M), s['sheet']))
        total = sum(w for _, _, w in rows)
        scale = 100 if total < 2 else 1  # some AMCs publish fractions (0.0763), others percent (7.63)
        merged = {}
        for isin, name, w in rows:
            key = isin[:7] if isin.startswith(('INE', 'IN9')) else isin  # issuer code folds partly-paid/rights into the main share
            m = merged.setdefault(key, {'isin': isin, 'name': clean_name(name), 'weight': 0})
            if m['isin'].startswith('IN9') and isin.startswith('INE'): m['isin'], m['name'] = isin, clean_name(name)
            m['weight'] += w * scale
        holdings = sorted(({**h, 'weight': round(h['weight'], 3)} for h in merged.values()), key=lambda h: -h['weight'])
        eq = sum(h['weight'] for h in holdings)
        if not 15 <= len(holdings) <= 400 or not 60 <= eq <= 101: raise ValueError(f'{len(holdings)} stocks, equity {eq:.1f}% looks wrong')
        funds.append({k: s[k] for k in ('id', 'name', 'amc', 'aliases', 'category')} | {'asOf': M['asOf'], 'holdings': holdings})
        print(f"ok    {s['id']:34} {len(holdings):3} stocks  equity {eq:5.1f}%", flush=True)
    except Exception as e:
        problems += 1
        old = prev.get(s['id'])
        if old: funds.append(old | {k: s[k] for k in ('name', 'amc', 'aliases', 'category')})
        print(f"{'stale' if old else 'skip '} {s['id']:34} {type(e).__name__}: {str(e)[:160]}" + (f"  (keeping {old['asOf']})" if old else ''), flush=True)

# Same ISIN can be spelled differently by each AMC: pick one name per ISIN.
best = {}
# Prefer no junk ("Elec.", "( I )", "Limited", SHOUTING words; short acronyms like BSE are fine), then shortest ignoring punctuation (Divi's over Divis).
rank = lambda n: (bool(re.search(r'\.$|\( |(?i:limited)|\b(?!ICICI)[A-Z]{5,}\b', n)), len(re.sub(r'[^A-Za-z0-9]', '', n)), -len(n))
for f in funds:
    for h in f['holdings']:
        if h['isin'] not in best or rank(h['name']) < rank(best[h['isin']]): best[h['isin']] = h['name']
for f in funds:
    for h in f['holdings']: h['name'] = pretty(h['isin'], best[h['isin']])

if '--dry' in sys.argv: sys.exit(2 if problems else 0)  # parse and report only
# Failed funds keep last month's data, so judge by how many parsed fresh; removing a fund from sources.json is fine.
fresh = len(SOURCES['funds']) - problems
if fresh < len(SOURCES['funds']) / 2: sys.exit(f'only {fresh} of {len(SOURCES["funds"])} funds parsed, not overwriting funds.json')
out = {'asOf': max(f['asOf'] for f in funds), 'source': 'AMC monthly portfolio disclosures', 'funds': funds}
OUT.write_text(json.dumps(out, ensure_ascii=False))
print(f'wrote {len(funds)} funds, {problems} problem(s)')
sys.exit(2 if problems else 0)
