// Weekly EUR/USD pattern study on HistData.com 1-minute data.
//  Q1: in how many weeks was Wednesday's high below Monday's high?
//  Q2: in how many weeks did Thursday trade down to (or below) Wednesday's low?
//  Q3: buy at Monday's open (spread + slippage) — net result for several exits.
//
// Trading days use the standard FX rollover at 17:00 New York time: "Monday" runs
// Sunday 17:00 NY -> Monday 17:00 NY. HistData timestamps are New York wall-clock time
// (see histdataBacktest.js), so adding 7 hours to the timestamp gives the trading date.
//
// Usage: node weeklyPattern.js <CSV_DIR> [FROM_MONDAY YYYY-MM-DD] [SPREAD] [SLIPPAGE_PER_FILL] [OUT_CSV]

const fs = require('fs');
const path = require('path');

const PIP = 0.0001;
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];

function loadDailyBars(dir) {
  const days = new Map(); // tradingDate -> {date, dow, open, high, low, close}
  const files = fs.readdirSync(dir).filter((f) => /^DAT_ASCII_.*_M1_\d+\.csv$/.test(f)).sort();
  for (const f of files) {
    for (const line of fs.readFileSync(path.join(dir, f), 'utf8').split('\n')) {
      const m = line.match(/^(\d{4})(\d{2})(\d{2}) (\d{2})(\d{2})\d{2};([\d.]+);([\d.]+);([\d.]+);([\d.]+)/);
      if (!m) continue;
      // NY wall-clock + 7h => trading date (17:00 NY rollover). Done in UTC arithmetic on the
      // wall-clock fields, so DST does not matter here.
      const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] + 7, +m[5]));
      const dow = d.getUTCDay(); // 1 = Mon ... 5 = Fri
      if (dow < 1 || dow > 5) continue;
      const key = d.toISOString().slice(0, 10);
      const [o, h, l, c] = [+m[6], +m[7], +m[8], +m[9]];
      const bar = days.get(key);
      if (!bar) days.set(key, { date: key, dow: DAYS[dow - 1], open: o, high: h, low: l, close: c });
      else { bar.high = Math.max(bar.high, h); bar.low = Math.min(bar.low, l); bar.close = c; }
    }
  }
  return days;
}

function mondayOf(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

function buildWeeks(days, fromMonday) {
  const weeks = new Map();
  for (const bar of days.values()) {
    const wk = mondayOf(bar.date);
    if (wk < fromMonday) continue;
    if (!weeks.has(wk)) weeks.set(wk, { week: wk });
    weeks.get(wk)[bar.dow] = bar;
  }
  const complete = [], skipped = [];
  for (const w of [...weeks.values()].sort((a, b) => a.week.localeCompare(b.week))) {
    (DAYS.every((d) => w[d]) ? complete : skipped).push(w);
  }
  return { complete, skipped };
}

if (require.main === module) {
  const [dir, from = '2025-11-10', spread = '0.8', slip = '1', outCsv] = process.argv.slice(2);
  const cost = +spread + 2 * +slip;
  const { complete: weeks, skipped } = buildWeeks(loadDailyBars(dir), from);
  const n = weeks.length;
  const pct = (k) => `${k} of ${n} (${((100 * k) / n).toFixed(1)}%)`;

  const rows = weeks.map((w) => {
    const wedBelowMon = w.Wed.high < w.Mon.high;
    const thuHitWedLow = w.Thu.low <= w.Wed.low;
    const entry = w.Mon.open;
    const g = (px) => (px - entry) / PIP;
    return {
      week: w.week, monOpen: entry, monHigh: w.Mon.high, wedHigh: w.Wed.high, wedLow: w.Wed.low, thuLow: w.Thu.low,
      wedBelowMon, thuHitWedLow,
      grossMonClose: g(w.Mon.close), grossWedClose: g(w.Wed.close), grossFriClose: g(w.Fri.close),
    };
  });

  const q1 = rows.filter((r) => r.wedBelowMon).length;
  const q2 = rows.filter((r) => r.thuHitWedLow).length;
  const both = rows.filter((r) => r.wedBelowMon && r.thuHitWedLow).length;
  const q2NotQ1 = rows.filter((r) => !r.wedBelowMon && r.thuHitWedLow).length;

  console.log(`EUR/USD weekly pattern | weeks ${weeks[0].week} to ${weeks.at(-1).week} | ${n} complete weeks`);
  if (skipped.length) console.log(`Skipped (missing a weekday): ${skipped.map((w) => w.week).join(', ')}`);
  console.log(`\nQ1 Wednesday high < Monday high:            ${pct(q1)}`);
  console.log(`Q2 Thursday reached Wednesday low:           ${pct(q2)}`);
  console.log(`   ...in weeks where Q1 was true:            ${both} of ${q1} (${((100 * both) / q1).toFixed(1)}%)`);
  console.log(`   ...in weeks where Q1 was false:           ${q2NotQ1} of ${n - q1} (${((100 * q2NotQ1) / (n - q1)).toFixed(1)}%)`);

  console.log(`\nQ3 Buy at Monday open | cost ${cost} pips/trade (spread ${spread} + slippage ${slip} x 2)`);
  const table = [];
  for (const [label, key] of [['Sell Monday close', 'grossMonClose'], ['Sell Wednesday close', 'grossWedClose'], ['Sell Friday close', 'grossFriClose']]) {
    const g = rows.map((r) => r[key]);
    const net = g.map((x) => x - cost);
    table.push({
      Exit: label, Trades: n,
      'Profitable (net)': pct(net.filter((x) => x > 0).length),
      'Gross pips': +g.reduce((a, b) => a + b, 0).toFixed(1),
      'Cost pips': +(-cost * n).toFixed(1),
      'Net pips': +net.reduce((a, b) => a + b, 0).toFixed(1),
      'Avg net/trade': +(net.reduce((a, b) => a + b, 0) / n).toFixed(2),
      Best: +Math.max(...net).toFixed(1), Worst: +Math.min(...net).toFixed(1),
    });
  }
  console.table(table);

  if (outCsv) {
    const f5 = (x) => x.toFixed(5), f1 = (x) => (Math.round(x * 10) / 10 + 0).toFixed(1);
    const lines = ['week_monday,mon_open,mon_high,wed_high,wed_low,thu_low,wed_high_below_mon_high,thu_reached_wed_low,' +
      'gross_pips_mon_close,net_pips_mon_close,gross_pips_wed_close,net_pips_wed_close,gross_pips_fri_close,net_pips_fri_close'];
    for (const r of rows) {
      lines.push([r.week, f5(r.monOpen), f5(r.monHigh), f5(r.wedHigh), f5(r.wedLow), f5(r.thuLow),
        r.wedBelowMon ? 'YES' : 'NO', r.thuHitWedLow ? 'YES' : 'NO',
        f1(r.grossMonClose), f1(r.grossMonClose - cost), f1(r.grossWedClose), f1(r.grossWedClose - cost),
        f1(r.grossFriClose), f1(r.grossFriClose - cost)].join(','));
    }
    fs.writeFileSync(outCsv, lines.join('\n') + '\n');
    console.log(`\nWeekly detail written to ${outCsv}`);
  }
}

module.exports = { loadDailyBars, buildWeeks };
