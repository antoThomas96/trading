import sys, glob, os, collections, numpy as np
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
import engine as E
D = sys.argv[1]
d = E.load(D, 'measured'); ts = d['ts']; gap = np.diff(ts) / 60
# missing minutes per month inside the week (gaps < 24h), as % of expected minutes
miss = collections.Counter(); have = collections.Counter()
for i in range(len(ts)):
    m = E.utc(ts[i]).strftime('%Y-%m'); have[m] += 1
    if i < len(gap) and 1 < gap[i] < 24 * 60: miss[m] += gap[i] - 1
print('month    bars    missing-min  missing%   (gaps >= 1h)')
hourgaps = collections.Counter(E.utc(ts[i]).strftime('%Y-%m') for i in np.where((gap >= 60) & (gap < 24*60))[0])
for m in sorted(have):
    tot = have[m] + miss[m]
    flag = '  <-- holes' if miss[m] / tot > 0.02 else ''
    print(f'{m}  {have[m]:>7,}  {int(miss[m]):>9,}   {100*miss[m]/tot:5.1f}%   {hourgaps[m]:>4}{flag}')
# duplicates in raw files
seen = {}; dup_same = dup_diff = 0; dup_where = collections.Counter()
for f in sorted(glob.glob(os.path.join(D, 'DAT_ASCII_EURUSD_M1_*.csv'))):
    prev = None
    for line in open(f):
        p = line.strip().split(';'); k = p[0]
        if k in seen:
            dup_where[(os.path.basename(f), k[:6])] += 1
            if seen[k] == p[1:5]: dup_same += 1
            else: dup_diff += 1
        seen[k] = p[1:5]
print(f'\nduplicate timestamps: identical rows {dup_same}, different prices {dup_diff}')
print('where:', dict(collections.Counter(k[1] for k in dup_where.elements())))
# big 1-minute moves: across a gap or genuine?
cc = np.abs(np.diff(d['c'])) / 1e-4
idx = np.where(cc > 30)[0]
across_gap = sum(1 for i in idx if gap[i] > 1)
print(f'\n1-minute close-to-close moves > 30 pips: {len(idx)}; across a time gap: {across_gap}; between adjacent minutes: {len(idx)-across_gap}')
adj = [i for i in idx if gap[i] == 1]
for i in sorted(adj, key=lambda i: -cc[i])[:8]: print('   ', E.utc(ts[i+1]), f'{cc[i]:.1f} pips')
