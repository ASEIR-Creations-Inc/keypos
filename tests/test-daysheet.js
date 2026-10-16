/* Day Sheet UI test: download a sheet, fill it as a phone would, refresh it, have the old
 * version refused, see a stock problem block the upload, then issue the receipt.
 * Also checks the CSV export buttons send the login (they failed with 401 before).
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-daysheet.js
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, execSync } = require('child_process');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const PYTHON = '/pos/backend/venv/bin/python';
const FILL = path.join(__dirname, '..', 'backend', 'tests', 'sheetfill.py');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const sql = (q) => execSync(`sudo -u postgres psql -d pos_test -tAc "${q}"`).toString().trim();
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !ok ? '  -> ' + detail : ''));
};

async function api(p, options) {
  const r = await authFetch(BASE + '/api' + p, options);
  return r.status === 204 ? null : r.json();
}
const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function fill(source, target, spec) {
  execFileSync(PYTHON, [FILL, source, target, JSON.stringify(spec)], { cwd: path.dirname(path.dirname(FILL)) });
}

async function downloaded(dir, pattern, timeout) {
  const until = Date.now() + (timeout || 8000);
  while (Date.now() < until) {
    const hit = fs.readdirSync(dir).find((f) => pattern.test(f) && !f.endsWith('.crdownload'));
    if (hit) return path.join(dir, hit);
    await wait(200);
  }
  return null;
}

async function run() {
  const rows = sql("select id, name from products where is_active order by id limit 2").split('\n').map((l) => l.split('|'));
  const [A, nameA] = [Number(rows[0][0]), rows[0][1]];
  const [B, nameB] = [Number(rows[1][0]), rows[1][1]];
  sql(`update products set stock_qty=10 where id in (${A}, ${B})`);
  await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_name: 'KEYPOS', currency_symbol: '$', tax_rate: 0, low_stock_threshold: 5 }) });
  const open = await api('/shifts?status=open&limit=1');
  if (open.length) await post('/shifts/close', { closing_cash: 0 });
  await post('/shifts/open', { opening_float: 0 });
  const category = (await api('/expenses/categories'))[0];

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'daysheet-'));
  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await browser.newPage();
  const cdp = await page.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dir });
  const errors = [];
  const alerts = [];
  const confirms = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => {
    if (d.type() === 'alert') alerts.push(d.message());
    if (d.type() === 'confirm') confirms.push(d.message());
    return d.accept();
  });
  const click = (sel) => page.$eval(sel, (el) => el.click());
  const text = (sel) => page.$eval(sel, (el) => el.textContent);
  const lastAlert = () => alerts[alerts.length - 1] || '';
  const stock = (id) => parseFloat(sql(`select stock_qty from products where id=${id}`));
  const pick = async (file) => {
    const input = await page.$('#daySheetFile');
    await input.uploadFile(file);
    await page.$eval('#daySheetFile', (el) => el.dispatchEvent(new Event('change')));
  };

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));
  const menu = await page.$$eval('[data-screen="daysheet"]', (els) => els.map((e) => e.parentNode.style.display));
  check('Day Sheet is in the menu', menu.length === 1 && menu[0] !== 'none', JSON.stringify(menu));

  /* 1. Download today's sheet (Portuguese) */
  await page.evaluate(() => showScreen('daysheet'));
  await wait(800);
  check('header reads DAY SHEET', (await text('#headerTitle')) === 'DAY SHEET');
  await page.select('#daySheetLang', 'pt');
  await click('#daySheetNewBtn');
  const v1 = await downloaded(dir, /^DaySheet-\d{4}-[A-Z0-9]{4}-v1\.xlsx$/);
  check('sheet downloads as DaySheet-MMDD-XXXX-v1.xlsx', !!v1, fs.readdirSync(dir).join(','));
  const code = (lastAlert().match(/DS-\d{4}-[A-Z0-9]{4}/) || [])[0];
  check('download message shows the sheet code', !!code, lastAlert());
  await wait(600);
  check('new sheet listed as OPEN', (await text('#daySheetList')).indexOf(code + ' OPEN') > -1, await text('#daySheetList'));

  /* 2. Fill rows, then Refresh: same rows come back as version 2 */
  const filled1 = path.join(dir, 'filled-v1.xlsx');
  fill(v1, filled1, { sales: [[2, nameA, 3, 2.5], [3, nameB, 12, 1]], expenses: [[2, category.name, 4, 'Gelo', 'Caixa']] });
  await pick(filled1);
  await click('#daySheetRefreshBtn');
  const v2 = await downloaded(dir, /-v2\.xlsx$/);
  check('refresh asks to confirm the sheet code and version',
    confirms.some((c) => c.indexOf('Refresh sheet ' + code) === 0 && c.indexOf('Version 1 · 2 sales rows · 1 expense rows') > -1), confirms.join(' || '));
  check('refresh downloads version 2', !!v2);

  /* 3. The old version is refused */
  await pick(filled1);
  await click('#daySheetCheckBtn');
  await wait(1500);
  let preview = await text('#daySheetPreview');
  check('version 1 is refused after the refresh', preview.indexOf('This is version 1 of ' + code + ', but version 2 exists') > -1, preview);
  check('no ISSUE RECEIPT button for a refused sheet', !(await page.$('#daySheetIssueBtn')));

  /* 4. Version 2 keeps the rows; 12 of B is more than the 10 in stock */
  const filled2 = path.join(dir, 'filled-v2.xlsx');
  fill(v2, filled2, { card: 5, counted: 20 });
  await pick(filled2);
  await click('#daySheetCheckBtn');
  await wait(1500);
  preview = await text('#daySheetPreview');
  check('stock shortfall shown with the line number', preview.indexOf('Sales line 2:') > -1 && preview.indexOf('the sheet sells 12, stock is 10') > -1, preview);
  check('rows typed in version 1 survived the refresh', preview.indexOf('2 sales rows · 1 expense rows') > -1, preview);
  check('blocked sheet has no ISSUE RECEIPT button', !(await page.$('#daySheetIssueBtn')));

  /* 5. Fix the quantity and issue the receipt */
  const fixed = path.join(dir, 'fixed-v2.xlsx');
  fill(filled2, fixed, { sales: [[3, nameB, 2, 1]] });
  await pick(fixed);
  await click('#daySheetCheckBtn');
  await wait(1500);
  preview = await text('#daySheetPreview');
  check('preview shows the cash check', preview.indexOf('= Cash sales$4.50') > -1 && preview.indexOf('Difference +$19.50 · EXTRA CASH') > -1, preview);
  const txnsBefore = Number(sql('select count(*) from transactions'));
  await click('#daySheetIssueBtn');
  await wait(2000);
  check('upload confirms with the receipt number', /uploaded\.\n\nReceipt TXN-/.test(lastAlert()), lastAlert());
  check('one receipt was created', Number(sql('select count(*) from transactions')) === txnsBefore + 1);
  check('stock deducted', stock(A) === 7 && stock(B) === 8, stock(A) + ' / ' + stock(B));
  check('sheet expense recorded and linked', sql(`select count(*) from expenses where description='Gelo' and day_sheet_id is not null and paid_from_drawer`) === '1');
  await wait(600);
  check('sheet listed as UPLOADED with its difference', (await text('#daySheetList')).indexOf(code + ' UPLOADED') > -1 && (await text('#daySheetList')).indexOf('difference +$19.50') > -1, await text('#daySheetList'));

  /* 6. The same file can't be uploaded twice */
  await pick(fixed);
  await click('#daySheetCheckBtn');
  await wait(1500);
  check('second upload refused', (await text('#daySheetPreview')).indexOf('was already uploaded') > -1, await text('#daySheetPreview'));

  /* 7. CSV export now carries the login */
  await page.evaluate(() => showScreen('importexport'));
  await wait(500);
  await click('#exportProductsBtn');
  const csv = await downloaded(dir, /^products\.csv$/);
  check('Export Products downloads a CSV', !!csv && fs.readFileSync(csv, 'utf8').indexOf(nameA) > -1);

  check('no script errors during the run', errors.length === 0, errors.join(' | '));
  await browser.close();
  fs.rmSync(dir, { recursive: true, force: true });
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
}

run().catch((e) => { console.error(e); process.exit(1); });
