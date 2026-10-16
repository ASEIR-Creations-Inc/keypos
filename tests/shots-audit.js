/* Phone-size screenshots of every screen and the main panels, for a visual review.
 *   CHROME=... BASE=http://127.0.0.1:8095 node shots-audit.js [outdir] [width] [height]
 */
const fs = require('fs');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch, signIn } = require('./auth');

const BASE = process.env.BASE || 'http://127.0.0.1:8095';
const OUT = process.argv[2] || '/tmp/audit';
const W = Number(process.argv[3] || 360);
const H = Number(process.argv[4] || 740);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function run() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await (await browser.createBrowserContext()).newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept(d.type() === 'prompt' ? '100' : undefined));
  let n = 0;
  const shot = async (name) => {
    n += 1;
    await page.screenshot({ path: `${OUT}/${String(n).padStart(2, '0')}-${name}.png` });
  };
  const closePanels = () => page.evaluate(() => {
    document.querySelectorAll('.panel.open, .slide-panel.open, .modal.open, .modal.show').forEach((p) => p.classList.remove('open', 'show'));
  });

  /* A posted purchase and a sale, so lists and detail panels have something to show. */
  const api = async (method, path, body) => {
    const r = await authFetch(BASE + '/api' + path, {
      method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status >= 400) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
    return r.json();
  };
  const products = (await api('GET', '/products?is_active=true')).slice(0, 2);
  if (!(await api('GET', '/shifts/current'))) await api('POST', '/shifts/open', { opening_float: 5000 });
  const po = await api('POST', '/purchases', { lines: products.map((p) => ({ product_id: p.id, qty: '12', unit_cost: '1250.50' })) });
  await api('POST', `/purchases/${po.id}/post`);
  const sale = await api('POST', '/transactions', {
    lines: products.map((p) => ({ product_id: p.id, qty: '2', sell_price: '1500' })), payment_cash: '6000',
  });

  await page.goto(BASE + '/index.html');
  await wait(800);
  await shot('login');
  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  await shot('register');

  await page.evaluate(() => { const b = openDrawer(); });
  await wait(500);
  await shot('menu');
  await page.evaluate(() => { closeDrawer(); });

  for (const name of ['inventory', 'purchases', 'reports', 'customers', 'expenses', 'daysheet', 'users', 'importexport', 'settings']) {
    await page.evaluate((s) => showScreen(s), name);
    await wait(1000);
    await shot('screen-' + name);
  }

  const panels = ['productPanel', 'purchaseFormPanel', 'customerPanel', 'expenseFormPanel', 'userFormPanel', 'salesPanel', 'ticketsPanel', 'passwordPanel', 'cartPanel'];
  for (const id of panels) {
    await page.evaluate((p) => { try { openPanel(p); } catch (e) { /* not all are panels */ } }, id);
    await wait(700);
    await shot('panel-' + id);
    await page.evaluate((p) => { try { closePanel(p); } catch (e) { /* ignore */ } }, id);
    await closePanels();
    await wait(300);
  }

  await page.evaluate(() => showScreen('reports'));
  await wait(600);
  for (const key of ['sales', 'shifts', 'pnl', 'lowstock']) {
    await page.evaluate((k) => { openReport(k, k); runActiveReport(); }, key);
    await wait(1300);
    await shot('report-' + key);
    await closePanels();
  }

  await page.evaluate(() => { closeTopPanel(); document.getElementById('salesHistoryBtn').click(); });
  await wait(1200);
  await shot('recent-sales');
  await page.evaluate((id) => showSaleDetail(id), sale.id);
  await wait(1200);
  await shot('sale-detail');
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); });
  const shiftNow = await api('GET', '/shifts/current');
  await page.evaluate((id) => openShiftZ(id), shiftNow.id);
  await wait(1500);
  await shot('z-report-open-shift');
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); showScreen('inventory'); });
  await wait(1200);
  await page.evaluate(() => document.querySelector('#inventoryTableBody tr').click());
  await wait(1000);
  await shot('product-edit-from-row');
  await page.evaluate(() => { while (APP.panelStack.length) closeTopPanel(); showScreen('purchases'); });
  await wait(1200);
  await shot('purchases-list');

  fs.writeFileSync(`${OUT}/errors.txt`, errors.join('\n'));
  console.log(`${n} shots in ${OUT}; script errors: ${errors.length}`);
  await browser.close();
}

run().catch((e) => { console.error(e); process.exit(1); });
