/* Two apps, one browser: the till (pos.html) and the Sheet app (/sheet/) share an origin but
 * keep separate logins, so an admin can have KEYPOS open while the Sheet app is signed in as
 * an employee, and signing out of one leaves the other alone.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-sessions.js
 */
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + JSON.stringify(detail) : ''));
};

async function until(fn, timeout) {
  const end = Date.now() + (timeout || 8000);
  while (Date.now() < end) {
    try {
      if (await fn()) return true;
    } catch (e) { /* page mid-navigation */ }
    await wait(150);
  }
  return false;
}

const storage = (page) => page.evaluate(() => ({
  pos: JSON.parse(localStorage.getItem('pos_user') || '{}').username,
  sheet: JSON.parse(localStorage.getItem('sheet_user') || '{}').username,
}));
const sheetSignedIn = (page) => page.$eval('#appView', (el) => !el.classList.contains('hidden'));
const posOpen = (page) => page.url().indexOf('/pos.html') !== -1;

async function signInSheetUser(page, username) {
  await page.goto(BASE + '/sheet/');
  await page.waitForSelector('#loginView:not(.hidden)');
  await page.type('#loginUser', username);
  await page.type('#loginPass', 'sheet-pass-1');
  await page.click('#loginBtn');
  await until(() => sheetSignedIn(page));
}

async function run() {
  const tag = Date.now().toString(36);
  const username = `sess_${tag}`;
  const r = await authFetch(BASE + '/api/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'Sessao Teste', username, password: 'sheet-pass-1', role: 'sheet' }),
  });
  check('test Day Sheet user created', r.status === 200 || r.status === 201, r.status);

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const errors = [];
  const context = await browser.createBrowserContext();
  const pos = await context.newPage();
  const sheet = await context.newPage();
  [pos, sheet].forEach((p) => {
    p.on('pageerror', (e) => errors.push(e.message));
    p.on('dialog', (d) => d.accept());
  });

  /* 1. The reported case: admin in KEYPOS, then the employee signs into the Sheet app in the same browser. */
  await signIn(pos);
  await pos.goto(BASE + '/pos.html');
  check('admin opens KEYPOS', await until(async () => posOpen(pos)), pos.url());
  await signInSheetUser(sheet, username);
  check('employee lands in the Sheet app', await sheetSignedIn(sheet), sheet.url());
  await pos.reload();
  await wait(1500);
  check('KEYPOS stays open after the Sheet app signs in', posOpen(pos), pos.url());
  check('KEYPOS is still signed in as admin', (await storage(pos)).pos === 'admin', await storage(pos));
  check('Sheet app is signed in as the employee', (await storage(sheet)).sheet === username, await storage(sheet));
  await sheet.reload();
  check('Sheet app stays signed in after reload', await until(() => sheetSignedIn(sheet)));
  check('Sheet app menu names the employee', (await sheet.$eval('#menuUser', (el) => el.textContent)) === 'Sessao Teste');

  /* 2. Signing out of one app leaves the other signed in. */
  await sheet.$eval('#logoutBtn', (el) => el.click());
  await until(() => sheet.$eval('#loginView', (el) => !el.classList.contains('hidden')));
  check('Sheet app sign-out shows its sign-in', await sheet.$eval('#loginView', (el) => !el.classList.contains('hidden')));
  await pos.reload();
  await wait(1500);
  check('KEYPOS still signed in after the Sheet app signs out', posOpen(pos) && (await storage(pos)).pos === 'admin', pos.url());
  await signInSheetUser(sheet, username);
  await pos.evaluate(() => signOut());
  await until(() => pos.url().indexOf('/index.html') !== -1);
  check('KEYPOS sign-out shows its sign-in page', pos.url().indexOf('/index.html') !== -1, pos.url());
  await sheet.reload();
  check('Sheet app still signed in after KEYPOS signs out', await until(() => sheetSignedIn(sheet)));

  /* 3. An admin signed into KEYPOS is not signed into the Sheet app as admin automatically. */
  await sheet.$eval('#logoutBtn', (el) => el.click());
  await signIn(pos);
  await sheet.goto(BASE + '/sheet/');
  await wait(800);
  check('Sheet app asks for its own sign-in, not the admin login',
    await sheet.$eval('#loginView', (el) => !el.classList.contains('hidden')) && !(await storage(sheet)).sheet);

  /* 4. A phone signed in before this change (Day Sheet login under the till's keys) keeps its session. */
  await pos.evaluate(() => { localStorage.removeItem('pos_token'); localStorage.removeItem('pos_user'); });
  const login = await (await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: 'sheet-pass-1' }),
  })).json();
  await pos.goto(BASE + '/index.html');
  await pos.evaluate((d) => {
    localStorage.setItem('pos_token', d.access_token);
    localStorage.setItem('pos_user', JSON.stringify(Object.assign({}, d, { access_token: undefined })));
  }, login);
  await sheet.goto(BASE + '/sheet/');
  check('old Day Sheet login moves to the Sheet app', await until(() => sheetSignedIn(sheet)));
  check('and is removed from the till\'s keys', !(await storage(sheet)).pos && (await storage(sheet)).sheet === username, await storage(sheet));

  check('no script errors', errors.length === 0, errors);
  await browser.close();
  const passed = results.filter((x) => x.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
