/* KEYPOS — shared state, DOM references and helpers. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── App State ── */
var POS_STATE = {
  token: "",
  user: null,
  shift: null,
  products: [],
  categories: [],
  units: [],
  cart: [],
  selectedCategoryId: 0,
  searchQuery: "",
  taxRate: 0.00,
  cartDiscountPct: 0,
  reissueOfId: null,
  offlineMode: false
};

/* ── DOM References (populated in init) ── */
var DOM = {
  cashierName: null,
  shiftStatus: null,
  logoutBtn: null,
  searchBox: null,
  catBar: null,
  productGrid: null,
  orderList: null,
  orderCount: null,
  cartBadge: null,
  subtotalEl: null,
  taxEl: null,
  grandTotalEl: null,
  discountEl: null,
  chargeBtn: null,
  holdBtn: null,
  voidBtn: null,
  discBtn: null,
  shiftModal: null,
  floatInput: null,
  openShiftBtn: null
};

/* ── Helpers ── */
function safeAddListener(id, handler) {
  var el = document.getElementById(id);
  if (el) { el.addEventListener("click", handler); }
}

function escapeHtml(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* "YYYY-MM-DD" in the device's own time zone (toISOString would give the UTC date). */
function localDateStr(d) {
  var date = d || new Date();
  var mm = date.getMonth() + 1;
  var dd = date.getDate();
  return date.getFullYear() + "-" + (mm < 10 ? "0" : "") + mm + "-" + (dd < 10 ? "0" : "") + dd;
}

/* Server timestamps are UTC; show them as "2026-10-08 11:06" in the device's time zone. */
function localDateTime(value) {
  if (!value) return "";
  var d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  var hh = d.getHours();
  var mi = d.getMinutes();
  return localDateStr(d) + " " + (hh < 10 ? "0" : "") + hh + ":" + (mi < 10 ? "0" : "") + mi;
}

function monthStartStr() {
  var now = new Date();
  return localDateStr(new Date(now.getFullYear(), now.getMonth(), 1));
}

/* "Kz6,500.00": thousands grouped, sign before the symbol. */
function money(value) {
  var amount = Math.round((parseFloat(value) || 0) * 100) / 100;
  var digits = Math.abs(amount).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (amount < 0 ? "-" : "") + (STORE_SETTINGS.currency_symbol || "$") + digits;
}

/* Rounds tax to the cent the same way the server does (ROUND_HALF_UP). */
function posCalcTax(taxable) {
  return Math.round(taxable * POS_STATE.taxRate * 100 + 1e-6) / 100;
}

function roundCents(value) {
  return Math.round(value * 100 + 1e-6) / 100;
}

function posLineGross(item) {
  return roundCents(item.price * item.qty);
}

/* A line discount can never exceed the line amount (e.g. after lowering the quantity). */
function posLineDiscount(item) {
  return Math.min(parseFloat(item.discount) || 0, posLineGross(item));
}

/* Mirrors compute_totals in backend/services/sales.py: line discounts, then the cart discount %, then tax. */
function posCartTotals() {
  var subtotal = 0;
  var lineDiscounts = 0;
  for (var i = 0; i < POS_STATE.cart.length; i++) {
    subtotal += posLineGross(POS_STATE.cart[i]);
    lineDiscounts += posLineDiscount(POS_STATE.cart[i]);
  }
  subtotal = roundCents(subtotal);
  lineDiscounts = roundCents(lineDiscounts);
  var cartDiscount = roundCents((subtotal - lineDiscounts) * POS_STATE.cartDiscountPct);
  var discount = roundCents(lineDiscounts + cartDiscount);
  var tax = posCalcTax(subtotal - discount);
  return {
    subtotal: subtotal,
    cartDiscount: cartDiscount,
    discount: discount,
    tax: tax,
    total: roundCents(subtotal - discount + tax)
  };
}

function posCartLines() {
  return POS_STATE.cart.map(function(item) {
    return { product_id: item.product_id, qty: item.qty, sell_price: item.price, discount: posLineDiscount(item) };
  });
}

function posResetCart() {
  POS_STATE.cart = [];
  POS_STATE.cartDiscountPct = 0;
  POS_STATE.reissueOfId = null;
  DB.saveCart([], function() {});
  posRenderCart();
}

/* ── Auth Check ── */
/* An offline till keeps working on an expired login; the server accepts its queued sales for 7 days. */
function posAuthCheck() {
  POS_STATE.token = getToken();
  if (!POS_STATE.token || (sessionExpired() && navigator.onLine)) {
    signOut();
    return false;
  }
  POS_STATE.user = getUser();
  if (isSheetOnly(POS_STATE.user)) {
    window.location.replace("/sheet/");
    return false;
  }
  return true;
}
