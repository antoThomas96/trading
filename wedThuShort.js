// Wednesday-close short with a 1R stop / 2R target, managed on Thursday.
//
// Rules (EUR/USD, trading days roll at 17:00 New York time):
//  1. Filter: Wednesday's open < Monday's open.
//  2. Entry: SELL at Wednesday's close (= Thursday's open).
//  3. Target (2R): Wednesday's low.  R = (entry - Wednesday low) / 2.
//  4. Stop (1R):   entry + R.
//  5. Exit on Thursday at whichever is touched first (checked on 1-minute bars);
//     if both are touched in the same minute the stop is assumed (conservative);
//     if neither is touched, exit at Thursday's close.
//  6. Cost per trade = spread + slippage on entry + slippage on exit.
//
// Usage: node wedThuShort.js <CSV_DIR> [FROM_MONDAY] [CAPITAL_USD] [SPREAD] [SLIP_PER_FILL] [OUT_CSV]

const fs = require('fs');
const path = require('path');
const { loadDailyBars, buildWeeks } = require('./weeklyPattern');

const PIP = 0.0001;

// Thursday 1-minute bars keyed by trading date (NY wall-clock + 7h => trading date).
function loadThursdayMinutes(dir) {
  const out = new Map();
  for (const f of fs.readdirSync(dir).filter((f) => /^DAT_ASCII_.*_M1_\d+\.csv$/.test(f)).sort()) {
    for (const line of fs.readFileSync(path.join(dir, f), 'utf8').split('\n')) {
      const m = line.match(/^(\d{4})(\d{2})(\d{2}) (\d{2})(\d{2})\d{2};([\d.]+);([\d.]+);([\d.]+);([\d.]+)/);
      if (!m) continue;
      const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] + 7, +m[5]));
      if (d.getUTCDay() !== 4) continue;
      const key = d.toISOString().slice(0, 10);
      if (!out.has(key)) out.set(key, []);
      out.get(key).push({ high: +m[7], low: +m[8], close: +m[9], ny: `${m[4]}:${m[5]}` });
    }
  }
  return out;
}

function run(dir, from, capital, spread, slip) {
  const cost = spread + 2 * slip;
  const { complete: weeks } = buildWeeks(loadDailyBars(dir), from);
  const thu = loadThursdayMinutes(dir);
  const trades = [];
  let filtered = 0;
  for (const w of weeks) {
    if (!(w.Wed.open < w.Mon.open)) continue;
    filtered++;
    const entry = w.Wed.close;
    const target = w.Wed.low;
    const R = (entry - target) / 2;
    const base = { week: w.week, monOpen: w.Mon.open, wedOpen: w.Wed.open, entry, target };
    if (R <= 0) { trades.push({ ...base, result: 'NO TRADE (closed at low)' }); continue; }
    const stop = entry + R;
    let exit = null, result = 'Thu close', time = '';
    for (const b of thu.get(w.Thu.date) || []) {
      const hitStop = b.high >= stop, hitTarget = b.low <= target;
      if (hitStop) { exit = stop; result = 'STOP (-1R)'; time = b.ny; break; }
      if (hitTarget) { exit = target; result = 'TARGET (+2R)'; time = b.ny; break; }
    }
    if (exit == null) exit = w.Thu.close;
    const gross = (entry - exit) / PIP; // short
    const net = gross - cost;
    const units = capital / entry; // EUR bought/sold with the capital
    trades.push({ ...base, stop, R_pips: R / PIP, exit, result, nyTime: time, gross, net, usd: units * net * PIP });
  }
  return { weeks: weeks.length, filtered, trades, cost };
}

function report(label, { weeks, filtered, trades, cost }, capital) {
  const t = trades.filter((x) => x.usd != null);
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  const cnt = (r) => t.filter((x) => x.result === r).length;
  const usd = t.map((x) => x.usd).sort((a, b) => b - a);
  console.log(`\n=== ${label}: ${weeks} weeks, ${filtered} passed the Wed-open filter, ${t.length} trades (cost ${cost} pips) ===`);
  console.log(`Target hit: ${cnt('TARGET (+2R)')} | Stop hit: ${cnt('STOP (-1R)')} | Closed at Thu close: ${cnt('Thu close')} | No trade: ${trades.length - t.length}`);
  console.log(`Avg R = ${(sum(t.map((x) => x.R_pips)) / t.length).toFixed(1)} pips | Profitable trades: ${t.filter((x) => x.usd > 0).length}`);
  console.log(`Gross pips ${sum(t.map((x) => x.gross)).toFixed(1)} | Net pips ${sum(t.map((x) => x.net)).toFixed(1)} | ` +
    `Net USD on $${capital.toLocaleString()}: ${Math.round(sum(usd)).toLocaleString()} (${((100 * sum(usd)) / capital).toFixed(2)}%)`);
  console.log(`Best $${Math.round(usd[0])} | Worst $${Math.round(usd.at(-1))} | Net without best 2: $${Math.round(sum(usd) - usd[0] - usd[1])}`);
}

if (require.main === module) {
  const [dir, from = '2025-11-10', cap = '180000', spread = '0.8', slip = '1', outCsv] = process.argv.slice(2);
  const res = run(dir, from, +cap, +spread, +slip);
  report(`From ${from}`, res, +cap);
  if (outCsv) {
    const f5 = (x) => (x == null ? '' : x.toFixed(5));
    const f1 = (x) => (x == null ? '' : (Math.round(x * 10) / 10 + 0).toFixed(1));
    const lines = ['week_monday,mon_open,wed_open,entry_wed_close,target_wed_low,stop,R_pips,exit,result,exit_time_ny,gross_pips,net_pips,net_usd'];
    for (const x of res.trades) {
      lines.push([x.week, f5(x.monOpen), f5(x.wedOpen), f5(x.entry), f5(x.target), f5(x.stop), f1(x.R_pips), f5(x.exit),
        x.result, x.nyTime || '', f1(x.gross), f1(x.net), x.usd == null ? '' : Math.round(x.usd)].join(','));
    }
    fs.writeFileSync(outCsv, lines.join('\n') + '\n');
    console.log(`Trade list written to ${outCsv}`);
  }
}

module.exports = { run };
