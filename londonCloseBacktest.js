// Backtest: buy EUR/USD 30 minutes before the London close (15:30 London time)
// and sell either 5 minutes before the close (15:55) or at the close (16:00).
// Uses Yahoo Finance 5-minute candles (max ~60 days of history).
//
// Usage: node londonCloseBacktest.js [SYMBOL] [SPREAD_PIPS] [SLIPPAGE_PIPS_PER_FILL] [SIDE]
//   defaults: EURUSD=X 0.8 1 long      (SIDE = long | short)
//
// Prices: the open of the 5-minute bar starting at a given minute is used as the
// price at that minute (e.g. entry = open of the 15:30 bar, exit = open of the 16:00 bar).
// Cost per trade = spread (paid once per round trip) + slippage on entry + slippage on exit.

const PIP = 0.0001;

async function get5mCandles(symbol) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=5m&range=60d`;
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!res.ok) throw new Error(`Yahoo Finance HTTP ${res.status}`);
  const json = await res.json();
  const r = json.chart.result?.[0];
  if (!r?.timestamp) throw new Error(JSON.stringify(json.chart.error));
  const tz = r.meta.exchangeTimezoneName; // Europe/London for FX — handles BST/GMT switch
  const q = r.indicators.quote[0];
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short',
  });
  return r.timestamp
    .map((t, i) => {
      const p = Object.fromEntries(fmt.formatToParts(new Date(t * 1000)).map((x) => [x.type, x.value]));
      return { date: `${p.year}-${p.month}-${p.day}`, weekday: p.weekday, time: `${p.hour}:${p.minute}`, open: q.open[i], close: q.close[i] };
    })
    .filter((c) => c.open != null);
}

function backtest(candles, { entry = '15:30', exit, spread, slippage, side = 'long' }) {
  const byDay = new Map();
  for (const c of candles) {
    if (!byDay.has(c.date)) byDay.set(c.date, {});
    byDay.get(c.date)[c.time] = c;
  }
  const costPips = spread + 2 * slippage;
  const dir = side === 'short' ? -1 : 1;
  const trades = [];
  for (const [date, bars] of byDay) {
    const e = bars[entry], x = bars[exit];
    if (!e || !x) continue; // weekend / missing data
    const grossPips = (dir * (x.open - e.open)) / PIP;
    trades.push({ date, weekday: e.weekday, entry: e.open, exit: x.open, grossPips, netPips: grossPips - costPips });
  }
  return { trades, costPips };
}

function summarize(label, { trades, costPips }) {
  const wins = trades.filter((t) => t.netPips > 0).length;
  const grossWins = trades.filter((t) => t.grossPips > 0).length;
  const net = trades.reduce((s, t) => s + t.netPips, 0);
  const gross = trades.reduce((s, t) => s + t.grossPips, 0);
  return {
    Strategy: label,
    Days: trades.length,
    'Profitable days (net)': `${wins} (${((100 * wins) / trades.length).toFixed(1)}%)`,
    'Losing days (net)': trades.length - wins,
    'Up days before costs': grossWins,
    'Total gross pips': gross.toFixed(1),
    'Total cost pips': (costPips * trades.length).toFixed(1),
    'Total net pips': net.toFixed(1),
    'Avg net pips/day': (net / trades.length).toFixed(2),
    'Best day': Math.max(...trades.map((t) => t.netPips)).toFixed(1),
    'Worst day': Math.min(...trades.map((t) => t.netPips)).toFixed(1),
  };
}

module.exports = { get5mCandles, backtest, summarize };

if (require.main === module) {
  const [symbol = 'EURUSD=X', spread = '0.8', slippage = '1', side = 'long'] = process.argv.slice(2);
  const opts = { spread: +spread, slippage: +slippage, side };
  get5mCandles(symbol).then((candles) => {
    const a = backtest(candles, { ...opts, exit: '15:55' });
    const b = backtest(candles, { ...opts, exit: '16:00' });
    console.log(`${symbol} ${side.toUpperCase()} 15:30 London entry | spread ${spread} pip + slippage ${slippage} pip/fill = ${a.costPips} pips/trade`);
    console.log(`Data: ${a.trades[0].date} to ${a.trades.at(-1).date}\n`);
    console.table([summarize('Exit 15:55', a), summarize('Exit 16:00', b)]);
    console.log('\nPer day (net pips after costs):');
    console.table(a.trades.map((t, i) => ({
      Date: `${t.date} ${t.weekday}`, 'Entry 15:30': t.entry.toFixed(5),
      'Exit 15:55': t.exit.toFixed(5), 'Net@15:55': t.netPips.toFixed(1),
      'Exit 16:00': b.trades[i].exit.toFixed(5), 'Net@16:00': b.trades[i].netPips.toFixed(1),
    })));
  }).catch((e) => { console.error('Error:', e.message); process.exit(1); });
}
