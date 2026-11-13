// Fetch 15-minute candles for a single trading day from Yahoo Finance.
// Usage: node yahoo15m.js [SYMBOL] [YYYY-MM-DD]
//   SYMBOL defaults to AAPL; date defaults to the most recent trading day.
// Note: Yahoo only serves 15m data for roughly the last 60 days.

async function get15mCandles(symbol = 'AAPL', date) {
  const params = new URLSearchParams({ interval: '15m', includePrePost: 'false' });
  if (date) {
    // Window covering the whole calendar day (UTC +/- slack); filtered below by exchange-local date.
    const start = Math.floor(new Date(`${date}T00:00:00Z`).getTime() / 1000) - 12 * 3600;
    params.set('period1', start);
    params.set('period2', start + 48 * 3600);
  } else {
    params.set('range', '5d');
  }

  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?${params}`;
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!res.ok) throw new Error(`Yahoo Finance HTTP ${res.status}: ${await res.text()}`);

  const json = await res.json();
  if (json.chart.error) throw new Error(JSON.stringify(json.chart.error));
  const result = json.chart.result?.[0];
  if (!result?.timestamp) throw new Error(`No 15m data for ${symbol}${date ? ' on ' + date : ''}`);

  const tz = result.meta.exchangeTimezoneName;
  const q = result.indicators.quote[0];
  const localDate = (t) => new Date(t * 1000).toLocaleDateString('en-CA', { timeZone: tz });
  const localTime = (t) =>
    new Date(t * 1000).toLocaleTimeString('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit' });

  const candles = result.timestamp
    .map((t, i) => ({
      date: localDate(t),
      time: localTime(t),
      open: q.open[i],
      high: q.high[i],
      low: q.low[i],
      close: q.close[i],
      volume: q.volume[i],
    }))
    .filter((c) => c.open != null && c.close != null)
    // Drop Yahoo's zero-volume closing-price placeholder bar (e.g. 16:00).
    .filter((c) => !(c.volume === 0 && c.open === c.high && c.high === c.low && c.low === c.close));

  const day = date ?? candles.at(-1)?.date;
  return { symbol: result.meta.symbol, timezone: tz, day, candles: candles.filter((c) => c.date === day) };
}

module.exports = { get15mCandles };

if (require.main === module) {
  const [symbol, date] = process.argv.slice(2);
  get15mCandles(symbol, date)
    .then(({ symbol, timezone, day, candles }) => {
      const f = (n) => n.toFixed(2);
      console.log(`${symbol} — 15-minute candles for ${day} (${timezone}), ${candles.length} bars\n`);
      console.table(
        candles.map((c) => ({ Time: c.time, Open: f(c.open), High: f(c.high), Low: f(c.low), Close: f(c.close), Volume: c.volume }))
      );
    })
    .catch((e) => {
      console.error('Error:', e.message);
      process.exit(1);
    });
}
