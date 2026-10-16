/* Inventory UX test: editing a product keeps its stock and cost, the product form's
 * category/unit dropdowns (with "+ New ..."), sortable columns and filters, and
 * creating a new product from inside a purchase.
 * Run against a TEST copy of the database, never production:
 *   CHROME=... BASE=http://127.0.0.1:8095 node test-inventory.js
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
const tag = Date.now().toString(36);

async function run() {
  const A = Number(sql('select id from products where is_active order by id limit 1'));
  sql(`update products set stock_qty=16, cost_price=8800 where id=${A}`);

  const browser = await puppeteer.launch({ args: ['--no-sandbox'], headless: true, executablePath: process.env.CHROME || undefined });
  const page = await browser.newPage();
  await page.setViewport({ width: 412, height: 860 });
  const errors = [];
  const alerts = [];
  const promptAnswers = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => {
    if (d.type() === 'prompt') return d.accept(promptAnswers.shift() || '');
    if (d.type() === 'alert') alerts.push(d.message());
    return d.accept();
  });
  const click = (sel) => page.$eval(sel, (el) => el.click());
  const select = async (sel, value) => {
    await page.$eval(sel, (el, v) => { el.value = v; el.dispatchEvent(new Event('change')); }, value);
  };
  const rowNames = () => page.$$eval('#inventoryTableBody tr td:first-child', (tds) => tds.map((td) => td.firstChild.textContent));

  await signIn(page, BASE);
  await page.goto(BASE + '/pos.html');
  await wait(2500);
  check('no script errors on load', errors.length === 0, errors.join(' | '));

  /* 1. Edit keeps stock and cost; new category and unit created from the form */
  await page.evaluate(() => showScreen('inventory'));
  await wait(1500);
  await page.evaluate((id) => editProduct(id), A);
  await wait(1000);
  await page.$eval('#editProductName', (el, t) => { el.value = el.value + ' ' + t; }, tag);
  promptAnswers.push('Cat ' + tag);
  await select('#editProductCategory', '__new');
  await wait(1200);
  const catSelected = await page.$eval('#editProductCategory', (el) => el.options[el.selectedIndex].text);
  check('"+ New category" creates and selects it', catSelected === 'Cat ' + tag, catSelected);
  const unitOptions = await page.$$eval('#editProductUnit option', (os) => os.map((o) => o.text));
  check('unit dropdown offers "+ New unit..."', unitOptions.indexOf('+ New unit...') !== -1, unitOptions.join(','));
  promptAnswers.push('kg' + tag);
  await select('#editProductUnit', '__new');
  await wait(1200);
  const unitSelected = await page.$eval('#editProductUnit', (el) => el.options[el.selectedIndex].text);
  check('"+ New unit" creates and selects it', unitSelected === 'kg' + tag, unitSelected);
  await click('#saveProductBtn');
  await wait(1500);
  const [stock, cost, catName, unitName] = sql(
    `select p.stock_qty, p.cost_price, c.name, u.name from products p left join categories c on c.id=p.category_id left join units u on u.id=p.unit_id where p.id=${A}`).split('|');
  check('edit keeps stock (16)', parseFloat(stock) === 16, stock);
  check('edit keeps cost (8800)', parseFloat(cost) === 8800, cost);
  check('edit saved category and unit', catName === 'Cat ' + tag && unitName === 'kg' + tag, catName + '/' + unitName);
  const moved = sql(`select count(*) from stock_movements m join audit_log a on a.id=m.audit_id where a.action='product_edited' and m.product_id=${A}`);
  check('edit wrote no stock movement', moved === '0', moved);

  /* 2. Sortable headers and filters */
  await wait(500);
  const arrows = await page.$$eval('#inventoryTable th .sort-arrow', (els) => els.map((e) => e.textContent));
  check('every sortable header shows an arrow', arrows.length === 4 && arrows.every((a) => a), arrows.join(''));
  await click('#inventoryTable th[data-sort="stock"]');
  await wait(300);
  const stocksAsc = await page.$$eval('#inventoryTableBody tr td:nth-child(2)', (tds) => tds.map((td) => parseFloat(td.textContent)));
  check('Stock header sorts ascending', stocksAsc.every((v, i) => i === 0 || stocksAsc[i - 1] <= v), stocksAsc.slice(0, 8).join(','));
  await click('#inventoryTable th[data-sort="stock"]');
  await wait(300);
  const stocksDesc = await page.$$eval('#inventoryTableBody tr td:nth-child(2)', (tds) => tds.map((td) => parseFloat(td.textContent)));
  check('tapping again sorts descending', stocksDesc.every((v, i) => i === 0 || stocksDesc[i - 1] >= v), stocksDesc.slice(0, 8).join(','));
  const arrow = await page.$eval('#inventoryTable th[data-sort="stock"] .sort-arrow', (e) => e.textContent);
  check('active header shows ▼ when descending', arrow === '▼', arrow);
  await click('#inventoryTable th[data-sort="name"]');
  await wait(300);
  const names = (await rowNames()).map((n) => n.toLowerCase());
  check('Name header sorts A-Z', names.every((n, i) => i === 0 || names[i - 1] <= n), names.slice(0, 5).join(' | '));
  const catId = sql(`select id from categories where name='Cat ${tag}'`);
  await select('#inventoryCategoryFilter', catId);
  await wait(300);
  const inCat = await rowNames();
  check('category filter shows only that category', inCat.length === 1 && inCat[0].indexOf(tag) !== -1, inCat.join(' | '));
  await select('#inventoryCategoryFilter', '');
  await select('#inventoryStockFilter', 'out');
  await wait(300);
  const outStocks = await page.$$eval('#inventoryTableBody tr td:nth-child(2)', (tds) => tds.map((td) => parseFloat(td.textContent)));
  const expectedOut = Number(sql('select count(*) from products where is_active and stock_qty<=0'));
  check('"Out of stock" filter', outStocks.length === expectedOut && outStocks.every((v) => v <= 0), outStocks.length + ' vs ' + expectedOut);
  await select('#inventoryStockFilter', '');

  /* 3. Create a new product from inside a purchase */
  await page.evaluate(() => { showScreen('purchases'); });
  await wait(1500);
  await click('#newPurchaseBtn');
  await wait(800);
  const newName = 'PO New ' + tag;
  await page.type('#lineProduct', newName);
  await wait(400);
  const createItem = await page.$$eval('#productDropdown div', (ds) => ds.map((d) => d.textContent));
  check('product search offers "+ Create new product"', createItem.some((t) => t.indexOf('+ Create new product') === 0), createItem.join(' | '));
  await page.$$eval('#productDropdown .po-new-product', (ds) => ds[0].click());
  await wait(1000);
  const formOnTop = await page.evaluate(() => {
    const p = document.getElementById('productPanel');
    const po = document.getElementById('purchaseFormPanel');
    return p.classList.contains('active') && Number(p.style.zIndex) > Number(po.style.zIndex);
  });
  check('product form opens on top of the purchase', formOnTop);
  const prefilled = await page.$eval('#editProductName', (el) => el.value);
  check('product form is prefilled with the typed name', prefilled === newName, prefilled);
  await click('#saveProductBtn');
  await wait(1500);
  const lineProduct = await page.$eval('#lineProduct', (el) => [el.value, el.getAttribute('data-product-id')]);
  const newId = sql(`select id from products where name='${newName}'`);
  check('new product is filled into the purchase line', lineProduct[0] === newName && lineProduct[1] === newId, lineProduct.join('/') + ' id ' + newId);
  await page.type('#lineQty', '12');
  await page.type('#lineCost', '250');
  await click('#addPurchaseLineBtn');
  await click('#postPurchaseBtn');
  await wait(2500);
  const [newStock, newCost] = sql(`select stock_qty, cost_price from products where id=${newId}`).split('|');
  check('posting the purchase stocks the new product', parseFloat(newStock) === 12 && parseFloat(newCost) === 250, newStock + '/' + newCost);
  const purchaseOpen = await page.evaluate(() => document.getElementById('purchaseFormPanel').classList.contains('active'));
  check('purchase form closed after posting', !purchaseOpen);

  check('no script errors overall', errors.length === 0, errors.join(' | '));
  await browser.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
}

run().catch((e) => { console.error(e); process.exit(1); });
