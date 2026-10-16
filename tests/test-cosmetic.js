/* Phone layout and polish: styled sign-in page, one-line header, nothing wider than a
 * 360px screen, money with thousands separators, local dates and times (Angola, UTC+1),
 * tap-to-open inventory and purchase rows, a single product panel per tap, the open-shift
 * Z report, and the Users list.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-cosmetic.js
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
const api = async (method, path, body) => {
  const r = await authFetch(BASE + '/api' + path, {
    method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status >= 400) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
};

async function run() {
  const A = Number(sql('select id from products where is_active order by id limit 1'));
  if ((await authFetch(BASE + '/api/shifts/current')).status === 404) await api('POST', '/shifts/open', { opening_float: 0 });
  const draft = await api('POST', '/purchases', { lines: [{ product_id: A, qty: '1', unit_cost: '1' }] });
  const sale = await api('POST', '/transactions', {
    lines: [{ product_id: A, qty: '1', sell_price: '6500' }], payment_cash: '6500',
  });
  const utc = new Date(sale.created_at);
  const luanda = new Date(utc.getTime() + 3600 * 1000);
  const pad = (n) => (n < 10 ? '0' : '') + n;
  const expectedTime = `${luanda.getUTCFullYear()}-${pad(luanda.getUTCMonth() + 1)}-${pad(luanda.getUTCDate())} ${pad(luanda.getUTCHours())}:${pad(luanda.getUTCMinutes())}`;

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await (await browser.createBrowserContext()).newPage();
  await page.emulateTimezone('Africa/Luanda');
  await page.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());
  const text = (sel) => page.$eval(sel, (el) => el.innerText);

  /* Sign-in page */
  await page.goto(BASE + '/index.html');
  await wait(800);
  const card = await page.$eval('.login-card', (el) => {
    const r = el.getBoundingClientRect();
    return { bg: getComputedStyle(el).backgroundColor, width: r.width, inputWidth: document.getElementById('username').getBoundingClientRect().width };
  });
  check('sign-in page is styled (white card, full-width fields)', card.bg === 'rgb(255, 255, 255)' && card.width <= 380 && card.inputWidth > 250, JSON.stringify(card));

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));

  /* Helpers available to every screen */
  const helpers = await page.evaluate(() => ({
    big: money(1234567.891), neg: money(-1500), zero: money(null),
    month: monthStartStr(), today: localDateStr(), time: localDateTime('2026-10-08T23:37:01.466160Z'),
  }));
  const sym = await page.evaluate(() => STORE_SETTINGS.currency_symbol || '$');
  check('money groups thousands', helpers.big === sym + '1,234,567.89' && helpers.neg === '-' + sym + '1,500.00' && helpers.zero === sym + '0.00', JSON.stringify(helpers));
  check('month starts on the 1st in local time', /-01$/.test(helpers.month), helpers.month);
  check('UTC 23:37 shows as next day 00:37 in Luanda', helpers.time === '2026-10-09 00:37', helpers.time);

  /* Every screen fits a 360px phone, header on one line */
  for (const name of ['pos', 'inventory', 'purchases', 'reports', 'customers', 'expenses', 'daysheet', 'users', 'importexport', 'settings']) {
    await page.evaluate((s) => showScreen(s), name);
    await wait(1000);
    const m = await page.evaluate((s) => {
      const screen = document.getElementById('screen-' + s);
      const title = document.getElementById('headerTitle');
      const badge = document.getElementById('shiftStatus');
      let widest = 0;
      const inScroller = (el) => {
        for (let p = el.parentElement; p && p !== screen; p = p.parentElement) {
          if (getComputedStyle(p).overflowX === 'auto') return true;
        }
        return false;
      };
      screen.querySelectorAll('*').forEach((el) => {
        if (inScroller(el)) return;
        const r = el.getBoundingClientRect();
        if (r.width && getComputedStyle(el).position !== 'fixed') widest = Math.max(widest, r.right);
      });
      return { widest: Math.round(widest), title: title.getBoundingClientRect().height, badge: badge.getBoundingClientRect().height, text: title.textContent };
    }, name);
    check(`screen ${name} fits 360px with a one-line header`, m.widest <= 361 && m.title <= 26 && m.badge <= 24, JSON.stringify(m));
    if (name === 'importexport') check('Import/Export title is readable', m.text === 'IMPORT / EXPORT', m.text);
  }

  /* Inventory: no row buttons, tap opens the product with stock actions */
  await page.evaluate(() => showScreen('inventory'));
  await wait(1500);
  check('inventory rows have no buttons', (await page.$$('#inventoryTableBody button')).length === 0);
  await page.evaluate((id) => document.querySelector(`#inventoryTableBody tr[data-id="${id}"]`).click(), A);
  await wait(1200);
  const editState = await page.evaluate(() => ({
    title: document.getElementById('productPanelTitle').textContent,
    actions: getComputedStyle(document.getElementById('productEditActions')).display,
    info: document.getElementById('productStockInfo').textContent,
    focused: document.activeElement && document.activeElement.id,
  }));
  check('tapping a row opens Edit Product with ADJUST STOCK / DELETE', editState.title === 'Edit Product' && editState.actions !== 'none' && /^In stock: /.test(editState.info), JSON.stringify(editState));
  check('editing does not pop up the keyboard', editState.focused !== 'editProductName', editState.focused);
  const numHeads = await page.$$eval('#inventoryTable th.num', (ths) => ths.length);
  check('numeric headers stay right-aligned after sorting', numHeads === 3, numHeads);
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });
  await page.$eval('#addProductBtn', (el) => el.click());
  await wait(800);
  const addState = await page.evaluate(() => ({
    stack: APP.panelStack.slice(),
    actions: getComputedStyle(document.getElementById('productEditActions')).display,
  }));
  check('+ opens the product panel once, without edit actions', addState.stack.join() === 'productPanel' && addState.actions === 'none', JSON.stringify(addState));
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });
  check('Clear All Products moved to Import/Export', !!(await page.$('#screen-importexport #deleteAllInventoryBtn')) && !(await page.$('#screen-inventory #deleteAllInventoryBtn')));

  /* Times in local time */
  await page.evaluate(() => document.getElementById('salesHistoryBtn').click());
  await wait(1500);
  const listed = await text('#salesPanel');
  check('Recent Sales shows the sale time in Luanda time', listed.indexOf(expectedTime) !== -1, expectedTime + ' not in ' + listed.slice(0, 200));
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });

  /* Report dates fit next to RUN */
  await page.evaluate(() => { showScreen('reports'); openReport('sales', 'Sales Summary'); });
  await wait(800);
  const dates = await page.evaluate(() => {
    const r = (id) => document.getElementById(id).getBoundingClientRect();
    return { from: r('reportDetailFrom').width, to: r('reportDetailTo').width, toRight: r('reportDetailTo').right, runLeft: r('runReportBtn').left, runRight: r('runReportBtn').right,
      fromValue: document.getElementById('reportDetailFrom').value };
  });
  check('report date fields and RUN fit side by side', dates.from > 90 && dates.to > 90 && dates.toRight <= dates.runLeft && dates.runRight <= 360, JSON.stringify(dates));
  check('report starts on the 1st of the month (local)', /-01$/.test(dates.fromValue), dates.fromValue);
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });

  /* Z report of the open shift */
  const shift = await api('GET', '/shifts/current');
  await page.evaluate((id) => openShiftZ(id), shift.id);
  await wait(1500);
  const z = await text('#zReportBody');
  check('open-shift Z report says "Still open"', z.indexOf('Still open') !== -1 && z.indexOf('Closed ') === -1, z.slice(0, 120));
  check('open-shift Z report has no counted cash or variance yet', z.indexOf('Counted cash') === -1 && z.indexOf('Variance') === -1 && z.indexOf('Expected cash so far') !== -1);
  const printable = await page.evaluate(() => formatZReport(Z_REPORT_STATE.current));
  check('printable Z report has no blank counted-cash lines', printable.indexOf('Counted cash') === -1 && printable.indexOf('\n\n\n') === -1);
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });

  /* Purchases: tap a draft row, delete it from the form */
  await page.evaluate(() => showScreen('purchases'));
  await wait(1500);
  check('purchase rows have no buttons', (await page.$$('#purchasesTableBody button')).length === 0);
  await page.evaluate(() => {
    document.body.classList.add('no-purchases-edit');
    document.querySelector('#purchasesTableBody tr').click();
  });
  await wait(1200);
  const viewOnly = await page.evaluate(() => ({
    footer: getComputedStyle(document.getElementById('purchaseFormFooter')).display,
    del: getComputedStyle(document.getElementById('deletePurchaseBtn')).display,
  }));
  check('a view-only user gets the draft read-only', viewOnly.footer === 'none' && viewOnly.del === 'none', JSON.stringify(viewOnly));
  await page.evaluate(() => { document.body.classList.remove('no-purchases-edit'); while (APP.panelStack.length) closeTopPanel(); });
  await page.evaluate(() => document.querySelector('#purchasesTableBody tr').click());
  await wait(1200);
  check('tapping a draft opens it with DELETE DRAFT', (await page.$eval('#deletePurchaseBtn', (el) => getComputedStyle(el).display)) !== 'none');
  await page.$eval('#deletePurchaseBtn', (el) => el.click());
  await wait(1500);
  const gone = await authFetch(`${BASE}/api/purchases/${draft.id}`);
  check('DELETE DRAFT removes it and closes the form', gone.status === 404 && (await page.evaluate(() => APP.panelStack.length)) === 0, gone.status);

  /* Customers: tap a row to open the account, edit and delete live there */
  const cust = await api('POST', '/customers', { name: 'Cliente ' + Date.now().toString(36), phone: '923000000' });
  await page.evaluate(() => showScreen('customers'));
  await wait(1200);
  check('customer rows have no buttons', (await page.$$('#customersList button')).length === 0);
  await page.evaluate((name) => {
    const row = Array.prototype.find.call(document.querySelectorAll('#customersList tr'), (tr) => tr.innerText.indexOf(name) !== -1);
    row.click();
  }, cust.name);
  await wait(1200);
  const ledger = await page.evaluate(() => ({
    title: document.getElementById('ledgerCustomerName').textContent,
    edit: document.getElementById('ledgerEditBtn').offsetParent !== null,
    del: document.getElementById('ledgerDeleteBtn').offsetParent !== null,
  }));
  check('tapping a customer opens their account with EDIT / DELETE', ledger.title === cust.name && ledger.edit && ledger.del, JSON.stringify(ledger));
  await page.$eval('#ledgerEditBtn', (el) => el.click());
  await wait(1000);
  await page.$eval('#editCustomerName', (el) => { el.value = el.value + ' Lda'; });
  await page.$eval('#saveCustomerBtn', (el) => el.click());
  await wait(1500);
  const afterEdit = await page.evaluate(() => ({ stack: APP.panelStack.slice(), title: document.getElementById('ledgerCustomerName').textContent }));
  check('editing from the account refreshes it, panel open once', afterEdit.stack.join() === 'customerLedgerPanel' && afterEdit.title === cust.name + ' Lda', JSON.stringify(afterEdit));
  await page.$eval('#ledgerDeleteBtn', (el) => el.click());
  await wait(1500);
  const deleted = await authFetch(`${BASE}/api/customers/${cust.id}`);
  check('DELETE removes the customer and closes the account', deleted.status === 404 && (await page.evaluate(() => APP.panelStack.length)) === 0, deleted.status);

  /* Expenses: rows have no buttons; DELETE lives in the edit form */
  const ecat = await api('POST', '/expenses/categories', { name: 'Cosmetic ' + Date.now() });
  const exp = await api('POST', '/expenses', { category_id: ecat.id, amount: 7, description: 'cosmetic row', expense_date: helpers.today, paid_from_drawer: false });
  await page.evaluate(() => showScreen('expenses'));
  await wait(1200);
  check('expense rows have no buttons', (await page.$$('#expensesList button')).length === 0);
  await page.evaluate((d) => {
    Array.prototype.find.call(document.querySelectorAll('#expensesList tr'), (tr) => tr.innerText.indexOf(d) !== -1).click();
  }, exp.description);
  await wait(1200);
  check('tapping an expense opens it with DELETE EXPENSE', await page.$eval('#deleteExpenseBtn', (el) => el.offsetParent !== null));
  await page.$eval('#deleteExpenseBtn', (el) => el.click());
  await wait(1500);
  const expGone = await authFetch(`${BASE}/api/expenses/${exp.id}`);
  check('DELETE EXPENSE removes it and closes the form', expGone.status === 404 && (await page.evaluate(() => APP.panelStack.length)) === 0, expGone.status);
  await page.$eval('#addExpenseBtn', (el) => el.click());
  await wait(800);
  check('a new expense form has no DELETE button', await page.$eval('#deleteExpenseBtn', (el) => el.offsetParent === null));
  await page.evaluate(() => closePanel('expenseFormPanel'));

  /* Users: no deactivate button on your own account */
  await page.evaluate(() => showScreen('users'));
  await wait(1200);
  const self = await page.evaluate(() => {
    const row = Array.prototype.find.call(document.querySelectorAll('#usersList tr'), (tr) => tr.innerText.indexOf('@admin') !== -1);
    return row ? { buttons: row.querySelectorAll('button').length, text: row.innerText } : null;
  });
  check('own account shows "you" instead of DEACTIVATE', self && self.buttons === 0 && /you/.test(self.text), JSON.stringify(self));

  /* Settings: shop time zone */
  const before = await api('GET', '/settings');
  await page.evaluate(() => showScreen('settings'));
  await wait(800);
  const zones = await page.$$eval('#settingTimezone option', (os) => os.map((o) => o.value));
  check('Settings offers the shop time zone', zones.indexOf('Africa/Luanda') !== -1 && (await page.$eval('#settingTimezone', (el) => el.value)) === before.timezone, zones.join(','));
  await page.select('#settingTimezone', 'Africa/Luanda');
  await page.$eval('#saveSettingsBtn', (el) => el.click());
  await wait(1200);
  const saved = await api('GET', '/settings');
  check('saving Settings stores the time zone and keeps the rest', saved.timezone === 'Africa/Luanda' && saved.currency_symbol === before.currency_symbol, JSON.stringify(saved));
  await api('PUT', '/settings', before);

  check('no script errors at the end', errors.length === 0, errors.join(' | '));
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
