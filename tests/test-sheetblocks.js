/* KEYPOS Sheet app: blocks and Cash/Card/Split marks. One sheet holds several blocks of lines,
 * numbered per block; stock is checked across all blocks; the Summary still counts the whole
 * sheet once, with the machine slip as the card total and the marked card as a reference only.
 * Approval issues one receipt per block, sharing the slip out between them.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-sheetblocks.js
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
  return r.status === 204 ? null : r.json().catch(() => null);
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
  const alfa = await send('POST', '/products', { name: `ZZ${tag} ALFA`, sell_price: '0' });
  const beta = await send('POST', '/products', { name: `ZZ${tag} BETA`, sell_price: '0' });
  sql(`update products set stock_qty=4 where id=${alfa.id}`);
  sql(`update products set stock_qty=50 where id=${beta.id}`);
  const username = `blk_${low}`;
  await send('POST', '/users', { name: 'Bia Blocos', username, password: 'sheet-pass-1', role: 'sheet' });

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
  const setField = async (i, f, v) => {
    await page.$eval(`[data-line="${i}"][data-f="${f}"]`, (el) => { el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });
    if (v) await page.type(`[data-line="${i}"][data-f="${f}"]`, v);
  };
  const setSum = async (f, v) => {
    await page.$eval(`[data-sum="${f}"]`, (el) => { el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await page.type(`[data-sum="${f}"]`, v);
  };
  const lines = () => page.evaluate(() => current().content.lines.map((l) => [l.product.split(' ').pop(), l.block, l.qty, l.price, l.pay, l.card].join(' ').trim()));
  const shown = () => page.$$eval('#lines .row', (rows) => rows.map((r) => r.querySelector('.row-num').textContent + ' ' + r.querySelector('.row-name').textContent.split(' ').pop()));
  const chips = () => page.$$eval('#blockBar .block-chip', (els) => els.map((e) => e.textContent.replace(/\s+/g, ' ').replace('×', '').trim()));

  /* 1. A new sheet: one block, and a + BLOCK button. Lines default to Cash. */
  check('new sheet shows Bloco 1 and + BLOCO', (await chips()).join('|') === 'Bloco 1 (0)' && !!(await page.$('[data-new-block]')), await chips());
  await pick('alfa'); await setField(0, 'qty', '2'); await setField(0, 'price', '10');
  await pick('beta'); await setField(1, 'price', '5');
  check('a new line is marked Cash', await page.$eval('[data-pay="1"][data-v="cash"]', (el) => el.className === 'on'));
  await page.click('[data-pay="0"][data-v="card"]');
  check('tapping Cartão marks the line card', (await lines())[0] === 'ALFA 1 2 10 card');

  /* 2. + BLOCO: block 2 on screen, empty; block 1 keeps its lines and count. */
  await page.click('[data-new-block]');
  check('block 2 created and shown', (await chips()).join('|') === 'Bloco 1 (2)|Bloco 2 (0)' &&
    await page.$eval('#blockBar .block-chip.on', (el) => /Bloco 2/.test(el.textContent)), await chips());
  check('block 2 starts with no lines on screen', (await shown()).length === 0);
  await pick('alfa'); await setField(2, 'qty', '3'); await setField(2, 'price', '10');
  check('a line added in block 2 is #1 of block 2', (await shown()).join('|') === '#1 ALFA', await shown());
  check('it is stored in block 2, after block 1', (await lines())[2] === 'ALFA 2 3 10 cash', await lines());

  /* 3. Stock is checked across blocks: ALFA 2 + 3 = 5 > 4. */
  check('stock across blocks: block 2 line red', await page.$eval('#line-2', (el) => el.className === 'row bad'));
  check('problem names the block and line', await page.$eval('#problemList', (el) => /Bloco 2 · Linha 1: SEM STOCK/.test(el.textContent)),
    await page.$eval('#problemList', (el) => el.textContent));
  await page.click('#blockBar [data-block="1"]');
  check('switching to block 1 shows its two lines', (await shown()).join('|') === '#2 BETA|#1 ALFA', await shown());
  check('block 1 ALFA line red too', await page.$eval('#line-0', (el) => el.className === 'row bad'));
  await page.click('#blockBar [data-block="2"]');
  await setField(2, 'qty', '2');
  check('within stock again: no red lines', await page.$eval('#line-2', (el) => el.className === 'row ok'));

  /* 4. Split needs the card part, no more than the line total. */
  await page.click('[data-pay="2"][data-v="split"]');
  check('split shows a card part field', !!(await page.$('[data-line="2"][data-f="card"]')));
  check('split without a card part is flagged', await page.$eval('#line-status-2', (el) => /PARTE EM CARTÃO/.test(el.textContent)));
  await setField(2, 'card', '25');
  check('card part above the line total is flagged', await page.$eval('#line-status-2', (el) => /CARTÃO > TOTAL/.test(el.textContent)));
  await setField(2, 'card', '4');
  check('valid split is ok', await page.$eval('#line-2', (el) => el.className === 'row ok'));

  /* 5. Insert inside block 1 stays in block 1; block 2 is untouched. */
  await page.click('#blockBar [data-block="1"]');
  await page.click('[data-ins-line="0"]');
  check('insert hint uses the number in the block', await page.$eval('#pickText', (el) => /linha 1\b/i.test(el.textContent)));
  await pick('beta'); await setField(1, 'price', '5');
  check('inserted line is #2 of block 1, old #2 moves to #3', (await shown()).join('|') === '#3 BETA|#2 BETA|#1 ALFA', await shown());
  check('block 2 line untouched', (await lines()).join('|') === 'ALFA 1 2 10 card|BETA 1 1 5 cash|BETA 1 1 5 cash|ALFA 2 2 10 split 4', await lines());

  /* 6. An empty block can be removed; a block with lines can't. */
  await page.click('[data-new-block]');
  check('block 3 created', (await chips()).length === 3);
  check('only the empty block has a remove button', (await page.$$('[data-del-block]')).length === 1 && !!(await page.$('[data-del-block="3"]')));
  await page.click('[data-del-block="3"]');
  check('empty block removed', (await chips()).join('|') === 'Bloco 1 (3)|Bloco 2 (1)', await chips());

  /* 7. Summary: one total for the whole sheet; slip decides; marks are a reference. */
  await page.click('.tab[data-tab="summary"]');
  await setSum('card', '10');
  await setSum('counted', '40');
  const summary = () => page.$eval('#summaryForm', (el) => el.textContent);
  check('summary: total of all blocks', /50[.,]00/.test(await page.$eval('#sumGrand', (el) => el.textContent)), await page.$eval('#sumGrand', (el) => el.textContent));
  check('summary: cash sales use the slip (50 − 10 = 40)', /40[.,]00/.test(await page.$eval('#sumCash', (el) => el.textContent)));
  check('summary: card marked shown as reference (20 + 4)', /24[.,]00/.test(await page.$eval('#sumCardMarked', (el) => el.textContent)));
  check('summary: warns marked card is more than the slip', /maior do que o talão/.test(await summary()));
  check('summary: lists each block\'s receipt', /Bloco 1 · 3 linhas/.test(await summary()) && /Bloco 2 · 1 linhas/.test(await summary()), await summary());
  check('difference uses the slip, not the marks', /CERTO/.test(await page.$eval('#sumDifference', (el) => el.textContent)));
  await setSum('card', '30');
  await setSum('counted', '20');
  check('no warning once the slip covers the marks', !/maior do que o talão/.test(await summary()));
  check('still balanced', /CERTO/.test(await page.$eval('#sumDifference', (el) => el.textContent)));

  /* 8. The server has the blocks and marks. */
  const content = () => sql(`select content->>'blocks' || ':' || (select string_agg((l->>'block') || (l->>'pay'), ',' order by n) from jsonb_array_elements(content->'lines') with ordinality as x(l, n)) from day_sheets where token='${token}'`);
  check('server has blocks and pay marks', await until(() => content() === '2:1card,1cash,1cash,2split', 10000), content());

  /* 9. Send, then the admin approves: two receipts sharing the slip. */
  await page.click('#sendBtn');
  await until(() => page.evaluate(() => current().status === 'submitted'), 10000);
  check('sheet sent', await page.evaluate(() => current().status === 'submitted'));
  const sheetId = Number(sql(`select id from day_sheets where token='${token}'`));
  const shift = await api('/shifts/current');
  if (!shift || !shift.id) await send('POST', '/shifts/open', { opening_float: 0 });

  const adm = await (await browser.createBrowserContext()).newPage();
  adm.on('pageerror', (e) => errors.push('pos: ' + e.message));
  adm.on('dialog', (d) => d.accept());
  await adm.setViewport({ width: 360, height: 760 });
  await signIn(adm);
  await adm.goto(BASE + '/pos.html');
  await adm.waitForSelector('#shiftStatus');
  await adm.evaluate((id) => openSheetReview(id), sheetId);
  await adm.waitForSelector('#sheetApproveBtn');
  const reviewText = await adm.$eval('#sheetReviewBody', (el) => el.textContent);
  check('POS review lists one receipt per block', /Receipts \(one per block\)/.test(reviewText) && /1 · 3 lines/.test(reviewText) && /2 · 1 lines/.test(reviewText), reviewText);
  check('POS review shows the marks on lines', /· Card/.test(reviewText) && /· Split/.test(reviewText));
  await adm.click('#sheetApproveBtn');
  await until(() => sql(`select status from day_sheets where id=${sheetId}`) === 'approved', 10000);
  const receipts = sql(`select string_agg(t.total_amount || '/' || t.payment_card, ',' order by t.id) from transactions t where t.client_ref like '${token}%'`);
  check('two receipts: 30 and 20, card 22.31 + 7.69 = the slip 30', receipts === '30.00/22.31,20.00/7.69', receipts);
  check('stock deducted across both blocks', sql(`select stock_qty::int from products where id=${alfa.id}`) === '0' &&
    sql(`select stock_qty::int from products where id=${beta.id}`) === '48');
  await until(() => adm.$eval('#sheetReviewBody', (el) => /Approved by/.test(el.textContent)), 8000);
  check('POS shows both receipt numbers after approval',
    (await adm.$eval('#sheetReviewBody', (el) => (el.textContent.match(/TXN-/g) || []).length)) >= 2);

  /* 10. The employee sees the approved sheet with both receipts; blocks can still be viewed. */
  await page.reload();
  await page.waitForSelector('#appView:not(.hidden)');
  await until(() => page.evaluate((tk) => { const s = sheetOf(tk); return s && s.status === 'approved'; }, token), 10000);
  await page.evaluate((tk) => openSheet(tk), token);
  check('banner lists both receipts', await page.$eval('#sheetBanner', (el) => (el.textContent.match(/TXN-/g) || []).length === 2),
    await page.$eval('#sheetBanner', (el) => el.textContent));
  check('approved: no + BLOCO, but blocks can be viewed', !(await page.$('[data-new-block]')) && (await chips()).length === 2);
  await page.click('#blockBar [data-block="2"]');
  check('approved: block 2 shows its line', (await shown()).join('|') === '#1 ALFA');

  /* 11. English. */
  await page.evaluate(() => setLang('en'));
  check('English block chips', (await chips())[0] === 'Block 1 (3)', await chips());
  await page.evaluate(() => setLang('pt'));

  /* 12. A draft kept on the phone by the app before blocks existed still gets + BLOCO. */
  await page.evaluate((id, name) => {
    const old = { token: newToken(), code: null, status: 'draft', sheet_date: today(), dirty: true, rev: 1, sent: false,
      content: { lines: [{ product_id: id, product: name, qty: '1', price: '5' }], expenses: [], card: '', counted: '', start: '' } };
    const list = JSON.parse(localStorage.getItem(storeKey()) || '[]');
    list.unshift(old);
    localStorage.setItem(storeKey(), JSON.stringify(list));
    window.__oldToken = old.token;
  }, beta.id, beta.name);
  const oldToken = await page.evaluate(() => window.__oldToken);
  await page.reload();
  await page.waitForSelector('#appView:not(.hidden)');
  await page.evaluate((tk) => openSheet(tk), oldToken);
  check('old-format draft: one block with + BLOCO', (await chips()).join('|') === 'Bloco 1 (1)' && !!(await page.$('[data-new-block]')), await chips());
  check('old-format draft: its line is Cash', await page.$eval('[data-v="cash"]', (el) => el.className === 'on'));

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
