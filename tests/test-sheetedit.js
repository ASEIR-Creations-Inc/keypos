/* KEYPOS Sheet app: editing lines already entered. Tap a line's product name to change the
 * product (qty kept; typed price kept, an empty price takes the new product's fixed price),
 * and tap ＋ on a line to insert a new line right after it (the lines below move down one).
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-sheetedit.js
 */
const { execSync } = require('child_process');
const puppeteer = require('/pos/tests/node_modules/puppeteer');
const { authFetch } = require('./auth');

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

async function run() {
  const tag = Date.now().toString(36).toUpperCase();
  const low = tag.toLowerCase();
  const alfa = await send('POST', '/products', { name: `ZZ${tag} ALFA`, sell_price: '0', stock_qty: '50' });
  const beta = await send('POST', '/products', { name: `ZZ${tag} BETA`, sell_price: '0', stock_qty: '50' });
  const gama = await send('POST', '/products', { name: `ZZ${tag} GAMA`, sell_price: '5', stock_qty: '50' });
  const delta = await send('POST', '/products', { name: `ZZ${tag} DELTA`, sell_price: '7', stock_qty: '50' });
  for (const p of [alfa, beta, gama, delta]) sql(`update products set stock_qty=50 where id=${p.id}`);
  const username = `edit_${low}`;
  await send('POST', '/users', { name: 'Edu Folha', username, password: 'sheet-pass-1', role: 'sheet' });

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const errors = [];
  const page = await (await browser.createBrowserContext()).newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());
  await page.setViewport({ width: 360, height: 760 });

  await page.goto(BASE + '/sheet/');
  await page.type('#loginUser', username);
  await page.type('#loginPass', 'sheet-pass-1');
  await page.click('#loginBtn');
  await page.waitForSelector('#appView:not(.hidden)');
  await page.click('#newSheetBtn');
  await until(() => page.$eval('#barTitle', (el) => /^DS-/.test(el.textContent)));
  const token = await page.evaluate(() => S.current);

  const pick = async (word) => {
    await page.$eval('#productSearch', (el) => { el.value = ''; });
    await page.type('#productSearch', `zz${low} ${word}`);
    await page.waitForSelector('#searchResults .result');
    await page.click('#searchResults .result');
  };
  const lines = () => page.evaluate(() => current().content.lines.map((l) => [l.product, l.qty, l.price]));
  const short = (rows) => rows.map((r) => r[0].split(' ').pop() + ' ' + r[1] + ' ' + r[2]);
  const setField = async (i, f, v) => {
    await page.$eval(`[data-line="${i}"][data-f="${f}"]`, (el) => { el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });
    if (v) await page.type(`[data-line="${i}"][data-f="${f}"]`, v);
  };

  /* Three lines: ALFA 1 × 10, BETA 2 × 20, ALFA 3 × 30. */
  await pick('alfa'); await setField(0, 'price', '10');
  await pick('beta'); await setField(1, 'qty', '2'); await setField(1, 'price', '20');
  await pick('alfa'); await setField(2, 'qty', '3'); await setField(2, 'price', '30');
  check('three lines entered', short(await lines()).join('|') === 'ALFA 1 10|BETA 2 20|ALFA 3 30', short(await lines()));

  /* 1. Insert after line 1: the new line becomes #2 and the old #2, #3 move to #3, #4. */
  check('each editable line has an insert button', (await page.$$('[data-ins-line]')).length === 3);
  await page.click('[data-ins-line="0"]');
  check('insert shows which line it goes after', await page.$eval('#pickHint', (el) => !el.classList.contains('hidden') && /linha 1\b/i.test(el.textContent)));
  check('insert puts the cursor in the search box', await page.evaluate(() => document.activeElement && document.activeElement.id === 'productSearch'));
  await pick('gama');
  let now = short(await lines());
  check('inserted line lands at #2 with its fixed price, the rest move down', now.join('|') === 'ALFA 1 10|GAMA 1 5|BETA 2 20|ALFA 3 30', now);
  check('insert hint goes away after picking', await page.$eval('#pickHint', (el) => el.classList.contains('hidden')));
  check('line numbers on screen follow the new order',
    await page.$eval('#line-1', (el) => el.querySelector('.row-num').textContent === '#2' && /GAMA/.test(el.querySelector('.row-name').textContent)) &&
    await page.$eval('#line-3', (el) => el.querySelector('.row-num').textContent === '#4' && /ALFA/.test(el.querySelector('.row-name').textContent)));
  await setField(3, 'price', '');
  check('problem messages use the new numbers', await page.$eval('#problemList', (el) => /Linha 4: SEM PREÇO/.test(el.textContent)), await page.$eval('#problemList', (el) => el.textContent));
  await setField(3, 'price', '30');

  /* Insert after the last line works too, and a plain search still adds at the end. */
  await page.click('[data-ins-line="3"]');
  await pick('delta');
  now = short(await lines());
  check('insert after the last line adds #5', now[4] === 'DELTA 1 7', now);

  /* 2. Cancel: nothing is added, and the next pick adds at the end as normal. */
  await page.click('[data-ins-line="0"]');
  await page.click('#pickCancel');
  check('cancel hides the insert hint', await page.$eval('#pickHint', (el) => el.classList.contains('hidden')));
  await pick('beta');
  now = short(await lines());
  check('after cancel, a pick adds at the end', now.length === 6 && now[5] === 'BETA 1 ', now);
  await page.click('[data-del-line="5"]');

  /* 3. Change a line's product: tap its name. Qty and a typed price stay. */
  await page.click('[data-change-line="2"]');
  check('change shows which line', await page.$eval('#pickHint', (el) => !el.classList.contains('hidden') && /linha 3\b/i.test(el.textContent)));
  await pick('delta');
  now = short(await lines());
  check('changed product keeps qty and the typed price', now[2] === 'DELTA 2 20' && now.length === 5, now);
  check('the line keeps its place', now.join('|') === 'ALFA 1 10|GAMA 1 5|DELTA 2 20|ALFA 3 30|DELTA 1 7', now);
  const ids = await page.evaluate(() => current().content.lines.map((l) => l.product_id));
  check('changed line points at the new product id', ids[2] === delta.id, ids);

  /* An empty price takes the new product's fixed price. */
  await setField(0, 'price', '');
  await page.click('[data-change-line="0"]');
  await pick('gama');
  now = short(await lines());
  check('empty price takes the new product\'s fixed price', now[0] === 'GAMA 1 5', now);

  /* Stock is checked on the new product: GAMA now sold 1 + 1, still within 50; push it over. */
  await setField(0, 'qty', '50');
  check('stock check follows the changed product (50 + 1 > 50 → both GAMA lines red)',
    await page.$eval('#line-0', (el) => el.className === 'row bad') && await page.$eval('#line-1', (el) => el.className === 'row bad'));
  await setField(0, 'qty', '1');

  /* 4. The server gets the lines in the new order. */
  const expected = [gama.id, gama.id, delta.id, alfa.id, delta.id].join(',');
  const saved = await until(() => sql(`select string_agg(l->>'product_id', ',' order by n) from day_sheets, jsonb_array_elements(content->'lines') with ordinality as x(l, n) where token='${token}'`) === expected, 10000);
  check('server has the lines in the new order', saved,
    sql(`select string_agg(l->>'product_id', ',' order by n) from day_sheets, jsonb_array_elements(content->'lines') with ordinality as x(l, n) where token='${token}'`));
  await page.reload();
  await page.waitForSelector('#appView:not(.hidden)');
  await page.evaluate((tk) => openSheet(tk), token);
  check('order survives a reload', short(await lines()).join('|') === 'GAMA 1 5|GAMA 1 5|DELTA 2 20|ALFA 3 30|DELTA 1 7', short(await lines()));

  /* 5. Once sent, the sheet is locked: no insert buttons, tapping a name does nothing. */
  await page.click('.tab[data-tab="summary"]');
  await page.type('[data-sum="card"]', '0');
  await page.type('[data-sum="counted"]', '102');
  await page.click('#sendBtn');
  await until(() => page.evaluate(() => current().status === 'submitted'), 10000);
  await page.click('.tab[data-tab="sales"]');
  check('sent sheet: insert buttons hidden', await page.$$eval('[data-ins-line]', (els) => els.every((e) => e.offsetParent === null)));
  await page.evaluate(() => document.querySelector('[data-change-line="0"]').click());
  check('sent sheet: tapping a name does not start a change', await page.$eval('#pickHint', (el) => el.classList.contains('hidden')));
  check('sent sheet: lines unchanged', short(await lines()).length === 5);

  /* 6. English strings. */
  await page.evaluate(() => setLang('en'));
  await page.evaluate(() => { S.current = null; });
  await page.evaluate(() => newSheet());
  await pick('alfa');
  await page.click('[data-ins-line="0"]');
  check('English insert hint', await page.$eval('#pickHint', (el) => /after line 1\b/i.test(el.textContent)), await page.$eval('#pickHint', (el) => el.textContent));
  await page.click('#pickCancel');
  await page.evaluate(() => setLang('pt'));

  check('no script errors', errors.length === 0, errors);
  await browser.close();
}

run().catch((e) => {
  console.error(e);
  results.push({ name: 'crashed', ok: false });
}).then(() => {
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
});
