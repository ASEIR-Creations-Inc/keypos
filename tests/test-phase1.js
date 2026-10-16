/* Phase 1 regression test. Run against a TEST copy of the database, never production:
 *   BASE=http://127.0.0.1:8095 node test-phase1.js
 * Self-contained: opens its own shift if none is open and tops up product stock. */
const { execSync } = require('child_process');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const sql = (q) => execSync(`sudo -u postgres psql -d pos_test -tAc "${q}"`).toString().trim();

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined ? '  -> ' + detail : ''));
};

async function api(path, options) {
  const r = await authFetch(BASE + '/api' + path, options);
  return r.json();
}

async function run() {
  const openShifts = await api('/shifts?status=open&limit=1');
  if (!openShifts.length) {
    await api('/shifts/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ opening_float: 50 }) });
  }
  /* Seed the product the register lists first (category, name order) so the
   * price prompt fires deterministically: sell_price 0 forces the prompt. */
  const seedPid = Number(sql('select id from products where is_active order by category_id nulls last, name limit 1'));
  sql(`update products set stock_qty = greatest(stock_qty, 8), sell_price = 0 where id=${seedPid}`);

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

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);

  check('no script errors on load', errors.length === 0, errors.join(' | '));
  check('safeAddListener defined', await page.evaluate(() => typeof safeAddListener === 'function'));
  check('open shift detected', await page.evaluate(() => !!(POS_STATE.shift && POS_STATE.shift.id)));
  const settings = await api('/settings');
  check('settings applied to drawer', (await page.$eval('#drawerStoreName', (e) => e.textContent)) === settings.store_name);

  /* Sale with tax */
  await page.evaluate(() => { POS_STATE.cart = []; posRenderCart(); });
  const product = await page.evaluate(() => POS_STATE.products.filter((p) => parseFloat(p.stock_qty) > 5)[0]);
  const stockBefore = parseFloat(product.stock_qty);
  promptAnswers.push('20');
  await page.evaluate((id) => posAddToCart(id), product.id);
  await click('#chargeBtn');
  await wait(300);
  const expected = (20 * (1 + parseFloat(settings.tax_rate) / 100)).toFixed(2);
  const shown = await page.$eval('#payTotalDisplay', (e) => e.textContent);
  check('payment panel shows taxed total', shown === '$' + expected, shown);
  await click('#payCardBtn');
  await click('#confirmCardBtn');
  await wait(1500);
  check('card sale completes', lastAlert().indexOf('Sale complete') === 0 && lastAlert().indexOf(expected) > -1, lastAlert().split('\n').join(' / '));
  check('cart emptied after sale', await page.evaluate(() => POS_STATE.cart.length === 0));
  const after = await api('/products/' + product.id);
  check('stock deducted', parseFloat(after.stock_qty) === stockBefore - 1, stockBefore + ' -> ' + after.stock_qty);

  /* Cart item editor buttons */
  promptAnswers.push('5');
  await page.evaluate((id) => posAddToCart(id), product.id);
  await page.evaluate((id) => openCartItem(id), product.id);
  await click('#cartItemPlus');
  await click('#applyCartItemBtn');
  check('cart item +/apply work', await page.evaluate(() => POS_STATE.cart[0].qty === 2));
  await page.evaluate((id) => openCartItem(id), product.id);
  await click('#removeCartItemBtn');
  check('cart item remove works', await page.evaluate(() => POS_STATE.cart.length === 0));

  /* Purchases: list, post new, draft edit, delete */
  const posBefore = (await api('/purchases')).length;
  await page.evaluate(() => showScreen('purchases'));
  await wait(1500);
  const rows = await page.$$eval('#purchasesTableBody tr', (r) => r.length);
  check('purchases list renders', rows === posBefore, rows + ' rows');

  const addLine = async (qty, cost) => {
    await page.type('#lineProduct', product.name);
    await wait(200);
    await page.$$eval('#productDropdown div', (divs, name) => divs.filter((d) => d.textContent.indexOf(name + ' (') === 0)[0].click(), product.name);
    await page.type('#lineQty', String(qty));
    await page.type('#lineCost', String(cost));
    await click('#addPurchaseLineBtn');
  };
  await click('#newPurchaseBtn');
  await page.type('#purchaseSupplier', 'E2E Supplier');
  await addLine(5, 2);
  check('purchase line added', (await page.$eval('#purchaseTotalDisplay', (e) => e.textContent)) === '$10.00');
  await click('#postPurchaseBtn');
  await wait(2000);
  const newest = (await api('/purchases'))[0];
  check('purchase posted with new supplier', newest.status === 'posted' && newest.supplier_name === 'E2E Supplier', newest.status + ' / ' + newest.supplier_name);
  check('purchase added stock', parseFloat((await api('/products/' + product.id)).stock_qty) === stockBefore - 1 + 5);

  await click('#newPurchaseBtn');
  await addLine(1, 3);
  await click('#saveDraftPurchaseBtn');
  await wait(1500);
  const draft = (await api('/purchases'))[0];
  check('draft saved without supplier', draft.status === 'draft' && draft.supplier_id === null);
  await page.evaluate((id) => openPurchase(id), draft.id);
  await wait(800);
  check('draft opens for edit', (await page.$eval('#purchaseLinesList', (e) => e.children.length)) === 1);
  await page.type('#purchaseSupplier', 'E2E Supplier');
  await click('#saveDraftPurchaseBtn');
  await wait(1500);
  check('draft supplier updated', (await api('/purchases/' + draft.id)).supplier_name === 'E2E Supplier');
  await page.evaluate((id) => deletePurchaseOrder(id), draft.id);
  await wait(1500);
  check('draft deleted', (await api('/purchases')).length === posBefore + 1);

  /* Customer edit (was POST -> 405) */
  const customer = (await api('/customers'))[0];
  await page.evaluate((id) => editCustomer(id), customer.id);
  await wait(800);
  await page.$eval('#editCustomerPhone', (e) => { e.value = '555-0101'; });
  await click('#saveCustomerBtn');
  await wait(1200);
  check('customer edit saves', (await api('/customers/' + customer.id)).phone === '555-0101');

  /* Expense save button */
  const expBefore = (await api('/expenses')).items.length;
  await page.evaluate(() => showScreen('expenses'));
  await wait(1200);
  await click('#addExpenseBtn');
  await page.$eval('#expenseCategory', (e) => { e.selectedIndex = 1; });
  await page.type('#expenseAmount', '7.5');
  await click('#addExpenseLineBtn');
  await click('#saveExpenseBtn');
  await wait(1500);
  check('expense saves', (await api('/expenses')).items.length === expBefore + 1);

  /* Reports with fixed field names */
  const runReport = async (key) => {
    await page.evaluate((k) => { openReport(k, k); document.getElementById('reportDetailFrom').value = '2026-05-01'; }, key);
    await click('#runReportBtn');
    await wait(1500);
    return page.$eval('#reportDetailContent', (e) => e.innerText);
  };
  const cashier = await runReport('cashier');
  check('cashier report shows gross/net', /Gross/.test(cashier) && /Net/.test(cashier) && !/Failed/.test(cashier));
  const tax = await runReport('tax');
  check('tax report loads with rows', /Tax Amount/.test(tax) && /\d{4}-\d{2}-\d{2}/.test(tax), tax.split('\n').slice(0, 3).join(' / '));
  await click('#reportDetailBack');

  /* Settings */
  await page.evaluate(() => showScreen('settings'));
  check('settings form populated', (await page.$eval('#settingStoreName', (e) => e.value)) === settings.store_name);
  await page.$eval('#settingTaxRate', (e) => { e.value = '0'; });
  await click('#saveSettingsBtn');
  await wait(1200);
  check('settings save', lastAlert() === 'Settings saved.' && (await page.evaluate(() => POS_STATE.taxRate)) === 0);

  /* Close shift: the Z report opens as a panel with refunds and the shift's audit trail */
  promptAnswers.push('100');
  await click('#closeShiftBtn');
  await wait(2000);
  check('close shift opens the Z report panel', await page.evaluate(() => document.getElementById('zReportPanel').classList.contains('active')));
  const zBody = await text('#zReportBody');
  check('Z report shows totals, refunds and activity',
    /Gross sales/.test(zBody) && /Refunded receipts/.test(zBody) && /Shift activity/.test(zBody), zBody.slice(0, 100));
  check('UI shows shift closed', (await page.$eval('#shiftStatus', (e) => e.textContent)) === 'SHIFT CLOSED');

  check('no script errors during run', errors.length === 0, errors.join(' | '));
  await browser.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log('\n' + (results.length - failed) + '/' + results.length + ' passed');
  process.exit(failed ? 1 : 0);
}

run().catch((e) => { console.error(e); process.exit(1); });
