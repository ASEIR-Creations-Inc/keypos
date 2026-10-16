/* One-off: split frontend/js/pos.js into per-screen files under frontend/js/app/.
 *
 * Every top-level statement (with the comments and blank lines above it) goes to
 * exactly one file, unchanged. The script then proves the split is lossless and that
 * no statement that runs at load time uses a function from a file loaded after it.
 *   node tools/split.js
 */
const fs = require('fs');
const path = require('path');
const esprima = require('/pos/tests/node_modules/esprima');

const JS = path.join(__dirname, '..', 'frontend', 'js');
const ORDER = ['core', 'settings', 'catalog', 'offline', 'tickets', 'cart', 'payment', 'shift', 'sales',
  'inventory', 'purchases', 'customers', 'expenses', 'users', 'csv', 'reports', 'init'];

/* [first line, last line, file] by the statement's first line in pos.js */
const RANGES = [
  [1, 128, 'core'], [129, 273, 'init'], [274, 536, 'shift'], [537, 588, 'settings'],
  [589, 642, 'catalog'], [643, 756, 'offline'], [757, 840, 'catalog'], [841, 933, 'tickets'],
  [934, 1188, 'cart'], [1189, 1416, 'payment'], [1417, 1610, 'expenses'], [1611, 1742, 'users'],
  [1743, 1798, 'csv'], [1799, 2061, 'inventory'], [2062, 2289, 'purchases'], [2290, 2612, 'reports'],
  [2613, 2787, 'customers'], [2832, 3100, 'sales'],
];
/* Statements that sit in the wrong section of pos.js, by a unique snippet of their text */
const MOVES = [
  ['var CUSTOMERS_STATE', 'customers'],
  ['function deletePurchaseOrder', 'purchases'],
  ['"addCustomerBtn"', 'customers'], ['"saveCustomerBtn"', 'customers'], ['"receivePaymentBtn"', 'customers'],
  ['var cancelCustomerBtn', 'customers'], ['if (cancelCustomerBtn)', 'customers'],
  ['var closeCustomerDetailBtn', 'customers'], ['if (closeCustomerDetailBtn)', 'customers'],
  ['var customersSearchInput', 'customers'], ['if (customersSearchInput)', 'customers'],
  ['"saveExpenseBtn"', 'expenses'], ['"addExpenseLineBtn"', 'expenses'],
  ['"saveUserBtn"', 'users'],
  ['"cartItemBack"', 'cart'], ['"applyCartItemBtn"', 'cart'], ['"removeCartItemBtn"', 'cart'],
  ['"cartItemMinus"', 'cart'], ['"cartItemPlus"', 'cart'],
  ['var cartItemPriceEl', 'cart'], ['var cartItemQtyEl', 'cart'], ['var cartItemDiscEl', 'cart'],
  ['if (cartItemPriceEl)', 'cart'], ['if (cartItemQtyEl)', 'cart'], ['if (cartItemDiscEl)', 'cart'],
  ['"deleteAllInventoryBtn"', 'inventory'],
  ['"exportProductsBtn"', 'csv'], ['"exportCustomersBtn"', 'csv'], ['"exportSalesBtn"', 'csv'],
  ['"exportExpensesBtn"', 'csv'], ['"templateProductsBtn"', 'csv'], ['"templateCustomersBtn"', 'csv'],
  ['"importProductsBtn"', 'csv'], ['"importCustomersBtn"', 'csv'],
];
const HEADER = '/* KEYPOS — %s. Part of the register app; see js/app/core.js for load order. */\n' +
  '/* Android 6 compatible — no arrow functions, no const/let */\n';
const TITLES = {
  core: 'shared state, DOM references and helpers', settings: 'store settings', catalog: 'products and categories',
  offline: 'offline sales and the sync badge', tickets: 'saved tickets', cart: 'cart and cart item editor',
  payment: 'payment panel', shift: 'shifts and Z-reports', sales: 'recent sales, refunds and re-issues',
  inventory: 'inventory screen', purchases: 'purchase orders', customers: 'customers and account ledger',
  expenses: 'expenses', users: 'users', csv: 'CSV import and export', reports: 'reports', init: 'start-up',
};

const src = fs.readFileSync(path.join(JS, 'pos.js'), 'utf8');
const ast = esprima.parseScript(src, { range: true, loc: true });

function fileFor(st, text) {
  for (const [snippet, file] of MOVES) if (text.indexOf(snippet) > -1 && text.split('\n')[0].indexOf(snippet) > -1) return file;
  const line = st.loc.start.line;
  for (const [a, b, file] of RANGES) if (line >= a && line <= b) return file;
  throw new Error('No file for statement at line ' + line + ': ' + text.slice(0, 60));
}

/* Chunk = the source from the end of the previous statement to the end of this one,
   so leading comments and section banners travel with their statement. */
const out = Object.fromEntries(ORDER.map((f) => [f, []]));
let cursor = 0;
const placed = [];
for (const st of ast.body) {
  const chunk = src.slice(cursor, st.range[1]);
  const file = fileFor(st, src.slice(st.range[0], st.range[1]));
  out[file].push(chunk);
  placed.push({ file, text: src.slice(st.range[0], st.range[1]), st });
  cursor = st.range[1];
}
const trailing = src.slice(cursor);
if (trailing.trim()) throw new Error('Unexpected trailing code: ' + trailing.slice(0, 60));

/* Lossless: every statement appears exactly once across the files, byte for byte. */
const written = {};
for (const file of ORDER) {
  let body = out[file].join('').replace(/^\s*\n/, '');
  if (file === 'core') body = body.replace(/^\/\* POS Screen Logic[^\n]*\n(\/\*[^\n]*\*\/\n)?/, '');
  written[file] = HEADER.replace('%s', TITLES[file]) + '\n' + body.replace(/\s*$/, '') + '\n';
}
const reparsed = ORDER.flatMap((f) => esprima.parseScript(written[f], { range: true }).body
  .map((st) => written[f].slice(st.range[0], st.range[1])));
const original = ast.body.map((st) => src.slice(st.range[0], st.range[1]));
if (reparsed.length !== original.length || original.some((t) => reparsed.indexOf(t) === -1)) {
  throw new Error('Split is not lossless');
}

/* Load order: identifiers used directly by load-time statements must be defined in the
   same file or an earlier one (or come from api.js / db.js / sync.js / the browser). */
const definedIn = {};
for (const p of placed) {
  if (p.st.type === 'FunctionDeclaration') definedIn[p.st.id.name] = p.file;
  if (p.st.type === 'VariableDeclaration') p.st.declarations.forEach((d) => { definedIn[d.id.name] = p.file; });
}
function loadTimeIdentifiers(node, acc) {
  if (!node || typeof node.type !== 'string') return acc;
  if (/Function/.test(node.type)) return acc;
  if (node.type === 'Identifier') acc.push(node.name);
  for (const key of Object.keys(node)) {
    if (key === 'property' && node.type === 'MemberExpression' && !node.computed) continue;
    if (key === 'key' && node.type === 'Property') continue;
    const value = node[key];
    if (Array.isArray(value)) value.forEach((v) => loadTimeIdentifiers(v, acc));
    else if (value && typeof value.type === 'string') loadTimeIdentifiers(value, acc);
  }
  return acc;
}
const problems = [];
for (const p of placed) {
  if (p.st.type === 'FunctionDeclaration') continue;
  for (const name of loadTimeIdentifiers(p.st, [])) {
    const home = definedIn[name];
    if (home && ORDER.indexOf(home) > ORDER.indexOf(p.file)) problems.push(`${p.file} uses ${name} from ${home} at load`);
  }
}
if (problems.length) throw new Error('Load-order problems:\n' + problems.join('\n'));

fs.mkdirSync(path.join(JS, 'app'), { recursive: true });
for (const file of ORDER) fs.writeFileSync(path.join(JS, 'app', file + '.js'), written[file]);
fs.unlinkSync(path.join(JS, 'pos.js'));
console.log('split into', ORDER.length, 'files;', original.length, 'statements placed; load order OK');
console.log(ORDER.map((f) => `${f}: ${written[f].split('\n').length} lines`).join('\n'));
