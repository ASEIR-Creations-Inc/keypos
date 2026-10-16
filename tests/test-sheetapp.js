/* KEYPOS Sheet app UI test: a Day Sheet user signs in and only gets the Sheet app, fills in
 * a sheet with type-ahead product search, keeps working offline, sends it; the admin
 * returns it with a note, the employee fixes and resends, and the admin approves it.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-sheetapp.js
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
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + JSON.stringify(detail) : ''));
};

async function api(p, options) {
  const r = await authFetch(BASE + '/api' + p, options);
  return r.status === 204 ? null : r.json();
}
const send = (method, p, body) => api(p, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

async function until(fn, timeout) {
  const end = Date.now() + (timeout || 8000);
  while (Date.now() < end) {
    if (await fn()) return true;
    await wait(150);
  }
  return false;
}

function watch(page, label, errors, dialogs) {
  page.on('pageerror', (e) => errors.push(label + ': ' + e.message));
  page.on('dialog', async (d) => {
    dialogs.push({ type: d.type(), message: d.message() });
    if (d.type() === 'prompt') return d.accept(dialogs.answer || '');
    return d.accept();
  });
}

async function run() {
  const tag = Date.now().toString(36).toUpperCase();
  const famoso = await send('POST', '/products', { name: `ZZ${tag} WSK FAMOSO 250ML`, sell_price: '0', stock_qty: '3' });
  const agua = await send('POST', '/products', { name: `ZZ${tag} AGUA LEVITA 1.5LT`, sell_price: '4', stock_qty: '10' });
  await send('POST', '/expenses/categories', { name: `ZZ${tag} Gelo` });
  const username = `sheet_${tag.toLowerCase()}`;
  const created = await send('POST', '/users', { name: 'Ana Folha', username, password: 'sheet-pass-1', role: 'sheet' });
  check('admin can create a Day Sheet user', created.role === 'sheet', created);
  const settingsBefore = await api('/settings');
  await send('PUT', '/settings', { store_name: 'KEYPOS', currency_symbol: 'Kz', tax_rate: 0, low_stock_threshold: 5 });
  await send('POST', '/shifts/close', { closing_cash: 0 });
  await send('POST', '/shifts/open', { opening_float: 0 });

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const errors = [];
  const empDialogs = [];
  const admDialogs = [];
  const emp = await (await browser.createBrowserContext()).newPage();
  const adm = await (await browser.createBrowserContext()).newPage();
  watch(emp, 'sheet app', errors, empDialogs);
  watch(adm, 'pos', errors, admDialogs);
  await emp.setViewport({ width: 400, height: 800 });

  /* 1. The Day Sheet user signs in on the normal login and lands in the Sheet app only. */
  await emp.goto(BASE + '/index.html');
  await emp.type('#username', username);
  await emp.type('#password', 'sheet-pass-1');
  await emp.click('#loginBtn');
  await until(() => emp.url().indexOf('/sheet/') !== -1);
  check('Day Sheet user lands in /sheet/ after signing in', emp.url().indexOf('/sheet/') !== -1, emp.url());
  await emp.goto(BASE + '/pos.html');
  await until(() => emp.url().indexOf('/index.html') !== -1);
  check('opening pos.html gives a Day Sheet user only the KEYPOS sign-in', emp.url().indexOf('/index.html') !== -1, emp.url());
  await emp.goto(BASE + '/sheet/');
  await emp.waitForSelector('#appView:not(.hidden)');
  check('POS link hidden for a Day Sheet user', await emp.$eval('#posLink', (el) => el.classList.contains('hidden')));
  check('app opens in Portuguese', (await emp.$eval('#newSheetBtn', (el) => el.textContent)).indexOf('NOVA FOLHA') !== -1);

  /* 2. New sheet: gets its DS- code from the server. */
  await emp.click('#newSheetBtn');
  const coded = await until(() => emp.$eval('#barTitle', (el) => /^DS-/.test(el.textContent)));
  const code = await emp.$eval('#barTitle', (el) => el.textContent);
  check('new sheet gets a DS- code', coded, code);

  /* 3. Type-ahead: any part of the name, words in any order, narrows on every letter. */
  await emp.type('#productSearch', 'famo');
  const one = await emp.$$eval('#searchResults .result', (els) => els.map((e) => e.textContent));
  check('typing part of a word finds the product', one.length >= 1 && one.every((t) => /FAMOSO/.test(t)) && one.some((t) => t.indexOf(tag) !== -1), one);
  check('product with stock shows no stock warning', one.filter((t) => t.indexOf(tag) !== -1).every((t) => t.indexOf('SEM STOCK') === -1), one);
  await emp.$eval('#productSearch', (el) => { el.value = ''; });
  await emp.type('#productSearch', `250ml zz${tag.toLowerCase()}`);
  const swapped = await emp.$$eval('#searchResults .result', (els) => els.map((e) => e.textContent));
  check('words in any order still match', swapped.length === 1 && /FAMOSO/.test(swapped[0]), swapped);
  await emp.click('#searchResults .result');
  check('picking a result adds a line and clears the search',
    (await emp.$$('#lines .row')).length === 1 && (await emp.$eval('#productSearch', (el) => el.value)) === '');
  check('line without a price is amber SEM PREÇO',
    await emp.$eval('#line-0', (el) => el.className === 'row warn' && el.textContent.indexOf('SEM PREÇO') !== -1));

  await emp.type('[data-line="0"][data-f="price"]', '2.5');
  await emp.$eval('[data-line="0"][data-f="qty"]', (el) => { el.value = ''; });
  await emp.type('[data-line="0"][data-f="qty"]', '5');
  check('more than the stock turns the whole line red SEM STOCK',
    await emp.$eval('#line-0', (el) => el.className === 'row bad' && el.textContent.indexOf('SEM STOCK') !== -1));
  check('the stock count itself is not shown', await emp.$eval('#line-0', (el) => !/\b3\b/.test(el.querySelector('.row-status').textContent)));
  check('send is disabled while there are problems', await emp.$eval('#sendBtn', (el) => el.disabled));
  await emp.$eval('[data-line="0"][data-f="qty"]', (el) => { el.value = ''; });
  await emp.type('[data-line="0"][data-f="qty"]', '2');
  check('line within stock is green ✓', await emp.$eval('#line-0', (el) => el.className === 'row ok'));

  await emp.type('#productSearch', `levita zz${tag.toLowerCase()}`);
  await emp.click('#searchResults .result');
  check('fixed price fills in (and can be changed)', (await emp.$eval('[data-line="1"][data-f="price"]', (el) => el.value)) === '4');
  check('newest line is listed first', await emp.$eval('#lines .row', (el) => el.id === 'line-1'));

  /* 4. Expenses: category optional, Caixa/Outro choice. */
  await emp.click('.tab[data-tab="expenses"]');
  await emp.click('#addExpenseBtn');
  check('expense without amount is amber', await emp.$eval('#exp-0', (el) => el.className === 'row warn'));
  const options = await emp.$$eval('[data-exp="0"][data-f="category_id"] option', (els) => els.map((e) => e.textContent));
  check('category list comes from the POS (optional first)', options.length >= 2 && /opcional/.test(options[0]), options);
  await emp.type('[data-exp="0"][data-f="amount"]', '1');
  check('no "paid from" is flagged', await emp.$eval('#exp-status-0', (el) => el.textContent === 'PAGO DE?'));
  await emp.click('[data-paid="0"][data-v="drawer"]');
  await emp.type('[data-exp="0"][data-f="description"]', 'Gelo');
  check('expense complete is green', await emp.$eval('#exp-0', (el) => el.className === 'row ok'));

  /* 5. Summary: total 2 x 2.50 + 4 = 9, card 3 -> cash 6; counted 5 + drawer 1 = 6 -> balanced. */
  await emp.click('.tab[data-tab="summary"]');
  check('summary shows the sales total', (await emp.$eval('#sumGrand', (el) => el.textContent)) === 'Kz9.00');
  await emp.type('[data-sum="card"]', '3');
  await emp.type('[data-sum="counted"]', '4');
  check('cash short shows FALTA', /FALTA/.test(await emp.$eval('#sumDifference', (el) => el.textContent)));
  await emp.$eval('[data-sum="counted"]', (el) => { el.value = ''; });
  await emp.type('[data-sum="counted"]', '5');
  const balanced = await emp.$eval('#sumDifference', (el) => el.textContent);
  check('balanced cash shows CERTO', /CERTO/.test(balanced) && /\+?Kz0\.00/.test(balanced), balanced);
  check('send is enabled with no problems', await emp.$eval('#sendBtn', (el) => !el.disabled));

  /* 6. Saved on the server, kept on the phone across a reload, and edits made offline sync later. */
  const token = await emp.evaluate(() => S.current);
  const saved = await until(() => sql(`select content->'card' from day_sheets where token='${token}'`) === '"3"');
  check('the sheet is saved to the server as you type', saved, sql(`select content from day_sheets where token='${token}'`));
  await emp.setOfflineMode(true);
  await emp.click('.tab[data-tab="expenses"]');
  await emp.$eval('[data-exp="0"][data-f="description"]', (el) => { el.value = ''; });
  await emp.type('[data-exp="0"][data-f="description"]', 'Gelo offline');
  await wait(1600);
  check('offline: dot shows not synced', await emp.$eval('#syncDot', (el) => /offline/.test(el.className)));
  check('offline edit not on the server yet', sql(`select content->'expenses'->0->>'description' from day_sheets where token='${token}'`) === 'Gelo');
  await emp.setOfflineMode(false);
  const synced = await until(() => sql(`select content->'expenses'->0->>'description' from day_sheets where token='${token}'`) === 'Gelo offline', 10000);
  check('back online: the offline edit reaches the server', synced);
  await emp.reload();
  await emp.waitForSelector('#appView:not(.hidden)');
  const listed = await emp.$$eval('#sheetList .sheet-card', (els) => els.map((e) => e.textContent));
  check('after a reload the sheet is still listed', listed.some((t) => t.indexOf(code) !== -1), listed);

  /* 7. Send for approval: locked for the employee. */
  await emp.evaluate((tk) => document.querySelector(`[data-open="${tk}"]`).click(), token);
  await emp.click('.tab[data-tab="summary"]');
  await emp.click('#sendBtn');
  await until(() => emp.$eval('#sheetBanner', (el) => /aprovação/.test(el.textContent)));
  check('after sending: banner says waiting for approval', /aprovação/.test(await emp.$eval('#sheetBanner', (el) => el.textContent)));
  check('after sending: sheet is read-only', await emp.$eval('#sheetView', (el) => el.className === 'readonly'));
  check('status is submitted on the server', sql(`select status from day_sheets where token='${token}'`) === 'submitted');

  /* 8. Admin (approver) sees it waiting in the POS, returns it with a note. */
  await signIn(adm);
  await adm.goto(BASE + '/pos.html');
  await adm.waitForSelector('#shiftStatus');
  await until(() => adm.$eval('#sheetPendingBadge', (el) => el.style.display !== 'none' && el.textContent !== ''));
  check('menu shows the waiting count', parseInt(await adm.$eval('#sheetPendingBadge', (el) => el.textContent), 10) >= 1);
  await adm.evaluate(() => showScreen('daysheet'));
  await until(() => adm.$eval('#sheetApprovalList', (el) => el.textContent.indexOf('Ana Folha') !== -1));
  check('Day Sheet screen lists it under Waiting for approval',
    await adm.$eval('#sheetApprovalList', (el, c) => el.textContent.indexOf(c) !== -1, code));
  const sheetId = Number(sql(`select id from day_sheets where token='${token}'`));
  await adm.evaluate((id) => openSheetReview(id), sheetId);
  await adm.waitForSelector('#sheetReturnBtn');
  check('review shows the cash difference', /BALANCED/.test(await adm.$eval('#sheetReviewBody', (el) => el.textContent)));
  admDialogs.answer = 'A água era 2 garrafas';
  await adm.click('#sheetReturnBtn');
  await until(() => sql(`select status from day_sheets where id=${sheetId}`) === 'returned');
  check('returned with the note', sql(`select return_note from day_sheets where id=${sheetId}`) === 'A água era 2 garrafas');

  /* 9. Employee sees the note, fixes, sends again. */
  await emp.reload();
  await emp.waitForSelector('#appView:not(.hidden)');
  await until(() => emp.$eval('#sheetList', (el) => /DEVOLVIDA/.test(el.textContent)));
  await emp.evaluate((tk) => document.querySelector(`[data-open="${tk}"]`).click(), token);
  check('employee sees the manager\'s note', /2 garrafas/.test(await emp.$eval('#sheetBanner', (el) => el.textContent)));
  await emp.$eval('[data-line="1"][data-f="qty"]', (el) => { el.value = ''; });
  await emp.type('[data-line="1"][data-f="qty"]', '2');
  await emp.click('.tab[data-tab="summary"]');
  await emp.$eval('[data-sum="counted"]', (el) => { el.value = ''; });
  await emp.type('[data-sum="counted"]', '9');
  await emp.click('#sendBtn');
  await until(() => sql(`select status from day_sheets where id=${sheetId}`) === 'submitted');
  check('sent again after the fix', sql(`select status from day_sheets where id=${sheetId}`) === 'submitted');

  /* 10. Admin approves: one receipt in the admin's shift, stock deducted, expense recorded. */
  const before = { f: Number(sql(`select stock_qty from products where id=${famoso.id}`)), a: Number(sql(`select stock_qty from products where id=${agua.id}`)) };
  await adm.evaluate((id) => openSheetReview(id), sheetId);
  await adm.waitForSelector('#sheetApproveBtn');
  await adm.click('#sheetApproveBtn');
  await until(() => sql(`select status from day_sheets where id=${sheetId}`) === 'approved');
  const ref = sql(`select t.ref_number from day_sheets d join transactions t on t.id=d.transaction_id where d.id=${sheetId}`);
  check('approved: receipt issued', /^TXN-/.test(ref), ref);
  check('approved: stock deducted', Number(sql(`select stock_qty from products where id=${famoso.id}`)) === before.f - 2 &&
    Number(sql(`select stock_qty from products where id=${agua.id}`)) === before.a - 2);
  check('approved: receipt in the admin\'s open shift',
    sql(`select t.shift_id = s.id from day_sheets d join transactions t on t.id=d.transaction_id join shifts s on s.status='open' and s.cashier_id=1 where d.id=${sheetId}`) === 't');
  check('approved: expense recorded from the sheet', sql(`select count(*) from expenses where day_sheet_id=${sheetId}`) === '1');
  check('audit trail: sent twice, returned once, approved once',
    sql(`select string_agg(action, ',' order by id) from audit_log where ref='${code}'`) === 'day_sheet_submitted,day_sheet_returned,day_sheet_submitted,day_sheet_approved',
    sql(`select string_agg(action, ',' order by id) from audit_log where ref='${code}'`));

  /* 11. Employee sees it approved with the receipt; language switch works. */
  await emp.reload();
  await emp.waitForSelector('#appView:not(.hidden)');
  await until(() => emp.$eval('#sheetList', (el) => /APROVADA/.test(el.textContent)));
  check('employee sees APROVADA with the receipt number', await emp.$eval('#sheetList', (el, r) => el.textContent.indexOf(r) !== -1, ref));
  await emp.evaluate((tk) => document.querySelector(`[data-open="${tk}"]`).click(), token);
  await emp.click('.tab[data-tab="sales"]');
  const approvedRows = await emp.$$eval('#lines .row', (els) => els.map((e) => e.className + ' ' + e.textContent));
  check('approved sheet: its own (already deducted) sales are not shown as SEM STOCK',
    approvedRows.length === 2 && approvedRows.every((r) => /^row ok /.test(r)), approvedRows);
  await emp.evaluate(() => showHome());
  await emp.click('#menuBtn');
  await emp.click('#menu .lang-btn[data-lang="en"]');
  check('language switch to English', /NEW SHEET/.test(await emp.$eval('#newSheetBtn', (el) => el.textContent)));

  /* 12. The POS Users form offers the role and the approve permission. */
  await adm.evaluate(() => { closePanel('sheetReviewPanel'); showScreen('users'); });
  check('Users form has the Day Sheet role', await adm.$eval('#editUserRole', (el) => [].some.call(el.options, (o) => o.value === 'sheet')));
  check('Users form has the approve permission', !!(await adm.$('#permApproveSheets')));

  check('no script errors', errors.length === 0, errors);
  await browser.close();
  await send('PUT', '/settings', settingsBefore);
}

run().catch((e) => {
  console.error(e);
  results.push({ name: 'crashed', ok: false });
}).then(() => {
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
});
