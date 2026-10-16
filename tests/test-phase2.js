/* Phase 2/3 UI test: discounts charged, held tickets, whole-receipt refund with
 * re-issue, account refunds, ledger.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-phase2.js
 * Opens a shift if none is open; sets tax to 10% and two products' stock to 20. */
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

async function run() {
  const [A, B] = sql('select id from products where is_active order by id limit 2').split('\n').map(Number);
  sql(`update products set stock_qty=20, sell_price=0 where id in (${A},${B})`);
  await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 10, low_stock_threshold: 5 }) });
  const openShifts = await api('/shifts?status=open&limit=1');
  if (!openShifts.length) {
    await api('/shifts/open', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opening_float: 0 }) });
  }

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await browser.newPage();
  const errors = [];
  const alerts = [];
  const promptAnswers = [];
  const confirmAnswers = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => {
    if (d.type() === 'prompt') return d.accept(promptAnswers.shift() || '');
    if (d.type() === 'alert') alerts.push(d.message());
    if (d.type() === 'confirm' && confirmAnswers.length) return confirmAnswers.shift() ? d.accept() : d.dismiss();
    return d.accept();
  });
  const click = (sel) => page.$eval(sel, (el) => el.click());
  const text = (sel) => page.$eval(sel, (el) => el.textContent);
  const lastAlert = () => alerts[alerts.length - 1] || '';
  const stock = (id) => parseFloat(sql(`select stock_qty from products where id=${id}`));

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));

  /* Cart: 2 x A @ 10, 1 x B @ 30 with $5 line discount, then 10% off the sale.
   * subtotal 50, line disc 5, cart disc 4.50, taxable 40.50, tax 4.05, total 44.55 */
  await page.evaluate(() => { posResetCart(); });
  promptAnswers.push('10');
  await page.evaluate((id) => posAddToCart(id), A);
  await page.evaluate((id) => posAddToCart(id), A);
  promptAnswers.push('30');
  await page.evaluate((id) => posAddToCart(id), B);
  await page.evaluate((id) => openCartItem(id), B);
  await page.$eval('#cartItemDiscount', (el) => { el.value = '5'; });
  await click('#applyCartItemBtn');
  promptAnswers.push('10');
  await click('#discBtn');
  await wait(200);
  check('cart shows discount', (await text('#discountDisplay')).indexOf('-$9.50') === 0, await text('#discountDisplay'));
  check('cart shows tax on discounted amount', (await text('#tax')) === '$4.05', await text('#tax'));
  check('charge button shows discounted total', (await text('#chargeBtn')) === 'CHARGE $44.55', await text('#chargeBtn'));

  /* Hold and resume keeps the discounts */
  await click('#holdBtn');
  await wait(800);
  check('ticket held', lastAlert() === 'Ticket saved.' && (await page.evaluate(() => POS_STATE.cart.length)) === 0, lastAlert());
  check('holding did not touch stock', stock(A) === 20 && stock(B) === 20);
  const held = (await api('/transactions/held'))[0];
  await page.evaluate((id) => posResumeTicket(id), held.id);
  await wait(800);
  check('resumed ticket restores total with discounts', (await text('#chargeBtn')) === 'CHARGE $44.55', await text('#chargeBtn'));
  check('resumed ticket removed from held list', !(await api('/transactions/held')).some((t) => t.id === held.id));

  /* Pay cash; the server must charge exactly what the cart showed */
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '50'; });
  await click('#confirmCashBtn');
  await wait(1500);
  check('cash sale completes at 44.55', lastAlert().indexOf('Sale complete') === 0 && lastAlert().indexOf('44.55') > -1, lastAlert().split('\n').join(' / '));
  const sale = (await api('/transactions?limit=1'))[0];
  check('server charged 44.55 with 9.50 discount', sale.total_amount === '44.55' && sale.discount_amount === '9.50', sale.total_amount + ' / ' + sale.discount_amount);
  check('both lines deducted stock', stock(A) === 18 && stock(B) === 19, stock(A) + ' / ' + stock(B));
  check('cart discount cleared after sale', await page.evaluate(() => POS_STATE.cartDiscountPct === 0));
  await wait(500);
  check('stock refreshed in the register', await page.evaluate((id) => parseFloat(POS_STATE.products.filter((p) => p.id === id)[0].stock_qty), A) === 18);

  /* Recent sales: whole-receipt refund, then re-issue of the items the customer kept */
  await page.evaluate(() => { closeDrawer(); });
  await click('#salesHistoryBtn');
  await wait(1200);
  check('recent sales lists the sale', (await text('#salesList')).indexOf(sale.ref_number) > -1);
  await page.evaluate((id) => showSaleDetail(id), sale.id);
  await wait(800);
  check('refund button shown, reissue hidden on a completed sale', await page.evaluate(() =>
    document.getElementById('saleRefundBtn').style.display !== 'none' &&
    document.getElementById('saleReissueBtn').style.display === 'none'));
  promptAnswers.push('customer changed mind');
  await click('#saleRefundBtn');            /* confirm refund -> reason -> slip alert -> confirm re-issue (accepted) */
  await wait(1800);
  check('sale now refunded', (await api('/transactions/' + sale.id)).status === 'refunded');
  check('all stock back on the shelf', stock(A) === 20 && stock(B) === 20, stock(A) + '/' + stock(B));
  check('refund receipt shown with RFD number and reason',
    alerts.some((a) => a.indexOf('REFUND RECEIPT') === 0 && a.indexOf('RFD-') > -1 && a.indexOf('customer changed mind') > -1),
    alerts.slice(-2).join(' | '));
  check('re-issue loaded the refunded items into the cart',
    lastAlert().indexOf('Items loaded') === 0 &&
    (await text('#chargeBtn')) === 'CHARGE $44.55' &&
    await page.evaluate((id) => POS_STATE.reissueOfId === id, sale.id), lastAlert() + ' / ' + await text('#chargeBtn'));

  /* Customer kept only the A items: drop B, then charge the re-issued receipt */
  await page.evaluate((id) => posUpdateQty(id, -1), B);
  await wait(200);
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '50'; });
  await click('#confirmCashBtn');
  await wait(1500);
  check('re-issue sale completes', lastAlert().indexOf('Sale complete') === 0, lastAlert());
  const reissue = (await api('/transactions?limit=1'))[0];
  check('re-issue linked to the refunded receipt', reissue.reissue_of_ref === sale.ref_number, reissue.reissue_of_ref);
  check('refunded receipt shows what re-issued it', (await api('/transactions/' + sale.id)).reissued_as_ref === reissue.ref_number);
  check('re-issue deducted stock again (A only)', stock(A) === 18 && stock(B) === 20, stock(A) + '/' + stock(B));
  check('re-issue flag cleared after the sale', await page.evaluate(() => POS_STATE.reissueOfId === null));

  /* Refunded receipt detail: refund info, no second refund, no second re-issue */
  await click('#salesHistoryBtn');
  await wait(1000);
  await page.evaluate((id) => showSaleDetail(id), sale.id);
  await wait(800);
  const detail = await text('#saleDetailBody');
  check('refund info shown with reason and RFD number', detail.indexOf('REFUNDED') > -1 && detail.indexOf('customer changed mind') > -1 && detail.indexOf('RFD-') > -1, detail.slice(0, 120));
  check('refund and reissue buttons hidden once refunded and re-issued', await page.evaluate(() =>
    document.getElementById('saleRefundBtn').style.display === 'none' &&
    document.getElementById('saleReissueBtn').style.display === 'none'));

  /* Account sale, then a whole-receipt refund clears the balance again */
  const cust = await api('/customers', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'UI Ledger Test', credit_limit: 0 }) });
  await page.evaluate(() => posResetCart());
  await page.evaluate((id) => posAddToCart(id), A);
  await click('#chargeBtn');
  await wait(300);
  await click('#payAccountBtn');
  await wait(800);
  await page.select('#accountCustomerSelect', String(cust.id));
  await click('#confirmAccountBtn');
  await wait(1500);
  check('account sale completes', lastAlert().indexOf('Sale complete') === 0, lastAlert());
  check('customer charged 11.00', (await api('/customers/' + cust.id)).balance === '11.00');
  const acct = (await api('/transactions?limit=1'))[0];
  await page.evaluate((id) => showSaleDetail(id), acct.id);
  await wait(800);
  promptAnswers.push('sold on account by mistake');
  confirmAnswers.push(true, false);          /* accept the refund, decline the re-issue offer */
  await click('#saleRefundBtn');
  await wait(1500);
  check('account refund clears the balance and restores stock',
    (await api('/customers/' + cust.id)).balance === '0.00' && stock(A) === 18,
    (await api('/customers/' + cust.id)).balance + '/' + stock(A));

  /* Ledger view */
  await page.evaluate((id) => showCustomerDetail(id), cust.id);
  await wait(1000);
  const ledger = await text('#ledgerEntries');
  check('ledger shows running balances', /Bal \$/.test(ledger) && ledger.indexOf('undefined') === -1, ledger.slice(0, 120));

  check('no script errors during run', errors.length === 0, errors.join(' | '));
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
