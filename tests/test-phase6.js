/* Phase 6 UI test: signing in and out, what a cashier's screen hides, changing a
 * password, and an offline sale staying credited to the cashier who rang it up even
 * when someone else's login syncs it.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-phase6.js
 */
const { execSync } = require('child_process');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, login } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const sql = (q) => execSync(`sudo -u postgres psql -d pos_test -tAc "${q}"`).toString().trim();
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + detail : ''));
};

async function api(path, options, token) {
  const opts = Object.assign({}, options);
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers);
  if (token) opts.headers.Authorization = 'Bearer ' + token;
  const r = token ? await fetch(BASE + '/api' + path, opts) : await authFetch(BASE + '/api' + path, opts);
  return { status: r.status, body: r.status === 204 ? null : await r.json() };
}

async function loginAs(username, password) {
  const r = await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return r.status === 200 ? r.json() : null;
}

async function run() {
  const A = Number(sql('select id from products where is_active order by id limit 1'));
  sql(`update products set stock_qty=10, sell_price=10 where id=${A}`);
  await api('/settings', { method: 'PUT', body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 0, low_stock_threshold: 5 }) });

  const username = 'p6cash' + Date.now();
  const created = await api('/users', { method: 'POST', body: JSON.stringify({ name: 'Phase Six Cashier', username, password: 'first-pass-1', role: 'cashier' }) });
  check('admin creates a cashier', created.status === 201, JSON.stringify(created.body));
  const cashierId = created.body.id;

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await (await browser.createBrowserContext()).newPage();
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
  const visible = (sel) => page.$eval(sel, (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const menuShown = (screen) => page.$eval(`.nav-link[data-screen="${screen}"]`, (el) => el.parentNode.style.display !== 'none');
  const lastAlert = () => alerts[alerts.length - 1] || '';
  const signInForm = async (user, pass) => {
    await page.$eval('#username', (el) => { el.value = ''; });
    await page.$eval('#password', (el) => { el.value = ''; });
    await page.type('#username', user);
    await page.type('#password', pass);
    await click('#loginBtn');
    await wait(1500);
  };

  /* 1. No login: the app sends you to the sign-in page */
  await page.goto(BASE + '/pos.html');
  await wait(1500);
  check('pos.html without a login redirects to sign-in', page.url().endsWith('/index.html'), page.url());
  const anon = await fetch(BASE + '/api/products');
  check('API refuses requests without a login', anon.status === 401, String(anon.status));

  /* 2. Wrong password is refused with a message */
  await signInForm(username, 'wrong-password');
  check('wrong password stays on sign-in', page.url().endsWith('/index.html'), page.url());
  check('wrong password shows an error', (await text('#errorMessage')).indexOf('Invalid username or password') > -1, await text('#errorMessage'));
  check('sign-in button usable again', !(await page.$eval('#loginBtn', (el) => el.disabled)));

  /* 3. Cashier signs in: open a shift, restricted menu and controls */
  const cashierSession = await loginAs(username, 'first-pass-1');
  const shift = await api('/shifts/open', { method: 'POST', body: JSON.stringify({ opening_float: 10 }) }, cashierSession.access_token);
  check('cashier opens their own shift', shift.status === 201 || shift.status === 200, JSON.stringify(shift.body));

  await signInForm(username, 'first-pass-1');
  await wait(1500);
  check('right password opens the till', page.url().endsWith('/pos.html'), page.url());
  check('no script errors after sign-in', errors.length === 0, errors.join(' | '));
  check('drawer shows the signed-in name', (await text('#cashierName')) === 'Phase Six Cashier', await text('#cashierName'));
  check('cashier sees Register and Inventory', (await menuShown('pos')) && (await menuShown('inventory')));
  const hidden = [];
  for (const s of ['users', 'settings', 'importexport', 'purchases']) if (await menuShown(s)) hidden.push(s);
  check('cashier menu hides Users, Settings, Import/Export, Purchases', hidden.length === 0, 'shown: ' + hidden.join(','));
  check('cashier can use Reports (own) and Expenses (own)', (await menuShown('reports')) && (await menuShown('expenses')));
  check('DISC button hidden for a cashier', !(await visible('#discBtn')));
  check('body marks refund as not allowed', await page.evaluate(() => document.body.classList.contains('no-refund')));

  const refused = await api('/users', { method: 'GET' }, cashierSession.access_token);
  check('server refuses the Users API to a cashier', refused.status === 403, String(refused.status));
  const discounted = await api('/transactions', { method: 'POST', body: JSON.stringify({
    lines: [{ product_id: A, qty: 1, sell_price: 10, discount: 5 }], payment_cash: 5, payment_card: 0, payment_account: 0,
  }) }, cashierSession.access_token);
  check('server refuses a discount from a cashier', discounted.status === 403, discounted.status + ' ' + JSON.stringify(discounted.body));

  /* 4. Change own password */
  alerts.length = 0;
  await page.evaluate(() => openPasswordPanel());
  await page.type('#pwCurrent', 'first-pass-1');
  await page.type('#pwNew', 'second-pass-2');
  await page.type('#pwRepeat', 'second-pass-2');
  await click('#savePasswordBtn');
  await wait(1200);
  check('password change confirmed', lastAlert() === 'Password changed.', lastAlert());
  check('old password no longer works', (await loginAs(username, 'first-pass-1')) === null);
  const second = await loginAs(username, 'second-pass-2');
  check('new password works', !!second);

  /* 5. Offline sale by the cashier, synced later under the admin's login on the same device */
  await page.setOfflineMode(true);
  await wait(800);
  alerts.length = 0;
  await page.evaluate(() => posResetCart());
  await page.evaluate((id) => { posAddToCart(id); posAddToCart(id); }, A);
  await click('#chargeBtn');
  await wait(300);
  await click('#payCashBtn');
  await page.$eval('#cashTenderedInput', (el) => { el.value = '20'; });
  await click('#confirmCashBtn');
  await wait(1200);
  check('cashier sale queued offline', lastAlert().indexOf('OFFLINE SALE') === 0, lastAlert().split('\n')[0]);
  const queued = await page.evaluate(() => new Promise((resolve) => DB.getPendingSync((e, items) => resolve(items || []))));
  const claims = queued.length && queued[0].auth_token
    ? JSON.parse(Buffer.from(queued[0].auth_token.split('.')[1], 'base64url').toString()) : {};
  check('queued sale carries the cashier login', queued.length === 1 && String(claims.sub) === String(cashierId), JSON.stringify(claims));

  const admin = await login();
  await page.evaluate((d) => saveSession(d), admin);
  await page.setOfflineMode(false);
  await page.evaluate(() => new Promise((resolve) => SYNC.syncNow(() => resolve())));
  await wait(800);
  const credited = sql(`select cashier_id || ':' || coalesce(shift_id::text,'') from transactions where is_offline and cashier_id in (${cashierId}, 1) order by id desc limit 1`);
  check('offline sale credited to the cashier and their shift', credited === `${cashierId}:${shift.body.id}`, credited);

  /* 6. Logout leaves the till's queue and device id, removes only the login */
  await page.evaluate((d) => saveSession(d), second);
  await page.goto(BASE + '/pos.html');
  await wait(2000);
  const deviceBefore = await page.evaluate(() => DB.getDeviceId());
  await page.evaluate(() => document.getElementById('logoutBtn').click());
  await wait(1200);
  check('logout returns to sign-in', page.url().endsWith('/index.html'), page.url());
  const after = await page.evaluate(() => ({ token: localStorage.getItem('pos_token'), user: localStorage.getItem('pos_user') }));
  check('logout removes the login from the device', !after.token && !after.user);
  await page.goto(BASE + '/pos.html');
  await wait(1500);
  check('till stays locked after logout', page.url().endsWith('/index.html'), page.url());
  await page.evaluate((d) => saveSession(d), second);
  await page.goto(BASE + '/pos.html');
  await wait(2000);
  check('device id survives logout', (await page.evaluate(() => DB.getDeviceId())) === deviceBefore);

  /* 7. Deactivated user is signed out on the next request */
  await api(`/users/${cashierId}`, { method: 'DELETE' });
  await page.evaluate(() => apiGet('/products').catch(() => null));
  await wait(1200);
  check('deactivated user is sent to sign-in', page.url().endsWith('/index.html'), page.url());
  check('no script errors overall', errors.length === 0, errors.join(' | '));

  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
