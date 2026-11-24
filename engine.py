"""Honest EUR/USD backtest engine for HistData.com 1-minute BID data.

Rules implemented (from the analysis brief):
  * Timestamps -> UTC WITHOUT a timezone library. Two modes:
      spec     : UTC = file time + 5h, always (as the brief says).
      measured : UTC = file time + 4h between the last Sunday of March and the
                 last Sunday of October (European summer time), else + 5h.
                 This is what the data itself shows (weekly open/close times and
                 a week-by-week price match against Yahoo Finance).
  * FX week filter in UTC: Sunday 21:00 -> Friday 21:00 (22:00 in US winter).
    Bars outside the window (incl. Saturday) are dropped.
  * Trading day rolls at the same boundary (17:00 New York).
  * No look-ahead: signal on bar i, fill at the OPEN of bar i+1.
  * A bar containing both stop and target is ambiguous: counted, and every test
    runs twice (stop-first = pessimistic, target-first = optimistic).
  * Cost in pips charged on every trade (default 0.8 round trip). Prices are
    BID only; the cost covers the spread. Volume is ignored.
"""
import datetime as dt
import glob
import math
import os
import sys

import numpy as np

PIP = 1e-4


# ---------- calendar helpers (no tz library) ----------
def _nth_sunday(y, m, n):
    d = dt.date(y, m, 1)
    d += dt.timedelta((6 - d.weekday()) % 7)
    return d + dt.timedelta(7 * (n - 1))


def _last_sunday(y, m):
    d = dt.date(y, m + 1, 1) - dt.timedelta(1) if m < 12 else dt.date(y, 12, 31)
    return d - dt.timedelta((d.weekday() + 1) % 7)


def eu_summer(day):
    return _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10)


def us_summer(day):
    return _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)


# ---------- loading ----------
# Data-quality exclusions found by the audit (file-clock dates, inclusive start, exclusive end).
# Feb-Jul 2023: 27-29% of minutes missing in repeating one-hour holes.
EXCLUDE = [("20230201", "20230801")]


def load(csv_dir, tz_mode="measured", exclude=EXCLUDE):
    """Return dict of numpy arrays: ts (UTC epoch s), o, h, l, c, tday (trading-day ordinal), wd (0=Mon).
    Duplicate timestamps are removed (first occurrence kept) and EXCLUDE ranges are dropped."""
    rows = []
    for f in sorted(glob.glob(os.path.join(csv_dir, "DAT_ASCII_EURUSD_M1_*.csv"))):
        with open(f) as fh:
            for line in fh:
                p = line.rstrip().split(";")
                if len(p) < 5 or len(p[0]) != 15:
                    continue
                if any(a <= p[0][:8] < b for a, b in exclude):
                    continue
                rows.append((p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    rows.sort(key=lambda r: r[0])  # stable: first occurrence of a duplicate stays first
    deduped, seen = [], set()
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0]); deduped.append(r)
    n_dupes = len(rows) - len(deduped)
    rows = deduped
    n = len(rows)
    ts = np.empty(n, dtype=np.int64)
    offset_cache = {}
    for i, (stamp, *_rest) in enumerate(rows):
        day = stamp[:8]
        off = offset_cache.get(day)
        if off is None:
            d = dt.date(int(day[:4]), int(day[4:6]), int(day[6:8]))
            off = 5 if tz_mode == "spec" else (4 if eu_summer(d) else 5)
            offset_cache[day] = off
        local = dt.datetime(int(day[:4]), int(day[4:6]), int(day[6:8]), int(stamp[9:11]), int(stamp[11:13]))
        ts[i] = int((local - dt.datetime(1970, 1, 1)).total_seconds()) + off * 3600
    o = np.array([r[1] for r in rows]); h = np.array([r[2] for r in rows])
    l = np.array([r[3] for r in rows]); c = np.array([r[4] for r in rows])

    # FX week window + trading day, in UTC
    keep = np.zeros(n, dtype=bool)
    tday = np.empty(n, dtype=np.int64)
    roll_cache = {}
    for i in range(n):
        t = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(ts[i]))
        d = t.date()
        roll = roll_cache.get(d)
        if roll is None:
            roll = 21 if us_summer(d) else 22
            roll_cache[d] = roll
        wd = d.weekday()  # 0 Mon .. 6 Sun
        hr = t.hour + t.minute / 60
        if wd == 5:
            ok = False
        elif wd == 6:
            ok = hr >= roll
        elif wd == 4:
            ok = hr < roll
        else:
            ok = True
        keep[i] = ok
        # trading day: bars at/after the roll hour belong to the next calendar day
        tday[i] = d.toordinal() + (1 if hr >= roll else 0)
    m = keep
    out = dict(ts=ts[m], o=o[m], h=h[m], l=l[m], c=c[m], tday=tday[m])
    out["wd"] = np.array([dt.date.fromordinal(int(x)).weekday() for x in out["tday"]])
    out["dropped"] = int((~keep).sum())
    out["duplicates_removed"] = n_dupes
    return out


def utc(ts):
    return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(ts))


# ---------- trade simulation ----------
def simulate(d, entry_idx, direction, stop_px, target_px, last_idx, cost, optimistic):
    """Fill at open[entry_idx]. direction +1 long / -1 short. stop_px/target_px may be None.
    Exit at stop/target touch, else at close[last_idx]. Returns dict."""
    entry = d["o"][entry_idx]
    ambiguous = False
    exit_px, reason, exit_i = None, "time", last_idx
    for i in range(entry_idx, last_idx + 1):
        hi, lo = d["h"][i], d["l"][i]
        if direction > 0:
            hit_s = stop_px is not None and lo <= stop_px
            hit_t = target_px is not None and hi >= target_px
        else:
            hit_s = stop_px is not None and hi >= stop_px
            hit_t = target_px is not None and lo <= target_px
        if hit_s and hit_t:
            ambiguous = True
            exit_px, reason = (target_px, "target") if optimistic else (stop_px, "stop")
        elif hit_s:
            exit_px, reason = stop_px, "stop"
        elif hit_t:
            exit_px, reason = target_px, "target"
        if exit_px is not None:
            exit_i = i
            break
    if exit_px is None:
        exit_px = d["c"][last_idx]
    gross = direction * (exit_px - entry) / PIP
    stop_pips = abs(entry - stop_px) / PIP if stop_px is not None else None
    tgt_pips = abs(target_px - entry) / PIP if target_px is not None else None
    return dict(entry_i=entry_idx, exit_i=exit_i, entry=entry, exit=exit_px, reason=reason,
                ambiguous=ambiguous, gross=gross, net=gross - cost, stop_pips=stop_pips, tgt_pips=tgt_pips)


# ---------- statistics ----------
def stats(trades, cost, use_r=True):
    n = len(trades)
    if n == 0:
        return dict(n=0)
    net = np.array([t["net"] for t in trades])
    if use_r:
        unit = np.array([t["net"] / t["stop_pips"] for t in trades])
    else:
        unit = net
    sd = unit.std(ddof=1) if n > 1 else float("nan")
    tstat = unit.mean() / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    half = n // 2
    h1, h2 = unit[:half].sum(), unit[half:].sum()
    be = None
    if use_r and all(t["tgt_pips"] for t in trades):
        be = float(np.mean([(t["stop_pips"] + cost) / (t["stop_pips"] + t["tgt_pips"]) for t in trades]))
    return dict(
        n=n, ambiguous=sum(t["ambiguous"] for t in trades),
        wins=int((net > 0).sum()), win_rate=float((net > 0).mean()), breakeven_wr=be,
        targets=sum(t["reason"] == "target" for t in trades), stops=sum(t["reason"] == "stop" for t in trades),
        time_exits=sum(t["reason"] == "time" for t in trades),
        avg_unit=float(unit.mean()), t=float(tstat), first_half=float(h1), second_half=float(h2),
        net_pips=float(net.sum()), avg_net_pips=float(net.mean()),
    )


def verdict(s_pess, plateau_ok):
    """Positivity and halves are judged in R (the same unit as the t-statistic).
    Halves must agree in sign AND be positive: two losing halves 'agree' but do not pass."""
    checks = {
        "n >= 30": s_pess["n"] >= 30,
        "positive on pessimistic (avg R > 0)": s_pess["avg_unit"] > 0,
        "|t| >= 2": abs(s_pess["t"]) >= 2,
        "both halves positive": s_pess["first_half"] > 0 and s_pess["second_half"] > 0,
        "plateau in grid": plateau_ok,
    }
    return checks, ("PASS" if all(checks.values()) else "INCONCLUSIVE")


if __name__ == "__main__":
    d = load(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "measured")
    print(len(d["ts"]), "bars kept;", d["dropped"], "dropped;", utc(d["ts"][0]), "->", utc(d["ts"][-1]))
