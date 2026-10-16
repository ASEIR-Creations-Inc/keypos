/* UI checks for the post-Phase-4 fixes:
 *  - a sale whose reply is lost is queued under the same checkout ref and the
 *    server does not record it twice when the queue syncs;
 *  - a freshly installed app has its scripts in the offline cache, so it starts
 *    with no network.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-fixes.js
 */
const fs = require('fs');
const http = require('http');
const path = require('path');
const { execSync } = require('child_process');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const sql = (q) => execSync(`sudo -u postgres psql -d pos_test -tAc "${q}"`).toString().trim();
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + detail : ''));
};

async function api(path, options) {
  const r = await authFetch(BASE + '/api' + path, options);
  return r.status === 204 ? null : r.json();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function serveFrontend(port) {
  const root = path.join(__dirname, '..', 'frontend');
  const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png' };
  const server = http.createServer((req, res) => {
    const file = path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end(); return;
    }
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

async function run() {
  const A = Number(sql('select id from products where is_active order by id limit 1'));
  sql(`update products set stock_qty=10, sell_price=10 where id=${A}`);
  await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 0, low_stock_threshold: 5 }) });
  const openShifts = await api('/shifts?status=open&limit=1');
  if (openShifts.length) await post('/shifts/close', { closing_cash: 0 });
  const shift = await post('/shifts/open', { opening_float: 20 });

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  const errors = [];
  const alerts = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => {
    if (d.type() === 'prompt') return d.accept('');
    if (d.type() === 'alert') alerts.push(d.message());
    return d.accept();
  });
  const click = (sel) => page.$eval(sel, (el) => el.click());
  const text = (sel) => page.$eval(sel, (el) => el.textContent);
  const lastAlert = () => alerts[alerts.length - 1] || '';
  const serverStock = () => parseFloat(sql(`select stock_qty from products where id=${A}`));

  /* 1. Fresh install: the offline cache already holds every script the page loads,
     so the app starts when the server cannot be reached at all. Served from a
     throwaway static server the test can switch off (Chrome's offline emulation
     does not survive a reload). */
  const shellServer = await serveFrontend(8096);
  const shellPage = await context.newPage();
  const shellErrors = [];
  shellPage.on('pageerror', (e) => shellErrors.push(e.message));
  shellPage.on('dialog', (d) => d.accept());
  await signIn(shellPage, 'http://127.0.0.1:8096');
  await shellPage.goto('http://127.0.0.1:8096/pos.html');
  await shellPage.evaluate(() => navigator.serviceWorker.ready);
  await wait(1500);
  const scripts = await shellPage.evaluate(() => Array.prototype.map.call(
    document.querySelectorAll('script[src]'), (s) => new URL(s.src).pathname + new URL(s.src).search));
  const cached = await shellPage.evaluate(async () => {
    const names = await caches.keys();
    const cache = await caches.open(names[names.length - 1]);
    return (await cache.keys()).map((r) => new URL(r.url).pathname + new URL(r.url).search);
  });
  const missing = scripts.filter((s) => cached.indexOf(s) === -1);
  check('page loads its scripts', scripts.length > 4, scripts.join(', '));
  check('fresh install has every script in the offline cache', missing.length === 0, 'missing: ' + missing.join(', '));

  await new Promise((resolve) => shellServer.close(resolve));
  shellServer.closeAllConnections();
  await shellPage.reload();
  await wait(2500);
  const unreachable = await shellPage.evaluate(() => fetch('/api/settings')
    .then(() => false, () => true));
  check('server really is unreachable', unreachable);
  const started = await shellPage.evaluate(() => typeof posAddToCart === 'function' && typeof SYNC === 'object'
    && !!document.getElementById('productGrid'));
  check('app starts from the offline cache', started && shellErrors.length === 0, shellErrors.join(' | '));
  await shellPage.close();

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);

  /* 2. Lost reply: the server records the sale, the till never hears back */
  const before = serverStock();
  await page.evaluate(() => {
    const realFetch = window.fetch;
    window.fetch = function (url, options) {
      const lose = options && options.method === 'POST' && String(url).indexOf('/api/transactions') > -1;
      return realFetch.apply(this, arguments).then((response) => {
        if (lose) { window.fetch = realFetch; throw new TypeError('Failed to fetch'); }
        return response;
      });
    };
  });
  alerts.length = 0;
  await page.evaluate(() => posResetCart());
  await page.evaluate((id) => { posAddToCart(id); posAddToCart(id); }, A);
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '20'; });
  await click('#confirmCashBtn');
  await wait(1500);
  check('till treats the lost reply as offline', lastAlert().indexOf('OFFLINE SALE') === 0, lastAlert().split('\n')[0]);
  check('server recorded the sale once already', serverStock() === before - 2, String(serverStock()));

  const dev = await page.evaluate(() => DB.getDeviceId());
  const recordedRef = sql(`select client_ref from transactions where shift_id=${shift.id} order by id desc limit 1`);
  const queuedRef = await page.evaluate(() => new Promise((resolve) => DB.getPendingSync((e, items) => resolve(items.length ? items[0].client_ref : null))));
  check('queued copy carries the same checkout ref', recordedRef && recordedRef === queuedRef, recordedRef + ' vs ' + queuedRef);

  await page.evaluate(() => new Promise((resolve) => SYNC.syncNow(resolve)));
  await wait(1500);
  check('badge back to ONLINE after sync', (await text('#syncStatus')) === 'ONLINE', await text('#syncStatus'));
  const txns = Number(sql(`select count(*) from transactions where shift_id=${shift.id}`));
  check('still one receipt after the queue synced', txns === 1, String(txns));
  check('stock deducted once', serverStock() === before - 2, String(serverStock()));
  const pending = Number(sql(`select count(*) from sync_queue where device_id='${dev}' and not synced`));
  check('queue item marked synced on the server', pending === 0, String(pending));

  check('no script errors', errors.length === 0, errors.join(' | '));
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
