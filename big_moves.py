"""Find EUR/USD moves of >= 15 / 20 / 30 pips within one hour, merging back-to-back hours
into one sustained move, over a date range of the HistData 1-minute data.

Definitions (all times UTC, measured timestamp rule from engine.py):
  * No clock-hour candles are used anywhere: every check is over ANY rolling 60-minute window.
  * One-hour move at minute t: the largest swing from the LOW of minute t to the highest high
    of any LATER minute less than 60 minutes after t (up), or from the HIGH of minute t to the
    lowest later low (down). This is the true extreme-to-extreme swing, so a move that spikes
    and then reverses inside the hour is counted at its full size.
  * Minutes with a one-hour move >= 15 pips in the same direction, whose 60-minute windows
    touch or overlap, are merged into one EVENT.
  * For each event: the actual swing (lowest low to the later highest high, or the reverse),
    its start/end time, total pips, duration, average pips per hour (pips / max(duration, 1h)),
    and the peak one-hour move. The tier is set by the peak one-hour move: 30+, 20-30 or 15-20.
  * Reversal check, on the hour of the peak one-hour swing: net_1h_pips = how far price still
    was in the move's direction at the end of that hour (close of its last minute) from the
    extreme the swing started at. reversed_in_hour = YES when that is below the tier's threshold
    (15/20/30), i.e. part of the move was given back inside the hour.
  * Window tags: scheduled release/session times that the event start falls near.

Usage: python3 big_moves.py <CSV_DIR> <FROM YYYY-MM-DD> <TO YYYY-MM-DD> <OUT_CSV>
"""
import csv
import datetime as dt
import sys

import numpy as np

import engine as E

WIN = 60          # minutes
MIN_PIPS = 15.0


def forward_extremes(h, l, ts, win):
    """For each bar i: max high and min low over bars whose time is within [ts_i, ts_i + win min)."""
    n = len(ts)
    end = np.searchsorted(ts, ts + win * 60, side="left")
    fmax = np.empty(n); fmin = np.empty(n)
    # sparse table for range max/min queries
    import math
    K = max(1, math.floor(math.log2(win * 2)) + 1)
    mx = [h.copy()]; mn = [l.copy()]
    for k in range(1, K):
        step = 1 << (k - 1)
        a, b = mx[-1], mn[-1]
        mx.append(np.maximum(a, np.concatenate([a[step:], np.full(step, -np.inf)])))
        mn.append(np.minimum(b, np.concatenate([b[step:], np.full(step, np.inf)])))
    length = end - np.arange(n)
    k = np.floor(np.log2(np.maximum(length, 1))).astype(int)
    idx = np.arange(n)
    for kk in np.unique(k):
        sel = k == kk
        i = idx[sel]; j = end[sel] - (1 << kk)
        fmax[sel] = np.maximum(mx[kk][i], mx[kk][j])
        fmin[sel] = np.minimum(mn[kk][i], mn[kk][j])
    return fmax, fmin


def range_extremes(h, l, start, end):
    """Max of h and min of l over index ranges [start, end) (end > start), via sparse tables."""
    import math
    n = len(h)
    span = int(max(1, (end - start).max()))
    K = max(1, math.floor(math.log2(span)) + 1)
    mx = [h.copy()]; mn = [l.copy()]
    for k in range(1, K):
        step = 1 << (k - 1)
        a, b = mx[-1], mn[-1]
        mx.append(np.maximum(a, np.concatenate([a[step:], np.full(step, -np.inf)])))
        mn.append(np.minimum(b, np.concatenate([b[step:], np.full(step, np.inf)])))
    length = np.maximum(end - start, 1)
    k = np.floor(np.log2(length)).astype(int)
    rmax = np.full(len(start), -np.inf); rmin = np.full(len(start), np.inf)
    ok = end > start
    for kk in np.unique(k[ok]):
        sel = ok & (k == kk)
        i = start[sel]; j = end[sel] - (1 << kk)
        rmax[sel] = np.maximum(mx[kk][i], mx[kk][j])
        rmin[sel] = np.minimum(mn[kk][i], mn[kk][j])
    return rmax, rmin


def window_tags(t):
    """Scheduled-release windows (UTC) that a move starting at t falls into (+/- 20 min).
    US releases at 08:30/10:00/14:00 New York; euro-area/German releases in CET/CEST."""
    us_dst = E.us_summer(t.date()); eu_dst = E.eu_summer(t.date())
    ny = 4 if us_dst else 5      # UTC = NY + ny
    cet = 2 if eu_dst else 1     # UTC = CET - cet
    slots = {
        "US 08:30 NY data slot": (8 + ny, 30),
        "US 10:00 NY data slot": (10 + ny, 0),
        "FOMC time slot 14:00 NY": (14 + ny, 0),
        "Fed-press time slot 14:30 NY": (14 + ny, 30),
        "ECB-decision time slot 14:15 CET": (14 - cet, 15),
        "ECB-press time slot 14:45 CET": (14 - cet, 45),
        "Eurozone 10:00-11:00 CET data slot": (10 - cet, 0),
        "German/EZ 08:00-09:50 CET data slot": (8 - cet, 0),
        "London open": (8 - (1 if eu_dst else 0), 0),
        "London 4pm fix": (16 - (1 if eu_dst else 0), 0),
    }
    out = []
    for name, (hh, mm) in slots.items():
        slot = dt.datetime(t.year, t.month, t.day, hh, mm)
        lo, hi = -20, 20
        if name.startswith("German"):
            hi = 110
        if name.startswith("Eurozone"):
            hi = 80
        if lo <= (t - slot).total_seconds() / 60 <= hi:
            out.append(name)
    return "; ".join(out)


def find_events(d, t0, t1):
    m = (d["ts"] >= t0) & (d["ts"] < t1)
    ts, o, h, l, c = d["ts"][m], d["o"][m], d["h"][m], d["l"][m], d["c"][m]
    n = len(ts)
    idx = np.arange(n)
    # later minutes strictly within 60 minutes of minute i (exclude minute i itself: the order of
    # its own high and low is unknown)
    end = np.searchsorted(ts, ts + WIN * 60, side="left")
    rmax, rmin = range_extremes(h, l, np.minimum(idx + 1, n), end)
    up = np.where(np.isfinite(rmax), (rmax - l) / E.PIP, 0.0)
    dn = np.where(np.isfinite(rmin), (h - rmin) / E.PIP, 0.0)
    events = []
    for direction, mv in (("UP", up), ("DOWN", dn)):
        flag = np.where(mv >= MIN_PIPS)[0]
        if not len(flag):
            continue
        groups, cur = [], [flag[0]]
        for i in flag[1:]:
            if ts[i] - ts[cur[-1]] <= WIN * 60:  # windows touch/overlap
                cur.append(i)
            else:
                groups.append(cur); cur = [i]
        groups.append(cur)
        for g in groups:
            a = g[0]
            b = np.searchsorted(ts, ts[g[-1]] + WIN * 60, side="left") - 1
            # largest swing inside the span: max over j of (running max high before j) - low[j]
            # (down) or high[j] - (running min low before j) (up)
            seg_h, seg_l = h[a:b + 1], l[a:b + 1]
            # start and end must be DIFFERENT minutes (inside one minute the order of high and low
            # is unknown), so the running extreme only uses earlier minutes
            if direction == "UP":
                run = np.r_[np.inf, np.minimum.accumulate(seg_l)[:-1]]
                j = int(np.argmax(seg_h - run))
                j_end = a + j
                j_start = a + int(np.argmin(seg_l[:j]))
                pips = (h[j_end] - l[j_start]) / E.PIP
            else:
                run = np.r_[-np.inf, np.maximum.accumulate(seg_h)[:-1]]
                j = int(np.argmax(run - seg_l))
                j_end = a + j
                j_start = a + int(np.argmax(seg_h[:j]))
                pips = (h[j_start] - l[j_end]) / E.PIP
            dur_min = (ts[j_end] - ts[j_start]) / 60 + 1
            peak = float(mv[g].max())
            start_t = E.utc(ts[j_start])
            thr = 30 if peak >= 30 else 20 if peak >= 20 else 15
            sgn = 1 if direction == "UP" else -1
            # reversal is judged on the hour of the PEAK one-hour swing: where did price close at
            # the end of that hour, relative to the extreme it started from?
            tp = g[int(np.argmax(mv[g]))]
            start_px = l[tp] if direction == "UP" else h[tp]
            k1 = np.searchsorted(ts, ts[tp] + WIN * 60, side="left") - 1
            net1h = sgn * (c[k1] - start_px) / E.PIP
            events.append(dict(
                start_utc=start_t, end_utc=E.utc(ts[j_end]), direction=direction,
                tier=("30+" if peak >= 30 else "20-30" if peak >= 20 else "15-20"),
                peak_1h_pips=round(peak, 1), total_pips=round(pips, 1),
                duration_min=int(dur_min), avg_pips_per_hour=round(pips / max(dur_min / 60, 1), 1),
                type=("within 1 hour" if dur_min <= 60 else f"sustained {dur_min/60:.1f} h"),
                start_price=round(float(l[j_start] if direction == 'UP' else h[j_start]), 5),
                end_price=round(float(h[j_end] if direction == 'UP' else l[j_end]), 5),
                net_1h_pips=round(float(net1h), 1),
                reversed_in_hour=("YES" if net1h < thr else "no"),
                time_slot=window_tags(start_t),
            ))
    events.sort(key=lambda e: e["start_utc"])
    return events


if __name__ == "__main__":
    csv_dir, a, b, out = sys.argv[1:5]
    d = E.load(csv_dir, "measured")
    t0 = int((dt.datetime.fromisoformat(a) - dt.datetime(1970, 1, 1)).total_seconds())
    t1 = int((dt.datetime.fromisoformat(b) - dt.datetime(1970, 1, 1)).total_seconds())
    ev = find_events(d, t0, t1)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ev[0].keys()) + ["reason"])
        w.writeheader()
        for e in ev:
            w.writerow({**e, "start_utc": e["start_utc"].strftime("%Y-%m-%d %H:%M"),
                        "end_utc": e["end_utc"].strftime("%Y-%m-%d %H:%M"), "reason": ""})
    import collections
    print(f"events {a} .. {b}: {len(ev)}")
    print("by tier:", dict(collections.Counter(e["tier"] for e in ev)))
    print("by type:", dict(collections.Counter("within 1h" if e["type"] == "within 1 hour" else "sustained" for e in ev)))
    for tier in ("30+", "20-30", "15-20"):
        t_ = [e for e in ev if e["tier"] == tier]
        print(f"  {tier}: {len(t_)} events | reversed within the hour: {sum(e['reversed_in_hour']=='YES' for e in t_)}")
    tagged = collections.Counter(e["tier"] for e in ev if e["time_slot"])
    print("starting in a scheduled-release/session time slot:", dict(tagged))
