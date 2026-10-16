/* Phase 3 UI test: audited stock adjustments, drawer expenses, payment methods,
 * the Z-report panel (refunds + shift activity) and the Shift Reports browser.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-phase3.js
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
  sql(`update products set stock_qty=20, sell_price=10 where id=${A}`);
  await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 10, low_stock_threshold: 5 }) });
  const openShifts = await api('/shifts?status=open&limit=1');
  if (openShifts.length) await post('/shifts/close', { closing_cash: 0 });
  const shift = await post('/shifts/open', { opening_float: 20 });
  let cat = await post('/expenses/categories', { name: 'UI Test Cat' });
  if (!cat.id) cat = (await api('/expenses/categories')).filter((c) => c.name === 'UI Test Cat')[0];
  const cust = await post('/customers', { name: 'UI Method Test', credit_limit: 0 });
  sql(`update customers set balance=50 where id=${cust.id}`);

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await browser.newPage();
  const errors = [];
  const alerts = [];
  const promptAnswers = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => {
    if (d.type() === 'prompt') return d.accept(promptAnswers.shift() || '');
    if (d.type() === 'alert') alerts.push(d.message());
    return d.accept();
  });
  const click = (sel) => page.$eval(sel, (el) => el.click());
  const text = (sel) => page.$eval(sel, (el) => el.textContent);
  const lastAlert = () => alerts[alerts.length - 1] || '';
  const stock = () => parseFloat(sql(`select stock_qty from products where id=${A}`));

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));

  /* 1. Audited stock adjustment from the Inventory screen */
  await page.evaluate(() => showScreen('inventory'));
  await wait(1200);
  await page.evaluate((id) => document.querySelector(`#inventoryTableBody tr[data-id="${id}"]`).click(), A);
  await wait(1000);
  check('tapping a product shows ADJUST STOCK', await page.$eval('#productAdjustBtn', (el) => el.offsetParent !== null));
  promptAnswers.push('-2', 'broken in the back room');
  await click('#productAdjustBtn');
  await wait(1500);
  check('adjustment applied and confirmed', lastAlert().indexOf('Stock updated') === 0 && stock() === 18, lastAlert() + ' / ' + stock());
  check('product form shows the new stock', (await text('#productStockInfo')).indexOf('In stock: 18') === 0, await text('#productStockInfo'));
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });
  const adjAudit = await api(`/audit?shift_id=${shift.id}&action=stock_adjusted`);
  check('adjustment wrote an audit entry with the reason',
    adjAudit.entries.some((e) => e.summary.indexOf('broken in the back room') > -1), JSON.stringify(adjAudit.entries).slice(0, 120));

  /* 2. Drawer expense through the Expenses screen */
  await page.evaluate(() => showScreen('expenses'));
  await wait(800);
  await click('#addExpenseBtn');
  await wait(300);
  await page.$eval('#expenseCategory', (el, catId) => { el.value = String(catId); }, cat.id);
  await page.$eval('#expenseAmount', (el) => { el.value = '6.50'; });
  await page.$eval('#expenseDesc', (el) => { el.value = 'ui test drawer expense'; });
  await page.$eval('#expenseDrawer', (el) => { el.checked = true; });
  await click('#addExpenseLineBtn');
  await wait(200);
  check('expense line shows the DRAWER tag', (await text('#expenseLinesList')).indexOf('DRAWER') > -1);
  await click('#saveExpenseBtn');
  await wait(1500);
  const drawerExpense = sql(`select count(*) from expenses where shift_id=${shift.id} and paid_from_drawer and description='ui test drawer expense'`);
  check('drawer expense booked to the open shift', drawerExpense === '1', drawerExpense);

  /* 3. Customer payment with a method */
  await page.evaluate((id) => showCustomerDetail(id), cust.id);
  await wait(1200);
  await page.$eval('#paymentAmount', (el) => { el.value = '20'; });
  await page.select('#paymentMethod', 'card');
  await click('#receivePaymentBtn');
  await wait(1500);
  check('payment alert names the method', lastAlert().indexOf('(card)') > -1, lastAlert());
  check('payment stored as card and booked to the shift',
    sql(`select count(*) from customer_payments where customer_id=${cust.id} and method='card' and shift_id=${shift.id}`) === '1');

  /* 4. Sale + refund through the API, then close the shift and read the Z panel */
  const sale = await post('/transactions', { lines: [{ product_id: A, qty: 1, sell_price: 10, discount: 0 }], payment_cash: 11 });
  await post(`/transactions/${sale.id}/refund`, { reason: 'ui z-report test' });
  promptAnswers.push('0');
  await click('#closeShiftBtn');
  await wait(2500);
  check('close shift opens the Z panel', await page.evaluate(() => document.getElementById('zReportPanel').classList.contains('active')));
  const zBody = await text('#zReportBody');
  check('Z panel lists the refunded receipt with its reason',
    /Refunded receipts \(1\)/.test(zBody) && zBody.indexOf('ui z-report test') > -1 && zBody.indexOf(sale.ref_number) > -1, zBody.slice(0, 150));
  check('Z panel shows the shift activity trail',
    /Shift activity/.test(zBody) && zBody.indexOf('broken in the back room') > -1 &&
    zBody.indexOf('ui test drawer expense') >= 0 && /Customer payment/i.test(zBody), zBody.slice(0, 200));
  check('Z panel shows payments and drawer expenses',
    zBody.indexOf('Customer payments') > -1 && zBody.indexOf('Drawer expenses') > -1);
  check('print button present', await page.evaluate(() => !!document.getElementById('zReportPrintBtn')));
  await page.evaluate(() => closePanel('zReportPanel'));

  /* 5. Shift Reports browser reopens any closed shift's Z report */
  await page.evaluate(() => showScreen('reports'));
  await wait(500);
  await click('#btnShiftReports');
  await wait(1200);
  const listBody = await text('#reportDetailContent');
  check('shift reports lists shifts with variance', /Shift #\d+/.test(listBody) && listBody.indexOf('CLOSED') > -1, listBody.slice(0, 100));
  await page.evaluate((id) => openShiftZ(id), shift.id);
  await wait(1500);
  check('tapping a shift reopens its Z report',
    await page.evaluate(() => document.getElementById('zReportPanel').classList.contains('active')) &&
    (await text('#zReportBody')).indexOf('ui z-report test') > -1);

  check('no script errors during run', errors.length === 0, errors.join(' | '));
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
