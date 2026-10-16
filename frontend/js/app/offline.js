/* KEYPOS — offline sales and the sync badge. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Offline mode ── */

function posCacheShift(shift) {
  try { localStorage.setItem("pos_shift_cache", JSON.stringify(shift)); } catch (e) {}
}

function posClearShiftCache() {
  try { localStorage.removeItem("pos_shift_cache"); } catch (e) {}
}

function posReadCachedShift() {
  try { return JSON.parse(localStorage.getItem("pos_shift_cache") || "null"); } catch (e) { return null; }
}

/* A sale may proceed when a shift is open, or when the device is offline and the
   till runs from cache (the server books queued sales to the shift open at sync). */
function posShiftOk() {
  return !!POS_STATE.shift || !!POS_STATE.offlineMode;
}

/* Keeps the device's stock count truthful as offline sales are queued, so the
   till cannot sell 11 of an item that only has 9 in the cache. */
function posDeductLocalStock(cart) {
  for (var i = 0; i < cart.length; i++) {
    for (var j = 0; j < POS_STATE.products.length; j++) {
      if (POS_STATE.products[j].id === cart[i].product_id) {
        var cur = parseFloat(POS_STATE.products[j].stock_qty) || 0;
        POS_STATE.products[j].stock_qty = Math.round((cur - cart[i].qty) * 1000) / 1000;
        break;
      }
    }
  }
}

function posApplyLocalStock(id, newQty) {
  for (var i = 0; i < POS_STATE.products.length; i++) {
    if (POS_STATE.products[i].id === id) {
      POS_STATE.products[i].stock_qty = newQty;
      break;
    }
  }
  posCacheProducts();
}

function posQueueOfflineSale(payload, method, cashTendered, totals) {
  var full = {};
  for (var key in payload) {
    if (payload.hasOwnProperty(key)) full[key] = payload[key];
  }
  full.cashier_id = POS_STATE.user && POS_STATE.user.id;
  SYNC.queueAction("sale", full, function(err) {
    if (err) {
      alert("OFFLINE and the sale could not be saved on this device.\nThe cart has been kept — retry when the connection returns.");
      return;
    }
    posDeductLocalStock(POS_STATE.cart);
    posCacheProducts();
    posResetCart();
    closePanel("paymentPanel");
    var msg = "OFFLINE SALE — saved on this device\nTotal: " + money(totals.total) +
      "\nIt will sync automatically when the connection returns.";
    if (method === "cash") {
      msg += "\nCash: " + money(cashTendered) + "\nChange: " + money(cashTendered - totals.total);
    } else if (method === "split") {
      msg += "\nCash: " + money(payload.payment_cash) + "\nCard: " + money(payload.payment_card);
    } else if (method === "card") {
      msg += "\nCard payment";
    } else if (method === "account") {
      msg += "\nAccount sale - charged to customer";
    }
    alert(msg);
  }, payload.client_ref);
}

/* ── Connection / sync badge ── */
var SYNC_BADGE_STATE = { pending: 0, dead: 0 };

function posBindSyncBadge() {
  SYNC.onStatusUpdate(function(s) {
    var hadPending = SYNC_BADGE_STATE.pending;
    posRenderSyncBadge(s);
    /* The queue just drained while online: pull the server's stock truth back in. */
    if (hadPending > 0 && s.pending === 0 && s.online) posRefreshStock();
  });
  safeAddListener("syncStatus", function() {
    if (SYNC_BADGE_STATE.dead > 0) {
      alert(SYNC_BADGE_STATE.dead + " offline item(s) could not be synced after several attempts.\n" +
        "They are still stored safely on this device — ask the manager to review them.");
      return;
    }
    if (SYNC_BADGE_STATE.pending > 0) SYNC.syncNow(null);
  });
}

function posRenderSyncBadge(s) {
  SYNC_BADGE_STATE.pending = s.pending;
  SYNC_BADGE_STATE.dead = s.dead;
  var el = document.getElementById("syncStatus");
  if (!el) return;
  if (s.dead > 0) {
    el.textContent = "SYNC STUCK (" + s.dead + ")";
    el.className = "sync-badge dead";
  } else if (!s.online) {
    el.textContent = s.pending > 0 ? "OFFLINE (" + s.pending + ")" : "OFFLINE";
    el.className = "sync-badge offline";
  } else if (s.pending > 0) {
    el.textContent = "SYNCING (" + s.pending + ")";
    el.className = "sync-badge pending";
  } else {
    el.textContent = "ONLINE";
    el.className = "sync-badge online";
  }
}
