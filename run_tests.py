"""Null control + Wednesday-close short, following the analysis brief.

Usage: python3 run_tests.py <CSV_DIR> [tz_mode measured|spec] [cost_pips]
"""
import sys
import datetime as dt
import numpy as np
import engine as E

CSV, TZ = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "measured")
COST = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
d = E.load(CSV, TZ)
N = len(d["ts"])
print(f"=== tz mode: {TZ} | bars kept {N:,} | bars dropped outside FX week {d['dropped']:,} | cost {COST} pips round trip")
print(f"    data {E.utc(d['ts'][0])} -> {E.utc(d['ts'][-1])} UTC\n")


def fmt(s, unit="R"):
    be = f"{100*s['breakeven_wr']:.1f}%" if s.get("breakeven_wr") is not None else "n/a"
    return (f"trades {s['n']} | ambiguous bars {s['ambiguous']} | targets {s['targets']} stops {s['stops']} time {s['time_exits']} | "
            f"win {100*s['win_rate']:.1f}% (break-even {be}) | avg {s['avg_unit']:+.3f}{unit} t={s['t']:+.2f} | "
            f"halves {s['first_half']:+.1f}/{s['second_half']:+.1f} | net {s['net_pips']:+.1f} pips")


# ---------------- NULL CONTROL ----------------
# Long every Tuesday 10:00 UTC: signal on the 09:59 bar, fill at the open of the 10:00 bar
# (next bar), hold 24 one-minute bars, exit at the close of the 24th bar. No stop, no target.
null = []
day_of = np.array([E.utc(t).date() for t in d["ts"]])
mins = (d["ts"] % 86400) // 60
for i in range(1, N - 24):
    if day_of[i].weekday() == 1 and mins[i] == 600 and mins[i - 1] == 599:
        # 24 bars must be contiguous minutes (no gap swallowed into the hold)
        if d["ts"][i + 23] - d["ts"][i] == 23 * 60:
            null.append(E.simulate(d, i, +1, None, None, i + 23, COST, optimistic=False))
s = E.stats(null, COST, use_r=False)
print("NULL CONTROL  long Tue 10:00 UTC, hold 24 x 1-min bars, no stops")
print("   " + fmt(s, unit=" pips"))
se = np.std([t['net'] for t in null], ddof=1) / np.sqrt(len(null))
dev = (s['avg_unit'] + COST) / se
gross_up = np.mean([t['gross'] > 0 for t in null]); gross_dn = np.mean([t['gross'] < 0 for t in null])
print(f"   gross (before cost): up {100*gross_up:.1f}% / down {100*gross_dn:.1f}% / flat {100*(1-gross_up-gross_dn):.1f}%, avg {np.mean([t['gross'] for t in null]):+.3f} pips")
print(f"   expected avg -{COST} pips: observed {s['avg_unit']:+.3f}, which is {dev:+.2f} standard errors from -{COST}  ->  "
      f"{'OK (within 2 SE)' if abs(dev) < 2 else 'CHECK ENGINE'}\n")

# ---------------- STRATEGY ----------------
# Week filter: Wednesday open < Monday open (trading days roll at 17:00 New York).
# Signal: last bar of Wednesday. Fill: SHORT at the open of the first Thursday bar.
# Exit: stop / target, else close of the last Thursday bar.
tdays = d["tday"]
first_idx, last_idx = {}, {}
for i, td in enumerate(tdays):
    first_idx.setdefault(int(td), i)
    last_idx[int(td)] = i
days = sorted(first_idx)
setups = []
for td in days:
    date = dt.date.fromordinal(td)
    if date.weekday() != 3:  # Thursday
        continue
    mon, wed = td - 3, td - 1
    if mon not in first_idx or wed not in first_idx:
        continue
    mon_open = d["o"][first_idx[mon]]
    wed_open = d["o"][first_idx[wed]]
    if not wed_open < mon_open:
        continue
    wi0, wi1 = first_idx[wed], last_idx[wed]
    wed_low = d["l"][wi0:wi1 + 1].min()
    entry_i = first_idx[td]
    assert entry_i == wi1 + 1, "signal bar must be the bar right before the fill bar"
    setups.append(dict(day=date, entry_i=entry_i, last_i=last_idx[td], wed_low=wed_low))
print(f"STRATEGY  Wed open < Mon open -> SHORT at Thursday's first-bar open; manage to Thursday close")
print(f"   qualifying weeks: {len(setups)} ({setups[0]['day']} .. {setups[-1]['day']})\n")
small = sum(1 for st in setups if 0 < (d["o"][st["entry_i"]] - st["wed_low"]) / E.PIP / 2 < 2)
print(f"   note: {small} setups have R < 2 pips (Wednesday closed within 4 pips of its low); the 0.8-pip cost alone is > 0.4R on those\n")


def run_fixed(stop, target, optimistic):
    out = []
    for st in setups:
        e = d["o"][st["entry_i"]]
        out.append(E.simulate(d, st["entry_i"], -1, e + stop * E.PIP, e - target * E.PIP, st["last_i"], COST, optimistic))
    return out


def run_dynamic(k, optimistic):
    """Target = Wednesday low (= 2R); stop = k*R above entry."""
    out = []
    for st in setups:
        e = d["o"][st["entry_i"]]
        if e <= st["wed_low"]:
            continue  # already at/below target at the fill: no trade
        R = (e - st["wed_low"]) / 2
        out.append(E.simulate(d, st["entry_i"], -1, e + k * R, st["wed_low"], st["last_i"], COST, optimistic))
    return out


# (a) the version you tested last: target = Wednesday low (2R), stop = 2R; plus neighbours
print("(a) Target = Wednesday low (2R), stop = k x R   [your last version is k = 2]")
dyn = {}
for k in (0.5, 1, 1.5, 2, 3, 4):
    p, o = E.stats(run_dynamic(k, False), COST), E.stats(run_dynamic(k, True), COST)
    dyn[k] = p
    print(f"   k={k:<3} PESSIMISTIC {fmt(p)}")
    print(f"         OPTIMISTIC  {fmt(o)}")
print()

# (b) fixed stop/target grid in pips, break-even win rate computed BEFORE running
stops = [5, 10, 15, 20, 30, 40]
targets = [5, 10, 15, 20, 30, 40, 60]
print("(b) Fixed stop/target grid (pips). Break-even win rate = (stop + cost) / (stop + target):")
print("   stop\\tgt " + "".join(f"{t:>8}" for t in targets))
for s_ in stops:
    print(f"   {s_:>8} " + "".join(f"{100*(s_+COST)/(s_+t):>7.1f}%" for t in targets))
print()
grid = {}
for s_ in stops:
    for t in targets:
        grid[(s_, t)] = (E.stats(run_fixed(s_, t, False), COST), E.stats(run_fixed(s_, t, True), COST))


def table(title, key, f):
    print(f"   {title}")
    print("   stop\\tgt " + "".join(f"{t:>8}" for t in targets))
    for s_ in stops:
        print(f"   {s_:>8} " + "".join(f"{f(grid[(s_, t)][key]):>8}" for t in targets))
    print()


table("trades (pessimistic)", 0, lambda s: f"{s['n']}")
table("ambiguous bars (stop & target in same minute)", 0, lambda s: f"{s['ambiguous']}")
table("win rate, PESSIMISTIC", 0, lambda s: f"{100*s['win_rate']:.0f}%")
table("t-statistic of avg R, PESSIMISTIC", 0, lambda s: f"{s['t']:+.2f}")
table("net pips, PESSIMISTIC", 0, lambda s: f"{s['net_pips']:+.0f}")
table("net pips, OPTIMISTIC", 1, lambda s: f"{s['net_pips']:+.0f}")

pos = [(k, v[0]) for k, v in grid.items() if v[0]["net_pips"] > 0]
table("avg R, PESSIMISTIC", 0, lambda s: f"{s['avg_unit']:+.3f}")
pos = [k for k, v in grid.items() if v[0]["avg_unit"] > 0]
print(f"   cells with avg R > 0 on pessimistic: {len(pos)} of {len(grid)}")
best = max(grid.items(), key=lambda kv: kv[1][0]["avg_unit"])
(bs, bt), (bp, bo) = best
nbrs = [(s_, t) for s_ in stops for t in targets
        if (s_, t) != (bs, bt) and abs(stops.index(s_) - stops.index(bs)) <= 1 and abs(targets.index(t) - targets.index(bt)) <= 1]
plateau = all(grid[x][0]["avg_unit"] > 0 for x in nbrs)
print(f"   best pessimistic cell: stop {bs} / target {bt}: {fmt(bp)}")
print(f"   its {len(nbrs)} neighbours all positive (plateau)? {plateau}\n")

print("PASS MARK")
for label, s_p, plat in (("(a) k=2 (your last version)", dyn[2], all(dyn[k]['avg_unit'] > 0 for k in (1.5, 2, 3))),
                         (f"(b) best grid cell {bs}/{bt}", bp, plateau)):
    checks, v = E.verdict(s_p, plat)
    print(f"   {label}: {v}")
    for c_, ok in checks.items():
        print(f"      [{'x' if ok else ' '}] {c_}")
