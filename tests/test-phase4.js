/* Phase 4 UI test: real offline mode — selling with the network down, the
 * device-side stock guard, the sync badge, and the queue draining on reconnect
 * without duplicates.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-phase4.js
 */
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

async function run() {
  const A = Number(sql('select id from products where is_active order by id limit 1'));
  sql(`update products set stock_qty=10, sell_price=10 where id=${A}`);
  await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 0, low_stock_threshold: 5 }) });
  const openShifts = await api('/shifts?status=open&limit=1');
  if (openShifts.length) await post('/shifts/close', { closing_cash: 0 });
  const shift = await post('/shifts/open', { opening_float: 20 });
  sql("delete from sync_queue where device_id like 'p4ui-%'");

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await browser.newPage();
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
  const cachedStock = () => page.evaluate((id) => {
    for (let i = 0; i < POS_STATE.products.length; i++) if (POS_STATE.products[i].id === id) return parseFloat(POS_STATE.products[i].stock_qty);
    return null;
  }, A);
  const deviceId = () => page.evaluate(() => DB.getDeviceId());

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));
  check('badge starts ONLINE', (await text('#syncStatus')) === 'ONLINE', await text('#syncStatus'));

  /* 1. Baseline online sale still works: 2 x 10 */
  await page.evaluate(() => posResetCart());
  await page.evaluate((id) => { posAddToCart(id); posAddToCart(id); }, A);
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '50'; });
  await click('#confirmCashBtn');
  await wait(1500);
  check('online sale completes', lastAlert().indexOf('Sale complete') === 0, lastAlert().split('\n')[0]);
  check('server stock 10 -> 8', serverStock() === 8, String(serverStock()));

  /* 2. Network goes down: badge flips, selling continues from cache */
  await page.setOfflineMode(true);
  await wait(800);
  check('badge shows OFFLINE', (await text('#syncStatus')) === 'OFFLINE', await text('#syncStatus'));

  alerts.length = 0;
  await page.evaluate(() => posResetCart());
  await page.evaluate((id) => { posAddToCart(id); posAddToCart(id); posAddToCart(id); }, A);
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '50'; });
  await click('#confirmCashBtn');
  await wait(1200);
  check('offline sale is saved on the device', lastAlert().indexOf('OFFLINE SALE') === 0, lastAlert().split('\n')[0]);
  check('offline alert shows total and change', lastAlert().indexOf('30.00') > -1 && lastAlert().indexOf('20.00') > -1, lastAlert().split('\n').join(' / '));
  check('badge counts the queued sale', (await text('#syncStatus')) === 'OFFLINE (1)', await text('#syncStatus'));
  check('server saw nothing yet', serverStock() === 8, String(serverStock()));
  check('device cache deducted stock 8 -> 5', (await cachedStock()) === 5, String(await cachedStock()));
  check('cart was cleared after queueing', (await page.evaluate(() => POS_STATE.cart.length)) === 0);

  /* 3. The device itself refuses to oversell its cache: 5 left, try 6 */
  await page.evaluate((id) => { for (let i = 0; i < 5; i++) posAddToCart(id); }, A);
  const cartQty = await page.evaluate(() => POS_STATE.cart.reduce((s, l) => s + l.qty, 0));
  check('five more allowed (exactly the cached stock)', cartQty === 5, String(cartQty));
  await page.evaluate((id) => posAddToCart(id), A);
  check('sixth blocked by the device stock guard', lastAlert().indexOf('Insufficient stock') === 0, lastAlert());
  check('cart still holds 5', (await page.evaluate(() => POS_STATE.cart.reduce((s, l) => s + l.qty, 0))) === 5);

  /* 4. Ring up the 5 offline as well, then reconnect */
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '100'; });
  await click('#confirmCashBtn');
  await wait(1200);
  check('second offline sale queued', lastAlert().indexOf('OFFLINE SALE') === 0 && (await text('#syncStatus')) === 'OFFLINE (2)', await text('#syncStatus'));

  await page.setOfflineMode(false);
  await wait(4000);
  const badge = await text('#syncStatus');
  check('badge back to ONLINE after drain', badge === 'ONLINE', badge);

  /* 5. Server truth: both sales landed once, stock exact, queue marked synced */
  check('server stock 8 -> 0', serverStock() === 0, String(serverStock()));
  const shiftTxns = Number(sql(`select count(*) from transactions where shift_id=${shift.id}`));
  check('exactly three transactions on the shift (no duplicates)', shiftTxns === 3, String(shiftTxns));
  const offCount = Number(sql(`select count(*) from transactions where is_offline and shift_id=${shift.id}`));
  check('both flagged offline on the open shift', offCount === 2, String(offCount));
  const dev = await deviceId();
  const pending = Number(sql(`select count(*) from sync_queue where device_id='${dev}' and not synced`));
  check('device queue fully drained on the server', pending === 0, String(pending));
  const refs = Number(sql(`select count(*) from sync_queue where device_id='${dev}' and synced and client_ref is not null`));
  check('synced rows carry client refs for replay protection', refs >= 2, String(refs));

  /* 6. Server-side view of the device queue (replay idempotency itself is covered in test-phase4-api.py) */
  const st = await api('/sync/status?device_id=' + encodeURIComponent(dev));
  check('sync status sees the device', st && st.device_id === dev && st.pending_count === 0, JSON.stringify(st));

  /* 7. Reloaded app is clean and stock truth is back in the catalog */
  await page.reload();
  await wait(2500);
  check('no script errors after reconnect and reload', errors.length === 0, errors.join(' | '));
  check('reloaded catalog shows server stock 0', (await cachedStock()) === 0, String(await cachedStock()));

  /* 8. Z-report shows the offline activity */
  const z = await post('/shifts/close', { closing_cash: 0 });
  check('Z-report counts the two offline sales', z && z.report && z.report.offline_sales_count === 2, JSON.stringify(z && z.report && z.report.offline_sales_count));
  check('Z-report offline total is 80.00', z && String(z.report.offline_sales_total) === '80.00', String(z && z.report && z.report.offline_sales_total));

  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} checks passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error('TEST CRASH:', e); process.exit(2); });
