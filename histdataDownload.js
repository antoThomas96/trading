// Download free 1-minute ASCII FX data from HistData.com.
// Past years come as one zip per year; the current year comes as one zip per month.
// Usage: node histdataDownload.js <OUT_DIR> [PAIR] [FROM_YEAR]
//   e.g. node histdataDownload.js ./data EURUSD 2023

const fs = require('fs');
const path = require('path');

const BASE = 'https://www.histdata.com';
const UA = { 'User-Agent': 'Mozilla/5.0' };

async function downloadOne(pair, year, month, outDir) {
  const suffix = month ? `${year}/${month}` : `${year}`;
  const pageUrl = `${BASE}/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/${pair.toLowerCase()}/${suffix}`;
  const page = await (await fetch(pageUrl, { headers: UA })).text();
  const field = (id) => page.match(new RegExp(`id="${id}" value="([^"]*)"`))?.[1];
  const tk = field('tk');
  if (!tk) return null; // no file published for this period
  const body = new URLSearchParams({
    tk, date: field('date'), datemonth: field('datemonth'),
    platform: 'ASCII', timeframe: 'M1', fxpair: pair.toUpperCase(),
  });
  const res = await fetch(`${BASE}/get.php`, {
    method: 'POST', body,
    headers: { ...UA, Referer: pageUrl, 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  const buf = Buffer.from(await res.arrayBuffer());
  if (!res.ok || buf.subarray(0, 2).toString() !== 'PK') throw new Error(`Bad download for ${suffix}: HTTP ${res.status}`);
  const file = path.join(outDir, `HISTDATA_COM_ASCII_${pair.toUpperCase()}_M1_${field('datemonth')}.zip`);
  fs.writeFileSync(file, buf);
  return file;
}

async function downloadRange(pair, fromYear, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const thisYear = new Date().getUTCFullYear();
  const files = [];
  for (let y = fromYear; y < thisYear; y++) {
    const f = await downloadOne(pair, y, null, outDir);
    if (f) { files.push(f); console.log('saved', f); }
  }
  for (let m = 1; m <= 12; m++) {
    const f = await downloadOne(pair, thisYear, m, outDir);
    if (f) { files.push(f); console.log('saved', f); }
  }
  return files;
}

module.exports = { downloadRange };

if (require.main === module) {
  const [outDir = './data', pair = 'EURUSD', from = String(new Date().getUTCFullYear() - 3)] = process.argv.slice(2);
  downloadRange(pair, +from, outDir).catch((e) => { console.error('Error:', e.message); process.exit(1); });
}
