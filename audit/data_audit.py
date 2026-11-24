import sys, glob, os, datetime as dt, collections, numpy as np
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
import engine as E
D = sys.argv[1]
# ---- raw-file checks (before any conversion) ----
raw = []; bad_parse = 0; files = sorted(glob.glob(os.path.join(D, 'DAT_ASCII_EURUSD_M1_*.csv')))
for f in files:
    for line in open(f):
        p = line.strip().split(';')
        if len(p) != 6: bad_parse += 1; continue
        raw.append((p[0], *map(float, p[1:5]), p[5]))
print(f'files {len(files)} | rows {len(raw):,} | unparseable lines {bad_parse}')
stamps = [r[0] for r in raw]
dups = len(stamps) - len(set(stamps))
print(f'duplicate timestamps: {dups}')
unsorted = sum(1 for a, b in zip(stamps, stamps[1:]) if b <= a)
print(f'out-of-order rows: {unsorted}')
o = np.array([r[1] for r in raw]); h = np.array([r[2] for r in raw]); l = np.array([r[3] for r in raw]); c = np.array([r[4] for r in raw])
print(f'high < low: {(h < l).sum()} | open outside [low,high]: {((o > h) | (o < l)).sum()} | close outside: {((c > h) | (c < l)).sum()}')
print(f'non-positive prices: {((o<=0)|(h<=0)|(l<=0)|(c<=0)).sum()} | price range {l.min():.5f} .. {h.max():.5f}')
print(f'volume values: {collections.Counter(r[5] for r in raw).most_common(3)}')
print(f'flat bars (O=H=L=C): {((o==h)&(h==l)&(l==c)).sum():,} ({100*((o==h)&(h==l)&(l==c)).mean():.1f}%)')
rng = (h - l) / 1e-4
print(f'1-min bar range pips: median {np.median(rng):.1f}, 99.9th pct {np.percentile(rng,99.9):.1f}, max {rng.max():.1f}')
# ---- after conversion ----
d = E.load(D, 'measured')
ts = d['ts']
gap = np.diff(ts) / 60
# within-session gaps (exclude weekend gaps > 24h)
inside = gap[(gap > 1) & (gap < 24 * 60)]
print(f'\nminute gaps inside the week: {len(inside):,} gaps; sizes: '
      + ', '.join(f'{k}: {v}' for k, v in sorted(collections.Counter(np.select([inside<=5, inside<=60, inside<=240], ['2-5 min','6-60 min','1-4 h'], '>4 h')).items())))
big = [(E.utc(ts[i]), gap[i]) for i in np.where((gap > 60) & (gap < 24 * 60))[0]]
print('gaps > 1 hour inside the week (UTC start, minutes):')
for t, g in big[:40]: print('   ', t, int(g))
print(f'   ... total {len(big)}')
# jumps between consecutive bars
jump = np.abs(d['o'][1:] - d['c'][:-1]) / 1e-4
idx = np.argsort(jump)[-10:][::-1]
print('\nlargest close->next-open jumps (pips):')
for i in idx: print('   ', E.utc(ts[i]), '->', E.utc(ts[i+1]), f'{jump[i]:.1f}')
spike = np.abs(d['c'][1:] - d['c'][:-1]) / 1e-4
print(f'close-to-close moves > 30 pips in 1 minute: {(spike > 30).sum()}')
# trading days per week
days = collections.Counter()
for td in set(d['tday'].tolist()):
    dd = dt.date.fromordinal(td); days[dd - dt.timedelta(dd.weekday())] += 1
short = sorted((k, v) for k, v in days.items() if v < 5)
print(f'\nweeks: {len(days)} | weeks with < 5 trading days: {len(short)}')
for k, v in short: print('   ', k, v, 'days')
bars_per_day = collections.Counter(d['tday'].tolist())
thin = sorted((dt.date.fromordinal(k), v) for k, v in bars_per_day.items() if v < 1000)
print(f'trading days with < 1000 one-minute bars (of ~1440): {len(thin)}')
for k, v in thin: print('   ', k, k.strftime('%a'), v)
