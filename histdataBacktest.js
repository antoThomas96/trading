// Run the London-close backtest (see londonCloseBacktest.js) on HistData.com 1-minute data.
// Usage: node histdataBacktest.js <CSV_DIR> [SPREAD_PIPS] [SLIPPAGE_PIPS_PER_FILL] [SIDE] [YEARS]
//   CSV_DIR holds the unzipped DAT_ASCII_<PAIR>_M1_*.csv files from histdataDownload.js.
//
// HistData's docs say timestamps are EST without daylight saving, but cross-checking these
// files against Yahoo Finance shows they follow US Eastern time WITH daylight saving
// (UTC-4 in summer, UTC-5 in winter). Each bar is converted America/New_York -> UTC ->
// Europe/London (which handles GMT/BST).

const fs = require('fs');
const path = require('path');
const { backtest, summarize } = require('./londonCloseBacktest');

const WANTED = new Set(['15:30', '15:55', '16:00']);
const nyFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' });
const nyOffsetHours = (ms) => -Number(nyFmt.formatToParts(new Date(ms)).find((x) => x.type === 'timeZoneName').value.replace('GMT', '') || 0);
// Wall-clock New York time -> UTC milliseconds
function nyToUtc(y, mo, d, h, mi) {
  const guess = Date.UTC(y, mo - 1, d, h + 5, mi);
  return Date.UTC(y, mo - 1, d, h + nyOffsetHours(guess), mi);
}

const fmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short',
});

function loadCandles(dir) {
  const out = [];
  for (const f of fs.readdirSync(dir).filter((f) => /^DAT_ASCII_.*_M1_\d+\.csv$/.test(f)).sort()) {
    for (const line of fs.readFileSync(path.join(dir, f), 'utf8').split('\n')) {
      // 20261101 170400;open;high;low;close;vol
      const m = line.match(/^(\d{4})(\d{2})(\d{2}) (\d{2})(\d{2})\d{2};([\d.]+);([\d.]+);([\d.]+);([\d.]+)/);
      if (!m) continue;
      // Cheap pre-filter: London 15:30-16:00 is 10:30-11:00 New York time, or 11:30-12:00
      // in the weeks when US and UK daylight-saving dates differ.
      if (m[4] < '10' || m[4] > '12') continue;
      const utcMs = nyToUtc(+m[1], +m[2], +m[3], +m[4], +m[5]);
      const p = Object.fromEntries(fmt.formatToParts(new Date(utcMs)).map((x) => [x.type, x.value]));
      const time = `${p.hour}:${p.minute}`;
      if (!WANTED.has(time)) continue;
      out.push({ date: `${p.year}-${p.month}-${p.day}`, weekday: p.weekday, time, open: +m[6], close: +m[9] });
    }
  }
  return out;
}

if (require.main === module) {
  const [dir, spread = '0.8', slippage = '1', side = 'long', years = '3'] = process.argv.slice(2);
  const opts = { spread: +spread, slippage: +slippage, side };
  const all = loadCandles(dir);
  const lastDate = all.at(-1).date;
  const cutoff = (monthsBack) => {
    const d = new Date(`${lastDate}T00:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() - monthsBack);
    return d.toISOString().slice(0, 10);
  };
  const window = (fromDate) => all.filter((c) => c.date > fromDate);

  const runs = [
    [`Last ${years} years`, window(cutoff(12 * +years))],
    ['Last 3 months', window(cutoff(3))],
  ];
  console.log(`EUR/USD ${side.toUpperCase()} 15:30 London entry | cost ${+spread + 2 * +slippage} pips/trade | data ends ${lastDate}\n`);
  const rows = [];
  for (const [label, candles] of runs) {
    for (const exit of ['15:55', '16:00']) {
      const r = backtest(candles, { ...opts, exit });
      rows.push({ Period: `${label} (${r.trades[0].date} → ${r.trades.at(-1).date})`, ...summarize(`Exit ${exit}`, r) });
    }
  }
  console.table(rows);

  // Per-year breakdown for the 3-year window
  const three = window(cutoff(12 * +years));
  const byYear = {};
  for (const exit of ['15:55', '16:00']) {
    for (const t of backtest(three, { ...opts, exit }).trades) {
      const y = t.date.slice(0, 4);
      byYear[y] ??= { Year: y };
      const k = `@${exit}`;
      byYear[y][`Days`] = (byYear[y][`Days ${k}`] = (byYear[y][`Days ${k}`] || 0) + 1);
      byYear[y][`Wins ${k}`] = (byYear[y][`Wins ${k}`] || 0) + (t.netPips > 0);
      byYear[y][`Net pips ${k}`] = +((byYear[y][`Net pips ${k}`] || 0) + t.netPips).toFixed(1);
    }
  }
  console.log('\nBy calendar year:');
  console.table(Object.values(byYear).map(({ Year, Days, ...r }) => ({
    Year, Days,
    'Wins @15:55': `${r['Wins @15:55']} (${((100 * r['Wins @15:55']) / Days).toFixed(0)}%)`, 'Net @15:55': r['Net pips @15:55'],
    'Wins @16:00': `${r['Wins @16:00']} (${((100 * r['Wins @16:00']) / Days).toFixed(0)}%)`, 'Net @16:00': r['Net pips @16:00'],
  })));
}

module.exports = { loadCandles };
