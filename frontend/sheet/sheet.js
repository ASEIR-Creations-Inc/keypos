/* KEYPOS Sheet — the day sheet app: fill in the day's sales and expenses on a phone, send
   it for approval, and an approver records it in the POS.

   Every change is kept on the phone at once (localStorage, per signed-in user) and saved
   to the server a moment later whenever there is a connection. The phone gives each sheet
   its id (token), so a save that is retried can never create a second sheet. The server
   checks everything again when the sheet is sent and when it is approved.

   A sheet holds one or more blocks of lines; approval issues one receipt per block. Lines
   stay one flat list, each with its block number, in block order. Each line is marked
   Cash, Card or Split; the marks are only a reference — the card machine slip on the
   Summary is the card total, and the server shares it out between the receipts.
   Android 6 compatible — no arrow functions, no const/let, no template literals. */

var LANG_KEY = "sheet_lang";
var CATALOG_KEY = "sheet_catalog";
var SAVE_DELAY = 1200;
var SEARCH_LIMIT = 40;
var EDITABLE = { draft: true, returned: true };
var MAX_BLOCKS = 20;
var MAX_BLOCK_LINES = 1000;

var T = {
  pt: {
    username: "Utilizador", password: "Palavra-passe", signIn: "Entrar", signingIn: "A entrar...",
    badLogin: "Utilizador ou palavra-passe inválidos", tooMany: "Demasiadas tentativas. Espere um minuto.",
    noServer: "Sem ligação ao servidor", language: "Idioma", openPos: "Abrir o KEYPOS", signOut: "Sair",
    newSheet: "+ NOVA FOLHA", noSheets: "Ainda não tem folhas. Toque em NOVA FOLHA para começar.",
    notSynced: "Nova (por sincronizar)", sales: "Vendas", expenses: "Despesas", summary: "Resumo",
    search: "Procurar produto (escreva parte do nome)", noMatch: "Nenhum produto encontrado",
    addExpense: "+ ADICIONAR DESPESA", qty: "Qtd", price: "Preço", amount: "Valor", category: "Categoria",
    noCategory: "— (opcional)", description: "Descrição", paidFrom: "Pago de", drawer: "Caixa", other: "Outro",
    ok: "✓", noStock: "SEM STOCK", noQty: "SEM QTD", noPrice: "SEM PREÇO", inactive: "PRODUTO INATIVO",
    noAmount: "SEM VALOR", noPaidFrom: "PAGO DE?", badCategory: "CATEGORIA?", badNumber: "NÚMERO INVÁLIDO",
    send: "ENVIAR PARA APROVAÇÃO", discard: "APAGAR RASCUNHO",
    status_draft: "RASCUNHO", status_submitted: "ENVIADA", status_returned: "DEVOLVIDA", status_approved: "APROVADA",
    lines: "linhas", line: "Linha", expense: "Despesa",
    secSales: "Vendas", grandTotal: "Total de vendas (dinheiro + cartão)", tax: "Imposto", receiptTotal: "Total do recibo",
    card: "− Cartão (talão da máquina)", cashSales: "= Vendas em dinheiro", secCash: "Conferência do dinheiro",
    counted: "Dinheiro contado", drawerExp: "+ Despesas pagas da caixa", start: "− Dinheiro inicial (opcional)",
    accounted: "= Dinheiro justificado", otherExp: "Despesas pagas de outro lado", difference: "Diferença",
    extra: "SOBRA DE CAIXA", short: "FALTA", even: "CERTO",
    needCard: "Escreva o total do talão do cartão no Resumo (0 se não houve vendas com cartão)",
    needCounted: "Escreva o dinheiro contado no Resumo", cardTooBig: "O talão do cartão é maior do que as vendas",
    emptySheet: "A folha não tem vendas nem despesas", fixFirst: "Corrija antes de enviar:",
    confirmSend: "Enviar {code} para aprovação?\n\n{n} linhas · total {total}\n\nDepois de enviada, só pode ser alterada se um gestor a devolver.",
    sent: "Enviada. Um gestor vai verificar e aprovar.", sendFailed: "Não foi enviada: ",
    needOnline: "Precisa de internet para enviar. A folha está guardada no telefone.",
    confirmDiscard: "Apagar este rascunho? Não pode ser desfeito.", deleteFailed: "Não foi apagada: ",
    saveRefused: "O servidor não aceitou a folha. Corrija e continue: ",
    bannerDraft: "Rascunho — guardado enquanto escreve. Envie no fim do dia.",
    bannerSubmitted: "Enviada — à espera de aprovação. Já não pode ser alterada.",
    bannerReturned: "Devolvida por {who}: «{note}». Corrija e envie outra vez.",
    bannerApproved: "Aprovada — recibo {ref}.", bannerApprovedNoSales: "Aprovada.",
    syncedAll: "Tudo guardado no servidor", syncPending: "Guardado no telefone — a enviar para o servidor",
    syncOffline: "Sem internet — guardado no telefone", lockedElsewhere: "Esta folha já foi enviada. Foi carregada a versão do servidor.",
    goneElsewhere: "Esta folha já não existe no servidor.",
    insertAfter: "Inserir depois da linha {n} — escolha o produto", changeLine: "Mudar o produto da linha {n} — escolha o novo produto",
    cancel: "Cancelar", insertHere: "Inserir uma linha depois desta", changeProduct: "Mudar o produto",
    block: "Bloco", newBlock: "+ BLOCO", removeBlock: "Remover o bloco vazio",
    blockFull: "O bloco {n} já tem 1000 linhas. Toque em + BLOCO para começar um novo bloco.",
    maxBlocks: "Uma folha pode ter no máximo 20 blocos.",
    payCash: "Dinheiro", payCard: "Cartão", paySplit: "Misto", cardPart: "Parte em cartão",
    noCardPart: "PARTE EM CARTÃO?", cardPartTooBig: "CARTÃO > TOTAL",
    secBlocks: "Blocos (um recibo cada)", blockLine: "Bloco {n} · {lines} linhas",
    cardMarked: "Cartão marcado nas linhas (só referência)",
    cardMarkedOver: "O cartão marcado nas linhas é maior do que o talão. Conta o talão.",
    confirmSendBlocks: "Enviar {code} para aprovação?\n\n{n} linhas em {b} blocos ({b} recibos) · total {total}\n\nDepois de enviada, só pode ser alterada se um gestor a devolver.",
    bannerApprovedMany: "Aprovada — recibos {refs}.", blocksN: "{n} blocos"
  },
  en: {
    username: "Username", password: "Password", signIn: "Sign in", signingIn: "Signing in...",
    badLogin: "Invalid username or password", tooMany: "Too many attempts. Wait a minute.",
    noServer: "No connection to the server", language: "Language", openPos: "Open KEYPOS", signOut: "Sign out",
    newSheet: "+ NEW SHEET", noSheets: "No sheets yet. Tap NEW SHEET to start.",
    notSynced: "New (not synced yet)", sales: "Sales", expenses: "Expenses", summary: "Summary",
    search: "Search product (type part of the name)", noMatch: "No product found",
    addExpense: "+ ADD EXPENSE", qty: "Qty", price: "Price", amount: "Amount", category: "Category",
    noCategory: "— (optional)", description: "Description", paidFrom: "Paid from", drawer: "Drawer", other: "Other",
    ok: "✓", noStock: "NO STOCK", noQty: "NO QTY", noPrice: "NO PRICE", inactive: "PRODUCT INACTIVE",
    noAmount: "NO AMOUNT", noPaidFrom: "PAID FROM?", badCategory: "CATEGORY?", badNumber: "NOT A NUMBER",
    send: "SEND FOR APPROVAL", discard: "DELETE DRAFT",
    status_draft: "DRAFT", status_submitted: "SENT", status_returned: "RETURNED", status_approved: "APPROVED",
    lines: "lines", line: "Line", expense: "Expense",
    secSales: "Sales", grandTotal: "Sales total (cash + card)", tax: "Tax", receiptTotal: "Receipt total",
    card: "− Card (machine slip)", cashSales: "= Cash sales", secCash: "Cash check",
    counted: "Cash counted", drawerExp: "+ Expenses paid from drawer", start: "− Starting cash (optional)",
    accounted: "= Cash accounted for", otherExp: "Expenses paid from elsewhere", difference: "Difference",
    extra: "EXTRA CASH", short: "SHORT", even: "BALANCED",
    needCard: "Enter the card machine slip total on the Summary (0 if there were no card sales)",
    needCounted: "Enter the cash counted on the Summary", cardTooBig: "The card slip total is more than the sales",
    emptySheet: "The sheet has no sales or expenses", fixFirst: "Fix these before sending:",
    confirmSend: "Send {code} for approval?\n\n{n} lines · total {total}\n\nOnce sent, it can only be changed if a manager returns it.",
    sent: "Sent. A manager will check and approve it.", sendFailed: "Not sent: ",
    needOnline: "You need internet to send. The sheet is saved on this phone.",
    confirmDiscard: "Delete this draft? This can't be undone.", deleteFailed: "Not deleted: ",
    saveRefused: "The server didn't accept the sheet. Fix it and carry on: ",
    bannerDraft: "Draft — saved as you type. Send it at the end of the day.",
    bannerSubmitted: "Sent — waiting for approval. It can no longer be changed.",
    bannerReturned: "Returned by {who}: “{note}”. Fix it and send it again.",
    bannerApproved: "Approved — receipt {ref}.", bannerApprovedNoSales: "Approved.",
    syncedAll: "Everything saved on the server", syncPending: "Saved on this phone — sending to the server",
    syncOffline: "No internet — saved on this phone", lockedElsewhere: "This sheet was already sent. The server's copy was loaded.",
    goneElsewhere: "This sheet no longer exists on the server.",
    insertAfter: "Insert after line {n} — choose the product", changeLine: "Change the product of line {n} — choose the new product",
    cancel: "Cancel", insertHere: "Insert a line after this one", changeProduct: "Change the product",
    block: "Block", newBlock: "+ BLOCK", removeBlock: "Remove the empty block",
    blockFull: "Block {n} already has 1000 lines. Tap + BLOCK to start a new block.",
    maxBlocks: "A sheet can have at most 20 blocks.",
    payCash: "Cash", payCard: "Card", paySplit: "Split", cardPart: "Card part",
    noCardPart: "CARD PART?", cardPartTooBig: "CARD > TOTAL",
    secBlocks: "Blocks (one receipt each)", blockLine: "Block {n} · {lines} lines",
    cardMarked: "Card marked on lines (reference only)",
    cardMarkedOver: "The card marked on lines is more than the slip. The slip counts.",
    confirmSendBlocks: "Send {code} for approval?\n\n{n} lines in {b} blocks ({b} receipts) · total {total}\n\nOnce sent, it can only be changed if a manager returns it.",
    bannerApprovedMany: "Approved — receipts {refs}.", blocksN: "{n} blocks"
  }
};

var S = {
  lang: localStorage.getItem(LANG_KEY) || "pt",
  user: null,
  catalog: { products: [], categories: [], currency_symbol: "", tax_rate: "0" },
  productById: {},
  categoryById: {},
  sheets: [],
  current: null,
  tab: "sales",
  block: 1,
  pick: null,
  saveTimer: null,
  syncing: {},
  again: {}
};

/* ── Small helpers ─────────────────────────────────────────── */

function $(id) { return document.getElementById(id); }

function t(key, values) {
  var text = (T[S.lang] && T[S.lang][key]) || T.en[key] || key;
  if (values) {
    for (var name in values) text = text.split("{" + name + "}").join(values[name]);
  }
  return text;
}

function esc(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function cents(value) {
  return Math.round(value * 100 + (value >= 0 ? 1e-6 : -1e-6)) / 100;
}

/* Same format as the POS: "Kz6,500.00", sign before the symbol. */
function money(value) {
  var amount = Math.round((value || 0) * 100) / 100;
  var digits = Math.abs(amount).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (amount < 0 ? "-" : "") + (S.catalog.currency_symbol || "") + digits;
}

function signed(value) {
  return (value > 0 ? "+" : "") + money(value);
}

/* A typed number: "" -> null, "1,5" -> 1.5, anything else that isn't a number -> NaN. */
function parseNum(text) {
  var s = String(text === null || text === undefined ? "" : text).replace(/\s/g, "");
  if (!s) return null;
  if (s.indexOf(",") !== -1) s = s.replace(/\./g, "").replace(",", ".");
  return /^\d+(\.\d+)?$/.test(s) ? parseFloat(s) : NaN;
}

function plain(value) {
  return value === null || value === undefined ? "" : String(value);
}

function fold(text) {
  var s = String(text || "").toLowerCase();
  if (typeof s.normalize === "function") s = s.normalize("NFD").replace(/[̀-ͯ]/g, "");
  return s;
}

function today() {
  var d = new Date();
  return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
}

function showDate(iso) {
  var p = String(iso || "").split("-");
  return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : "";
}

function newToken() {
  var b = new Uint8Array(16);
  (window.crypto || window.msCrypto).getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  var h = [];
  for (var i = 0; i < 16; i++) h.push(("0" + b[i].toString(16)).slice(-2));
  return h.slice(0, 4).join("") + "-" + h.slice(4, 6).join("") + "-" + h.slice(6, 8).join("") + "-" +
    h.slice(8, 10).join("") + "-" + h.slice(10).join("");
}

/* ── The phone's copy ──────────────────────────────────────── */

function storeKey() {
  return "sheet_store_" + (S.user && S.user.id);
}

function persist() {
  try {
    localStorage.setItem(storeKey(), JSON.stringify(S.sheets));
  } catch (e) {
    setSync("offline");
  }
}

function loadLocal() {
  try {
    S.sheets = JSON.parse(localStorage.getItem(storeKey()) || "[]");
  } catch (e) {
    S.sheets = [];
  }
  /* Sheets kept by the app before blocks existed: one block, every line Cash. */
  S.sheets.forEach(function(sh) {
    if (!sh.content) return;
    sh.content.blocks = sh.content.blocks || 1;
    (sh.content.lines || []).forEach(function(l) {
      l.block = l.block || 1;
      l.pay = l.pay || "cash";
      if (l.card === undefined) l.card = "";
    });
  });
  try {
    var cached = JSON.parse(localStorage.getItem(CATALOG_KEY) || "null");
    if (cached) setCatalog(cached);
  } catch (e) { /* no cached catalog yet */ }
}

function setCatalog(catalog) {
  S.catalog = catalog;
  S.productById = {};
  S.categoryById = {};
  catalog.products.forEach(function(p) { S.productById[p.id] = p; });
  catalog.categories.forEach(function(c) { S.categoryById[c.id] = c; });
}

function sheetOf(token) {
  for (var i = 0; i < S.sheets.length; i++) if (S.sheets[i].token === token) return S.sheets[i];
  return null;
}

function current() {
  return sheetOf(S.current);
}

function emptyContent() {
  return { blocks: 1, lines: [], expenses: [], card: "", counted: "", start: "" };
}

/* Server numbers arrive as strings like "2.50"; the phone keeps what was typed. */
function localContent(c) {
  return {
    blocks: c.blocks || 1,
    lines: (c.lines || []).map(function(l) {
      return {
        product_id: l.product_id, product: l.product, qty: plain(l.qty), price: plain(l.price),
        block: l.block || 1, pay: l.pay || "cash", card: plain(l.card)
      };
    }),
    expenses: (c.expenses || []).map(function(e) {
      return { category_id: e.category_id, amount: plain(e.amount), description: e.description || "", paid_from: e.paid_from };
    }),
    card: plain(c.card), counted: plain(c.counted), start: plain(c.start)
  };
}

function wireNum(text) {
  var n = parseNum(text);
  return n === null || isNaN(n) ? null : String(n);
}

function payload(sh) {
  var c = sh.content;
  return {
    lang: S.lang,
    sheet_date: sh.sheet_date,
    content: {
      blocks: c.blocks || 1,
      lines: c.lines.map(function(l) {
        return {
          product_id: l.product_id, product: l.product, qty: wireNum(l.qty), price: wireNum(l.price),
          block: l.block || 1, pay: l.pay || "cash", card: l.pay === "split" ? wireNum(l.card) : null
        };
      }),
      expenses: c.expenses.map(function(e) {
        return { category_id: e.category_id, amount: wireNum(e.amount), description: e.description, paid_from: e.paid_from };
      }),
      card: wireNum(c.card), counted: wireNum(c.counted), start: wireNum(c.start)
    }
  };
}

function fromServer(srv, keepContent) {
  return {
    token: srv.token, code: srv.code, status: srv.status, sheet_date: srv.sheet_date,
    content: keepContent || localContent(srv.content), dirty: !!keepContent, rev: 0,
    sent: !!srv.submitted_at, return_note: srv.return_note, returned_by_name: srv.returned_by_name,
    receipt_ref: srv.receipt_ref, receipt_refs: srv.receipt_refs || []
  };
}

/* ── Checking (the server checks again when the sheet is sent and approved) ── */

/* Each line's number within its block (1, 2, ... per block). */
function lineNumbers(lines) {
  var seen = {}, nums = [];
  for (var i = 0; i < lines.length; i++) {
    var b = lines[i].block || 1;
    seen[b] = (seen[b] || 0) + 1;
    nums.push(seen[b]);
  }
  return nums;
}

function lineLabel(sh, num, block) {
  return (sh.content.blocks > 1 ? t("block") + " " + block + " · " : "") + t("line") + " " + num;
}

function check(sh) {
  var c = sh.content;
  var rows = [], exps = [], problems = [];
  var sold = {}, linesOf = {};
  var nLines = 0;
  var nums = lineNumbers(c.lines);
  var blocks = {};
  /* An approved sheet's sales are already deducted, so today's stock and catalogue no longer apply to it. */
  var recorded = sh.status === "approved";

  c.lines.forEach(function(l, i) {
    var row = { cls: "ok", msg: t("ok"), total: null };
    var product = S.productById[l.product_id];
    var qty = parseNum(l.qty), price = parseNum(l.price);
    if (!product && !recorded) row = { cls: "warn", msg: t("inactive") };
    else if (qty === null || qty === 0) row = { cls: "warn", msg: t("noQty") };
    else if (isNaN(qty)) row = { cls: "warn", msg: t("badNumber") };
    else if (price === null || price === 0) row = { cls: "warn", msg: t("noPrice") };
    else if (isNaN(price)) row = { cls: "warn", msg: t("badNumber") };
    if (product && !recorded && qty > 0 && !isNaN(qty)) {
      sold[l.product_id] = (sold[l.product_id] || 0) + qty;
      (linesOf[l.product_id] = linesOf[l.product_id] || []).push(i);
    }
    var marked = 0;
    if (row.cls === "ok") {
      row.total = cents(Math.round(qty * 1000) / 1000 * cents(price));
      if (l.pay === "card") marked = row.total;
      else if (l.pay === "split") {
        var part = parseNum(l.card);
        if (part === null || part === 0) row = { cls: "warn", msg: t("noCardPart"), total: row.total };
        else if (isNaN(part)) row = { cls: "warn", msg: t("badNumber"), total: row.total };
        else if (cents(part) > row.total + 1e-9) row = { cls: "warn", msg: t("cardPartTooBig"), total: row.total };
        else marked = cents(part);
      }
    }
    if (row.cls === "ok") {
      var b = blocks[l.block || 1] = blocks[l.block || 1] || { lines: 0, grand: 0, marked: 0 };
      b.lines++;
      b.grand += row.total;
      b.marked += marked;
      nLines++;
    }
    rows.push(row);
  });
  Object.keys(sold).forEach(function(id) {
    if (sold[id] > parseFloat(S.productById[id].stock) + 1e-9) {
      linesOf[id].forEach(function(i) { rows[i].cls = "bad"; rows[i].msg = t("noStock"); });
    }
  });
  rows.forEach(function(row, i) {
    if (row.cls !== "ok") {
      problems.push(lineLabel(sh, nums[i], c.lines[i].block || 1) + ": " + row.msg + " — " + c.lines[i].product);
    }
  });

  var drawer = 0, other = 0;
  c.expenses.forEach(function(e, i) {
    var row = { cls: "ok", msg: t("ok") };
    var amount = parseNum(e.amount);
    if (amount === null || amount === 0) row = { cls: "warn", msg: t("noAmount") };
    else if (isNaN(amount)) row = { cls: "warn", msg: t("badNumber") };
    else if (!e.paid_from) row = { cls: "warn", msg: t("noPaidFrom") };
    else if (e.category_id && !S.categoryById[e.category_id]) row = { cls: "warn", msg: t("badCategory") };
    if (row.cls === "ok") {
      if (e.paid_from === "drawer") drawer += cents(amount);
      else other += cents(amount);
    } else {
      problems.push(t("expense") + " " + (i + 1) + ": " + row.msg);
    }
    exps.push(row);
  });

  /* Tax per block, as each block is its own receipt (the server does the same). */
  var rate = parseFloat(S.catalog.tax_rate) || 0;
  var grand = 0, receipt = 0, cardMarked = 0, blockList = [];
  Object.keys(blocks).sort(function(a, b) { return a - b; }).forEach(function(n) {
    var b = blocks[n];
    b.grand = cents(b.grand);
    b.total = cents(b.grand + cents(b.grand * rate / 100));
    b.marked = Math.min(cents(b.marked), b.total);
    b.block = +n;
    grand += b.grand;
    receipt += b.total;
    cardMarked += b.marked;
    blockList.push(b);
  });
  grand = cents(grand);
  receipt = cents(receipt);
  var tax = cents(receipt - grand);
  var card = parseNum(c.card), counted = parseNum(c.counted), start = parseNum(c.start);
  card = card > 0 ? cents(card) : card;
  counted = counted > 0 ? cents(counted) : counted;
  if (c.lines.length && (card === null || isNaN(card))) problems.push(t("needCard"));
  if (card > receipt + 1e-9) problems.push(t("cardTooBig"));
  if (c.lines.length && (counted === null || isNaN(counted))) problems.push(t("needCounted"));
  if (!c.lines.length && !c.expenses.length) problems.push(t("emptySheet"));
  var cashSales = cents(receipt - (card > 0 ? card : 0));
  var accounted = counted === null || isNaN(counted) ? null :
    cents(counted + drawer - (start > 0 ? cents(start) : 0));
  return {
    rows: rows, exps: exps, problems: problems, lines: nLines, nums: nums, blocks: blockList,
    totals: {
      grand: grand, tax: tax, receipt: receipt, cashSales: cashSales, drawer: cents(drawer), other: cents(other),
      card: card > 0 ? card : 0, cardMarked: cents(cardMarked),
      accounted: accounted, difference: accounted === null ? null : cents(accounted - cashSales)
    }
  };
}

/* ── Saving to the server ──────────────────────────────────── */

function setSync(state) {
  var dot = $("syncDot");
  dot.className = "sync-dot" + (state === "ok" ? "" : " " + state);
  dot.title = t(state === "ok" ? "syncedAll" : state === "pending" ? "syncPending" : "syncOffline");
}

function refreshSyncDot() {
  var pending = S.sheets.some(function(s) { return s.dirty; });
  setSync(!pending ? "ok" : navigator.onLine ? "pending" : "offline");
}

function changed() {
  var sh = current();
  sh.dirty = true;
  sh.rev = (sh.rev || 0) + 1;
  persist();
  refreshSyncDot();
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(function() { syncSheet(sh.token); }, SAVE_DELAY);
}

function applyServer(sh, srv, rev) {
  sh.code = srv.code;
  sh.status = srv.status;
  sh.sheet_date = srv.sheet_date;
  sh.sent = !!srv.submitted_at;
  sh.return_note = srv.return_note;
  sh.returned_by_name = srv.returned_by_name;
  sh.receipt_ref = srv.receipt_ref;
  sh.receipt_refs = srv.receipt_refs || [];
  if (sh.rev === rev) sh.dirty = false;
}

/* The sheet is looked up again when the answer arrives: a refresh from the server may have
   replaced the object in the meantime. A save the server refuses (e.g. a number too large)
   is reported once and not retried until the sheet changes. */
function syncSheet(token) {
  var sh = sheetOf(token);
  if (!sh || !sh.dirty || !EDITABLE[sh.status] || sh.rejectedRev === sh.rev) return;
  if (!navigator.onLine) { refreshSyncDot(); return; }
  if (S.syncing[token]) { S.again[token] = true; return; }
  S.syncing[token] = true;
  var rev = sh.rev;
  apiPut("/daysheets/app/" + token, payload(sh)).then(function(srv) {
    var now = sheetOf(token);
    if (now) applyServer(now, srv, rev);
  }).catch(function(err) {
    if (err.status === 409) return reloadFromServer(token, "lockedElsewhere");
    if (err.status === 404) return dropSheet(token, "goneElsewhere");
    if (err.status === 400 || err.status === 422) {
      var now = sheetOf(token);
      if (now) now.rejectedRev = rev;
      alert(t("saveRefused") + err.message);
    }
  }).then(function() {
    S.syncing[token] = false;
    persist();
    refreshSyncDot();
    if (S.current === token) renderHeader();
    if (!S.current) renderHome();
    if (S.again[token]) {
      S.again[token] = false;
      syncSheet(token);
    }
  });
}

function syncAll() {
  S.sheets.forEach(function(sh) { if (sh.dirty) syncSheet(sh.token); });
  refreshSyncDot();
}

function reloadFromServer(token, message) {
  return apiGet("/daysheets/app/mine").then(function(list) {
    mergeServer(list, token);
    if (message) alert(t(message));
    if (S.current === token) renderSheet();
  });
}

function dropSheet(token, message) {
  S.sheets = S.sheets.filter(function(s) { return s.token !== token; });
  persist();
  if (message) alert(t(message));
  if (S.current === token) showHome();
}

/* The server's sheets, keeping this phone's unsent changes to sheets that can still change.
   force: a sheet whose local copy must give way to the server's (e.g. it was sent elsewhere). */
function mergeServer(list, force) {
  var local = {};
  S.sheets.forEach(function(s) { local[s.token] = s; });
  var merged = [];
  var seen = {};
  list.forEach(function(srv) {
    var mine = local[srv.token];
    seen[srv.token] = true;
    var keep = mine && mine.dirty && EDITABLE[srv.status] && srv.token !== force;
    merged.push(fromServer(srv, keep ? mine.content : null));
    if (keep) merged[merged.length - 1].rev = mine.rev;
  });
  var unsent = S.sheets.filter(function(s) { return !seen[s.token] && (!s.code || s.dirty); });
  S.sheets = unsent.concat(merged);
  persist();
}

function loadServer() {
  if (!navigator.onLine) return;
  apiGet("/daysheets/app/catalog").then(function(catalog) {
    localStorage.setItem(CATALOG_KEY, JSON.stringify(catalog));
    setCatalog(catalog);
    return apiGet("/daysheets/app/mine");
  }).then(function(list) {
    mergeServer(list);
    if (S.current && sheetOf(S.current)) renderSheet();
    else showHome();
    syncAll();
  }).catch(function() { refreshSyncDot(); });
}

/* ── Screens ───────────────────────────────────────────────── */

function applyLang() {
  document.documentElement.lang = S.lang;
  var labels = document.querySelectorAll("[data-t]");
  for (var i = 0; i < labels.length; i++) labels[i].textContent = t(labels[i].getAttribute("data-t"));
  $("productSearch").placeholder = t("search");
  var buttons = document.querySelectorAll(".lang-btn");
  for (var j = 0; j < buttons.length; j++) {
    buttons[j].className = "lang-btn" + (buttons[j].getAttribute("data-lang") === S.lang ? " active" : "");
  }
}

function setLang(lang) {
  S.lang = lang;
  localStorage.setItem(LANG_KEY, lang);
  applyLang();
  if (!S.user) return;
  if (S.current) renderSheet();
  else renderHome();
  refreshSyncDot();
}

function badge(status) {
  return "<span class='badge badge-" + status + "'>" + esc(t("status_" + status)) + "</span>";
}

function showHome() {
  S.current = null;
  S.pick = null;
  $("sheetView").className = "hidden";
  $("homeView").className = "";
  $("backBtn").className = "bar-btn hidden";
  $("barTitle").textContent = "KEYPOS Sheet";
  renderHome();
}

function renderHome() {
  if (S.current) return;
  var list = $("sheetList");
  if (!S.sheets.length) {
    list.innerHTML = "<div class='empty'>" + esc(t("noSheets")) + "</div>";
    return;
  }
  list.innerHTML = S.sheets.map(function(sh) {
    var r = check(sh);
    var deletable = sh.status === "draft" && !sh.sent;
    var refs = sh.receipt_refs && sh.receipt_refs.length ? sh.receipt_refs : sh.receipt_ref ? [sh.receipt_ref] : [];
    return "<div class='card sheet-card' data-open='" + esc(sh.token) + "'><div class='info'>" +
      "<div class='code'>" + esc(sh.code || t("notSynced")) + " " + badge(sh.status) + "</div>" +
      "<div class='sub'>" + showDate(sh.sheet_date) + " · " + sh.content.lines.length + " " + esc(t("lines")) +
      (sh.content.blocks > 1 ? " · " + esc(t("blocksN", { n: sh.content.blocks })) : "") +
      " · " + money(r.totals.receipt) +
      (refs.length ? " · " + esc(refs[0]) + (refs.length > 1 ? " +" + (refs.length - 1) : "") : "") + "</div></div>" +
      (deletable ? "<button class='row-del' data-discard='" + esc(sh.token) + "' aria-label='Delete'>&times;</button>" : "") +
      "</div>";
  }).join("");
}

function openSheet(token) {
  S.current = token;
  S.tab = "sales";
  S.block = 1;
  S.pick = null;
  $("homeView").className = "hidden";
  $("sheetView").className = "";
  $("backBtn").className = "bar-btn";
  if (window.history && history.pushState) history.pushState({ sheet: token }, "");
  renderSheet();
}

function readOnly(sh) {
  return !EDITABLE[sh.status];
}

function renderHeader() {
  var sh = current();
  if (!sh) return;
  $("barTitle").textContent = sh.code || t("notSynced");
  var banner;
  if (sh.status === "submitted") banner = ["banner-info", t("bannerSubmitted")];
  else if (sh.status === "approved") banner = ["banner-good", approvedText(sh)];
  else if (sh.status === "returned") banner = ["banner-bad", t("bannerReturned", { who: sh.returned_by_name || "", note: sh.return_note || "" })];
  else banner = ["banner-warn", t("bannerDraft")];
  $("sheetBanner").innerHTML = "<div class='banner " + banner[0] + "'>" + esc(banner[1]) + "</div>";
}

function approvedText(sh) {
  var refs = sh.receipt_refs && sh.receipt_refs.length ? sh.receipt_refs : sh.receipt_ref ? [sh.receipt_ref] : [];
  if (refs.length > 1) return t("bannerApprovedMany", { refs: refs.join(", ") });
  return refs.length ? t("bannerApproved", { ref: refs[0] }) : t("bannerApprovedNoSales");
}

function renderSheet() {
  var sh = current();
  if (!sh) { showHome(); return; }
  if (S.block > sh.content.blocks) S.block = sh.content.blocks;
  var locked = readOnly(sh);
  $("sheetView").className = locked ? "readonly" : "";
  $("productSearch").parentNode.style.display = locked ? "none" : "";
  $("addExpenseBtn").style.display = locked ? "none" : "";
  $("sendBtn").style.display = locked ? "none" : "";
  $("discardBtn").className = "btn btn-danger-outline btn-wide" + (sh.status === "draft" && !sh.sent ? "" : " hidden");
  renderHeader();
  renderLines();
  renderPick();
  renderExpenses();
  renderSummary();
  showTab(S.tab);
  updateFlags();
}

function showTab(tab) {
  S.tab = tab;
  ["sales", "expenses", "summary"].forEach(function(name) {
    $("tab-" + name).className = "tab-body" + (name === tab ? "" : " hidden");
  });
  var tabs = document.querySelectorAll(".tab");
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].className = "tab" + (tabs[i].getAttribute("data-tab") === tab ? " active" : "");
  }
  hideResults();
}

function linesIn(sh, block) {
  var n = 0;
  sh.content.lines.forEach(function(l) { if ((l.block || 1) === block) n++; });
  return n;
}

/* Where a new line of `block` goes: after the block's last line (lines are kept in block order). */
function endOfBlock(sh, block) {
  var at = 0;
  sh.content.lines.forEach(function(l, i) { if ((l.block || 1) <= block) at = i + 1; });
  return at;
}

function renderBlocks() {
  var sh = current();
  var c = sh.content;
  var locked = readOnly(sh);
  var bar = $("blockBar");
  if (locked && c.blocks === 1) { bar.innerHTML = ""; bar.className = "block-bar hidden"; return; }
  var counts = {};
  c.lines.forEach(function(l) { counts[l.block || 1] = (counts[l.block || 1] || 0) + 1; });
  var html = "";
  for (var b = 1; b <= c.blocks; b++) {
    html += "<span class='block-chip" + (b === S.block ? " on" : "") + "'><button data-block='" + b + "'>" +
      esc(t("block")) + " " + b + " <span class='tab-count'>(" + (counts[b] || 0) + ")</span></button>" +
      (!locked && c.blocks > 1 && !counts[b] ? "<button class='block-del' data-del-block='" + b + "' aria-label='" +
        esc(t("removeBlock")) + "'>&times;</button>" : "") + "</span>";
  }
  if (!locked && c.blocks < MAX_BLOCKS) html += "<button class='block-new' data-new-block='1'>" + esc(t("newBlock")) + "</button>";
  bar.innerHTML = html;
  bar.className = "block-bar";
}

function payButton(i, pay, value) {
  var key = value === "cash" ? "payCash" : value === "card" ? "payCard" : "paySplit";
  return "<button data-pay='" + i + "' data-v='" + value + "' class='" + (pay === value ? "on" : "") + "'>" + esc(t(key)) + "</button>";
}

/* The block on screen only, newest line first, so the line just added sits under the search box.
   Element ids use the line's place in the whole list; the number shown is its place in its block. */
function renderLines() {
  var sh = current();
  var nums = lineNumbers(sh.content.lines);
  var html = [];
  for (var i = sh.content.lines.length - 1; i >= 0; i--) {
    var l = sh.content.lines[i];
    if ((l.block || 1) !== S.block) continue;
    var pay = l.pay || "cash";
    html.push(
      "<div class='row' id='line-" + i + "'><div class='row-head'><span class='row-num'>#" + nums[i] + "</span>" +
      "<span class='row-name' role='button' data-change-line='" + i + "' title='" + esc(t("changeProduct")) + "'>" + esc(l.product) + "</span>" +
      "<button class='row-ins' data-ins-line='" + i + "' aria-label='" + esc(t("insertHere")) + "'>&#65291;</button>" +
      "<button class='row-del' data-del-line='" + i + "' aria-label='Remove'>&times;</button></div>" +
      "<div class='row-fields'>" +
      "<div class='field field-qty'><label>" + esc(t("qty")) + "</label><input inputmode='decimal' data-line='" + i + "' data-f='qty' value='" + esc(l.qty) + "'></div>" +
      "<div class='field field-price'><label>" + esc(t("price")) + "</label><input inputmode='decimal' data-line='" + i + "' data-f='price' value='" + esc(l.price) + "'></div>" +
      "<div class='row-total' id='line-total-" + i + "'></div>" +
      "<div class='field field-wide'><div class='choice choice-pay'>" +
      payButton(i, pay, "cash") + payButton(i, pay, "card") + payButton(i, pay, "split") + "</div></div>" +
      (pay === "split" ? "<div class='field field-price'><label>" + esc(t("cardPart")) + "</label><input inputmode='decimal' data-line='" +
        i + "' data-f='card' value='" + esc(l.card) + "'></div>" : "") +
      "</div><div class='row-status' id='line-status-" + i + "'></div></div>"
    );
  }
  $("lines").innerHTML = html.join("");
}

function categoryOptions(selected) {
  var html = "<option value=''>" + esc(t("noCategory")) + "</option>";
  S.catalog.categories.forEach(function(c) {
    html += "<option value='" + c.id + "'" + (c.id === selected ? " selected" : "") + ">" + esc(c.name) + "</option>";
  });
  return html;
}

function renderExpenses() {
  var sh = current();
  var html = [];
  for (var i = sh.content.expenses.length - 1; i >= 0; i--) {
    var e = sh.content.expenses[i];
    html.push(
      "<div class='row' id='exp-" + i + "'><div class='row-head'><span class='row-num'>#" + (i + 1) + "</span>" +
      "<span class='row-name'></span><button class='row-del' data-del-exp='" + i + "' aria-label='Remove'>&times;</button></div>" +
      "<div class='row-fields'>" +
      "<div class='field field-amount'><label>" + esc(t("amount")) + "</label><input inputmode='decimal' data-exp='" + i + "' data-f='amount' value='" + esc(e.amount) + "'></div>" +
      "<div class='field field-grow'><label>" + esc(t("category")) + "</label><select data-exp='" + i + "' data-f='category_id'>" + categoryOptions(e.category_id) + "</select></div>" +
      "<div class='field field-wide'><label>" + esc(t("description")) + "</label><input maxlength='500' data-exp='" + i + "' data-f='description' value='" + esc(e.description) + "'></div>" +
      "<div class='field field-wide'><label>" + esc(t("paidFrom")) + "</label><div class='choice'>" +
      "<button data-paid='" + i + "' data-v='drawer' class='" + (e.paid_from === "drawer" ? "on" : "") + "'>" + esc(t("drawer")) + "</button>" +
      "<button data-paid='" + i + "' data-v='other' class='" + (e.paid_from === "other" ? "on" : "") + "'>" + esc(t("other")) + "</button>" +
      "</div></div></div><div class='row-status' id='exp-status-" + i + "'></div></div>"
    );
  }
  $("expenseRows").innerHTML = html.join("");
}

function sumRow(label, id, strong) {
  return "<div class='sum-row" + (strong ? " sum-strong" : "") + "'><span class='label'>" + esc(t(label)) +
    "</span><span class='value' id='" + id + "'></span></div>";
}

function sumInput(label, field) {
  return "<div class='sum-row'><span class='label'>" + esc(t(label)) + "</span><input inputmode='decimal' data-sum='" +
    field + "' value='" + esc(current().content[field]) + "'></div>";
}

function renderSummary() {
  $("summaryForm").innerHTML =
    "<div class='sum-head'>" + esc(t("secSales")) + "</div>" +
    sumRow("grandTotal", "sumGrand") +
    "<div id='sumTaxRows'>" + sumRow("tax", "sumTax") + sumRow("receiptTotal", "sumReceipt", true) + "</div>" +
    sumInput("card", "card") +
    sumRow("cashSales", "sumCash", true) +
    "<div id='sumMarked'>" + sumRow("cardMarked", "sumCardMarked") + "<div id='sumMarkedOver' class='note-warn'></div></div>" +
    "<div id='sumBlocks'></div>" +
    "<div class='sum-head'>" + esc(t("secCash")) + "</div>" +
    sumInput("counted", "counted") +
    sumRow("drawerExp", "sumDrawer") +
    sumInput("start", "start") +
    sumRow("accounted", "sumAccounted", true) +
    "<div id='sumDifference' class='difference even'></div>" +
    sumRow("otherExp", "sumOther");
}

/* Statuses, totals and counts after any change, without redrawing what is being typed in. */
function updateFlags() {
  var sh = current();
  if (!sh) return;
  var r = check(sh);
  r.rows.forEach(function(row, i) {
    if (!$("line-" + i)) return;
    $("line-" + i).className = "row " + row.cls;
    $("line-status-" + i).textContent = row.msg;
    $("line-total-" + i).textContent = row.total === null ? "" : money(row.total);
  });
  r.exps.forEach(function(row, i) {
    $("exp-" + i).className = "row " + row.cls;
    $("exp-status-" + i).textContent = row.msg;
  });
  var tt = r.totals;
  $("sumGrand").textContent = money(tt.grand);
  $("sumTaxRows").style.display = tt.tax ? "" : "none";
  $("sumTax").textContent = money(tt.tax);
  $("sumReceipt").textContent = money(tt.receipt);
  $("sumCash").textContent = money(tt.cashSales);
  $("sumDrawer").textContent = money(tt.drawer);
  $("sumAccounted").textContent = tt.accounted === null ? "—" : money(tt.accounted);
  $("sumOther").textContent = money(tt.other);
  $("sumMarked").style.display = tt.cardMarked ? "" : "none";
  $("sumCardMarked").textContent = money(tt.cardMarked);
  $("sumMarkedOver").textContent = tt.cardMarked > tt.card + 1e-9 ? t("cardMarkedOver") : "";
  $("sumBlocks").innerHTML = sh.content.blocks > 1 && r.blocks.length ?
    "<div class='sum-head'>" + esc(t("secBlocks")) + "</div>" + r.blocks.map(function(b) {
      return "<div class='sum-row'><span class='label'>" + esc(t("blockLine", { n: b.block, lines: b.lines })) +
        "</span><span class='value'>" + money(b.total) + "</span></div>";
    }).join("") : "";
  renderBlocks();
  var diff = $("sumDifference");
  if (tt.difference === null) {
    diff.className = "difference even";
    diff.textContent = t("difference") + ": —";
  } else {
    var kind = tt.difference > 0 ? "extra" : tt.difference < 0 ? "short" : "even";
    diff.className = "difference " + kind;
    diff.textContent = t("difference") + " " + signed(tt.difference) + " · " + t(kind);
  }
  $("salesCount").textContent = sh.content.lines.length ? "(" + sh.content.lines.length + ")" : "";
  $("expenseCount").textContent = sh.content.expenses.length ? "(" + sh.content.expenses.length + ")" : "";
  $("problemCount").textContent = !readOnly(sh) && r.problems.length ? "(" + r.problems.length + ")" : "";
  $("problemList").innerHTML = readOnly(sh) || !r.problems.length ? "" :
    "<div class='problems'><b>" + esc(t("fixFirst")) + "</b><ul>" +
    r.problems.map(function(p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div>";
  $("sendBtn").disabled = r.problems.length > 0;
  return r;
}

/* ── Product search: narrows on every letter, any part of the name, words in any order ── */

function hideResults() {
  $("searchResults").className = "results hidden";
}

function searchProducts(query) {
  var words = fold(query).split(/\s+/).filter(function(w) { return w; });
  if (!words.length) return [];
  var found = [];
  for (var i = 0; i < S.catalog.products.length && found.length < SEARCH_LIMIT; i++) {
    var p = S.catalog.products[i];
    var name = fold(p.name);
    var all = true;
    for (var j = 0; j < words.length; j++) {
      if (name.indexOf(words[j]) === -1) { all = false; break; }
    }
    if (all) found.push(p);
  }
  return found;
}

function renderResults() {
  var query = $("productSearch").value;
  var box = $("searchResults");
  if (!query.trim()) { hideResults(); return; }
  var found = searchProducts(query);
  box.innerHTML = found.length ? found.map(function(p) {
    var out = parseFloat(p.stock) <= 0;
    return "<button class='result' data-product='" + p.id + "'>" + esc(p.name) +
      (out ? " <b style='color:#C62828;'>· " + esc(t("noStock")) + "</b>" : "") + "</button>";
  }).join("") : "<div class='result-none'>" + esc(t("noMatch")) + "</div>";
  box.className = "results";
}

/* The next product picked either goes after line `index` ("insert") or replaces the product
   on line `index` ("change"); with no pick it is added at the end. */
function startPick(mode, index) {
  var sh = current();
  if (!sh || readOnly(sh) || !sh.content.lines[index]) return;
  S.pick = { mode: mode, index: index };
  $("productSearch").value = "";
  hideResults();
  renderPick();
  window.scrollTo(0, 0);
  $("productSearch").focus();
}

function cancelPick() {
  S.pick = null;
  renderPick();
}

function renderPick() {
  var sh = current();
  if (S.pick && (!sh || readOnly(sh) || !sh.content.lines[S.pick.index])) S.pick = null;
  var marked = document.querySelectorAll("[data-picking]");
  for (var i = 0; i < marked.length; i++) marked[i].removeAttribute("data-picking");
  if (!S.pick) { $("pickHint").className = "pick-hint hidden"; return; }
  $("pickText").textContent = t(S.pick.mode === "insert" ? "insertAfter" : "changeLine", { n: lineNumbers(sh.content.lines)[S.pick.index] });
  $("pickCancel").textContent = t("cancel");
  $("pickHint").className = "pick-hint";
  var row = $("line-" + S.pick.index);
  if (row) row.setAttribute("data-picking", S.pick.mode);
}

/* A changed line keeps its qty and a typed price; an empty price takes the product's fixed price. */
function addLine(productId) {
  var p = S.productById[productId];
  var sh = current();
  if (!p || !sh || readOnly(sh)) return;
  var fixed = parseFloat(p.price) || 0;
  var price = fixed > 0 ? String(fixed) : "";
  var pick = S.pick;
  var at, line;
  if (pick && pick.mode === "change") {
    at = pick.index;
    line = sh.content.lines[at];
    line.product_id = p.id;
    line.product = p.name;
    if (!String(line.price || "").trim()) line.price = price;
  } else {
    var block = pick ? sh.content.lines[pick.index].block || 1 : S.block;
    if (linesIn(sh, block) >= MAX_BLOCK_LINES) { alert(t("blockFull", { n: block })); return; }
    at = pick ? pick.index + 1 : endOfBlock(sh, block);
    line = { product_id: p.id, product: p.name, qty: "1", price: price, block: block, pay: "cash", card: "" };
    sh.content.lines.splice(at, 0, line);
  }
  S.pick = null;
  $("productSearch").value = "";
  hideResults();
  renderLines();
  renderPick();
  updateFlags();
  changed();
  if (!line.price) {
    var input = document.querySelector("[data-line='" + at + "'][data-f='price']");
    if (input) input.focus();
  } else if (pick && $("line-" + at).scrollIntoView) {
    $("line-" + at).scrollIntoView(false);
  }
}

/* ── Actions ───────────────────────────────────────────────── */

function showBlock(block) {
  S.block = block;
  S.pick = null;
  $("productSearch").value = "";
  hideResults();
  renderLines();
  renderPick();
  updateFlags();
}

function addBlock() {
  var sh = current();
  if (!sh || readOnly(sh)) return;
  if (sh.content.blocks >= MAX_BLOCKS) { alert(t("maxBlocks")); return; }
  sh.content.blocks++;
  changed();
  showBlock(sh.content.blocks);
}

/* Only an empty block can go; the blocks after it move down one number. */
function removeBlock(block) {
  var sh = current();
  if (!sh || readOnly(sh) || sh.content.blocks < 2 || linesIn(sh, block)) return;
  sh.content.lines.forEach(function(l) { if ((l.block || 1) > block) l.block = (l.block || 1) - 1; });
  sh.content.blocks--;
  changed();
  showBlock(S.block > block ? S.block - 1 : Math.min(S.block, sh.content.blocks));
}

function setPay(index, pay) {
  var sh = current();
  var line = sh && sh.content.lines[index];
  if (!line || readOnly(sh) || line.pay === pay) return;
  line.pay = pay;
  renderLines();
  renderPick();
  updateFlags();
  changed();
  if (pay === "split") {
    var input = document.querySelector("[data-line='" + index + "'][data-f='card']");
    if (input) input.focus();
  }
}

function newSheet() {
  var sh = {
    token: newToken(), code: null, status: "draft", sheet_date: today(), content: emptyContent(),
    dirty: true, rev: 1, sent: false
  };
  S.sheets.unshift(sh);
  persist();
  openSheet(sh.token);
  syncSheet(sh.token);
}

function sendSheet() {
  var sh = current();
  var r = updateFlags();
  if (r.problems.length) { showTab("summary"); return; }
  if (!navigator.onLine) { alert(t("needOnline")); return; }
  var question = r.blocks.length > 1 ?
    t("confirmSendBlocks", { code: sh.code || "", n: r.lines, b: r.blocks.length, total: money(r.totals.receipt) }) :
    t("confirmSend", { code: sh.code || "", n: r.lines, total: money(r.totals.receipt) });
  if (!confirm(question)) return;
  var btn = $("sendBtn");
  btn.disabled = true;
  clearTimeout(S.saveTimer);
  var rev = sh.rev;
  var token = sh.token;
  apiPost("/daysheets/app/" + token + "/submit", payload(sh)).then(function(srv) {
    sh = sheetOf(token) || sh;
    applyServer(sh, srv, rev);
    persist();
    refreshSyncDot();
    renderSheet();
    alert(t("sent"));
  }).catch(function(err) {
    btn.disabled = false;
    if (err.status === 409) { reloadFromServer(token, "lockedElsewhere"); return; }
    alert(err.network ? t("needOnline") : t("sendFailed") + err.message);
  });
}

function discardSheet(token) {
  var sh = sheetOf(token);
  if (!sh || !confirm(t("confirmDiscard"))) return;
  if (!sh.code) { dropSheet(token); renderHome(); return; }
  if (!navigator.onLine) { alert(t("needOnline")); return; }
  apiDelete("/daysheets/app/" + token).then(function() {
    dropSheet(token);
    showHome();
  }).catch(function(err) {
    if (err.status === 404) { dropSheet(token); showHome(); return; }
    alert(t("deleteFailed") + err.message);
  });
}

/* ── Wiring ────────────────────────────────────────────────── */

function bindEvents() {
  $("newSheetBtn").addEventListener("click", newSheet);
  $("sheetList").addEventListener("click", function(e) {
    var del = e.target.getAttribute("data-discard");
    if (del) { e.stopPropagation(); discardSheet(del); return; }
    var card = e.target;
    while (card && card !== this && !card.getAttribute("data-open")) card = card.parentNode;
    if (card && card !== this) openSheet(card.getAttribute("data-open"));
  });
  $("backBtn").addEventListener("click", function() {
    if (window.history && history.state && history.state.sheet) history.back();
    else showHome();
  });
  window.addEventListener("popstate", function() { if (S.current) showHome(); });

  var tabs = document.querySelectorAll(".tab");
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].addEventListener("click", function() { S.pick = null; showTab(this.getAttribute("data-tab")); renderPick(); });
  }

  $("productSearch").addEventListener("input", renderResults);
  $("searchResults").addEventListener("click", function(e) {
    var btn = e.target;
    while (btn && btn !== this && !btn.getAttribute("data-product")) btn = btn.parentNode;
    if (btn && btn !== this) addLine(parseInt(btn.getAttribute("data-product"), 10));
  });
  document.addEventListener("click", function(e) {
    var box = document.querySelector(".search-box");
    if (box && !box.contains(e.target)) hideResults();
  });

  $("lines").addEventListener("input", function(e) {
    var i = e.target.getAttribute("data-line");
    if (i === null) return;
    current().content.lines[+i][e.target.getAttribute("data-f")] = e.target.value;
    updateFlags();
    changed();
  });
  $("lines").addEventListener("click", function(e) {
    var payOf = e.target.getAttribute("data-pay");
    if (payOf !== null) { setPay(+payOf, e.target.getAttribute("data-v")); return; }
    var ins = e.target.getAttribute("data-ins-line");
    if (ins !== null) { startPick("insert", +ins); return; }
    var change = e.target.getAttribute("data-change-line");
    if (change !== null) { startPick("change", +change); return; }
    var i = e.target.getAttribute("data-del-line");
    if (i === null || readOnly(current())) return;
    S.pick = null;
    current().content.lines.splice(+i, 1);
    renderLines();
    renderPick();
    updateFlags();
    changed();
  });
  $("pickCancel").addEventListener("click", cancelPick);
  $("blockBar").addEventListener("click", function(e) {
    var btn = e.target;
    while (btn && btn !== this && !btn.getAttribute("data-block") && !btn.getAttribute("data-del-block") &&
      !btn.getAttribute("data-new-block")) btn = btn.parentNode;
    if (!btn || btn === this) return;
    if (btn.getAttribute("data-new-block")) addBlock();
    else if (btn.getAttribute("data-del-block")) removeBlock(+btn.getAttribute("data-del-block"));
    else showBlock(+btn.getAttribute("data-block"));
  });

  $("addExpenseBtn").addEventListener("click", function() {
    current().content.expenses.push({ category_id: null, amount: "", description: "", paid_from: null });
    renderExpenses();
    updateFlags();
    changed();
  });
  function expenseField(e) {
    var i = e.target.getAttribute("data-exp");
    if (i === null) return;
    var field = e.target.getAttribute("data-f");
    var value = e.target.value;
    current().content.expenses[+i][field] = field === "category_id" ? (value ? parseInt(value, 10) : null) : value;
    updateFlags();
    changed();
  }
  $("expenseRows").addEventListener("input", expenseField);
  $("expenseRows").addEventListener("change", expenseField);
  $("expenseRows").addEventListener("click", function(e) {
    var del = e.target.getAttribute("data-del-exp");
    if (del !== null) {
      current().content.expenses.splice(+del, 1);
      renderExpenses();
      updateFlags();
      changed();
      return;
    }
    var paid = e.target.getAttribute("data-paid");
    if (paid === null) return;
    current().content.expenses[+paid].paid_from = e.target.getAttribute("data-v");
    var pair = e.target.parentNode.children;
    for (var j = 0; j < pair.length; j++) pair[j].className = pair[j] === e.target ? "on" : "";
    updateFlags();
    changed();
  });

  $("summaryForm").addEventListener("input", function(e) {
    var field = e.target.getAttribute("data-sum");
    if (!field) return;
    current().content[field] = e.target.value;
    updateFlags();
    changed();
  });
  $("sendBtn").addEventListener("click", sendSheet);
  $("discardBtn").addEventListener("click", function() { discardSheet(S.current); });

  $("menuBtn").addEventListener("click", function(e) {
    e.stopPropagation();
    $("menu").className = $("menu").className.indexOf("hidden") === -1 ? "menu hidden" : "menu";
  });
  document.addEventListener("click", function(e) {
    if (!$("menu").contains(e.target)) $("menu").className = "menu hidden";
  });
  $("logoutBtn").addEventListener("click", function() { signOut(); });

  var langs = document.querySelectorAll(".lang-btn");
  for (var k = 0; k < langs.length; k++) {
    langs[k].addEventListener("click", function() { setLang(this.getAttribute("data-lang")); });
  }

  window.addEventListener("online", function() { loadServer(); });
  window.addEventListener("offline", refreshSyncDot);
  setInterval(function() { if (navigator.onLine) syncAll(); }, 30000);
  setInterval(loadServer, 5 * 60000);
}

function bindLogin() {
  $("loginForm").addEventListener("submit", function(e) {
    e.preventDefault();
    var error = $("loginError");
    var btn = $("loginBtn");
    error.className = "error";
    btn.disabled = true;
    btn.textContent = t("signingIn");
    fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("loginUser").value.trim(), password: $("loginPass").value })
    }).then(function(r) {
      return r.json().catch(function() { return {}; }).then(function(d) { return { status: r.status, data: d }; });
    }).then(function(res) {
      if (res.status === 429) throw new Error(t("tooMany"));
      if (res.status !== 200) throw new Error(t("badLogin"));
      saveSession(res.data);
      $("loginPass").value = "";
      startApp();
    }).catch(function(err) {
      error.textContent = err instanceof TypeError ? t("noServer") : err.message;
      error.className = "error visible";
    }).then(function() {
      btn.disabled = false;
      btn.textContent = t("signIn");
    });
  });
}

function startApp() {
  S.user = getUser();
  $("loginView").className = "view hidden";
  $("appView").className = "view";
  $("menuUser").textContent = S.user.name || S.user.username || "";
  $("barSub").textContent = S.user.name || "";
  var staff = !(S.user.permissions && S.user.permissions.sheet_only);
  $("posLink").className = "menu-item" + (staff ? "" : " hidden");
  loadLocal();
  showHome();
  refreshSyncDot();
  loadServer();
}

/* A phone that is offline may keep using an expired login; it signs in again once online. */
function signedIn() {
  return !!getToken() && (!sessionExpired() || !navigator.onLine);
}

applyLang();
bindLogin();
bindEvents();
if (signedIn()) startApp();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sheet/sw.js", { scope: "/sheet/" }).catch(function() {});
}
