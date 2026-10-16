/* Phase 5d UI test: the stored currency symbol is used everywhere amounts are shown,
 * and the last settings are kept on the device for when the API cannot be reached.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-phase5.js
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
const settings = (symbol) => authFetch(BASE + '/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: symbol, tax_rate: 0, low_stock_threshold: 5 }) });

async function run() {
  const A = Number(sql('select id from products where is_active order by category_id nulls last, name limit 1'));
  sql(`update products set stock_qty=10, sell_price=12.5 where id=${A}`);
  await settings('R');
  await authFetch(BASE + '/api/shifts/close', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"closing_cash":0}' });
  await authFetch(BASE + '/api/shifts/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"opening_float":0}' });

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await (await browser.createBrowserContext()).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());
  const text = (sel) => page.$eval(sel, (el) => el.textContent);

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  const tile = await page.evaluate(() => { const t = document.querySelector('.tile-price'); return t ? t.textContent : ''; });
  check('product tile uses R', tile === 'R12.50', tile);
  await page.evaluate((id) => { posAddToCart(id); posAddToCart(id); }, A);
  await wait(300);
  check('cart total uses R', (await text('#grandTotal')) === 'R25.00', await text('#grandTotal'));
  check('charge button uses R', (await text('#chargeBtn')) === 'CHARGE R25.00', await text('#chargeBtn'));
  const dollars = await page.evaluate(() => (document.body.innerText.match(/\$\d/g) || []).length);
  check('no $ amounts anywhere on the register', dollars === 0, dollars);

  await settings('€');
  await page.evaluate(() => loadSettings());
  await wait(800);
  check('changing the symbol redraws the cart', (await text('#grandTotal')) === '€25.00', await text('#grandTotal'));
  check('changing the symbol redraws the tiles', (await page.$eval('.tile-price', (el) => el.textContent)) === '€12.50');

  await page.setRequestInterception(true);
  page.on('request', (req) => (req.url().indexOf('/api/settings') > -1 ? req.abort() : req.continue()));
  await page.reload();
  await wait(2500);
  const offlineTile = await page.$eval('.tile-price', (el) => el.textContent);
  check('settings API down: last symbol still used', offlineTile === '€12.50', offlineTile);

  check('no script errors', errors.length === 0, errors.join(' | '));
  await settings('$');
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
