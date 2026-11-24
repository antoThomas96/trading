import sys, json, collections, numpy as np
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
import engine as E
D, F = sys.argv[1], sys.argv[2]
td = {}
for line in json.load(open(F))['result'].splitlines()[1:]:
    p = line.split(';'); td[p[0]] = tuple(map(float, p[1:5]))
print('Twelve Data daily bars:', len(td), min(td), '->', max(td))
for mode in ('measured', 'spec'):
    d = E.load(D, mode)
    hd = {}
    for i in range(len(d['ts'])):
        k = E.utc(d['ts'][i]).strftime('%Y-%m-%d')
        o, h, l, c = d['o'][i], d['h'][i], d['l'][i], d['c'][i]
        if k not in hd: hd[k] = [o, h, l, c]
        else: x = hd[k]; x[1] = max(x[1], h); x[2] = min(x[2], l); x[3] = c
    common = sorted(k for k in hd if k in td and k >= '2023-01-02')
    diff = {f: np.array([abs(hd[k][j] - td[k][j]) / 1e-4 for k in common]) for j, f in enumerate('OHLC')}
    print(f'\n[{mode}] days compared: {len(common)}')
    for f in 'OHLC':
        a = diff[f]; print(f'   {f}: median |diff| {np.median(a):.1f} pips | 95th pct {np.percentile(a,95):.1f} | days > 10 pips: {(a>10).sum()}')
    if mode == 'measured':
        bad = [k for k in common if max(diff[f][common.index(k)] for f in 'HL') > 10]
        by_month = collections.Counter(k[:7] for k in bad)
        print('   days where high or low differs by > 10 pips, by month:', dict(sorted(by_month.items())))
        hole = [k for k in common if '2023-02' <= k[:7] <= '2023-07']
        clean = [k for k in common if not ('2023-02' <= k[:7] <= '2023-07')]
        for name, ks in (('Feb-Jul 2023 (holes)', hole), ('all other months', clean)):
            hl = np.array([max(abs(hd[k][1]-td[k][1]), abs(hd[k][2]-td[k][2]))/1e-4 for k in ks])
            print(f'   {name}: {len(ks)} days, median worst high/low diff {np.median(hl):.1f} pips, days > 10 pips {(hl>10).sum()} ({100*(hl>10).mean():.0f}%)')
