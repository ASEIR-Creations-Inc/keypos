/* Opens every screen and runs every report, failing on any script error or on a
 * report that renders an error. Catches wiring mistakes the flow tests don't reach.
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-tour.js
 */
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const SCREENS = ['pos', 'inventory', 'purchases', 'reports', 'customers', 'expenses', 'daysheet', 'users', 'importexport', 'settings'];
const REPORTS = ['sales', 'shifts', 'pnl', 'purchases', 'inventory', 'lowstock', 'priceedits', 'cashier', 'tax', 'stockadj'];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + detail : ''));
};

async function run() {
  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await (await browser.createBrowserContext()).newPage();
  const errors = [];
  const alerts = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => { alerts.push(d.message()); d.accept(); });
  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('app loads without script errors', errors.length === 0, errors.join(' | '));

  for (const name of SCREENS) {
    const before = errors.length;
    await page.evaluate((n) => showScreen(n), name);
    await wait(900);
    const visible = await page.evaluate((n) => document.getElementById('screen-' + n).classList.contains('active'), name);
    check(`screen ${name} opens cleanly`, visible && errors.length === before, errors.slice(before).join(' | '));
  }

  await page.evaluate(() => { showScreen('reports'); loadReports(); });
  for (const key of REPORTS) {
    const before = errors.length;
    const alertsBefore = alerts.length;
    await page.evaluate((k) => { openReport(k, k); runActiveReport(); }, key);
    await wait(1200);
    const html = await page.$eval('#reportDetailContent', (el) => el.innerText);
    const failed = /\b(Error|error|Failed|failed)\b|\bundefined\b|\bNaN\b/.test(html) || alerts.length > alertsBefore;
    check(`report ${key} renders`, !failed && errors.length === before && html.indexOf('Loading') === -1,
      (errors.slice(before).join(' | ') || html.slice(0, 160)) + ' ' + alerts.slice(alertsBefore).join(' | '));
  }

  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

run().catch((e) => { console.error(e); process.exit(1); });
