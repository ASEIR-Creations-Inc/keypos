/* KEYPOS — start-up. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Init ── */
function posInit() {
  if (!posAuthCheck()) return;
  /* The badge's first draw needs the queue counts, which need the database open. */
  DB.open(function(err) { if (!err) SYNC.refreshStatus(); });

  /* Wire DOM refs */
  DOM.cashierName = document.getElementById("cashierName") || null;
  DOM.shiftStatus = document.getElementById("shiftStatus") || null;
  DOM.logoutBtn = document.getElementById("logoutBtn") || null;
  DOM.searchBox = document.getElementById("searchBox") || null;
  DOM.catBar = document.getElementById("catBar") || null;
  DOM.productGrid = document.getElementById("productGrid") || null;
  DOM.orderList = document.getElementById("orderList") || null;
  DOM.orderCount = document.getElementById("orderCount") || null;
  DOM.cartBadge = document.getElementById("cartBadge") || null;
  DOM.subtotalEl = document.getElementById("subtotal") || null;
  DOM.taxEl = document.getElementById("tax") || null;
  DOM.grandTotalEl = document.getElementById("grandTotal") || null;
  DOM.discountEl = document.getElementById("discountDisplay") || null;
  DOM.chargeBtn = document.getElementById("chargeBtn") || null;
  DOM.holdBtn = document.getElementById("holdBtn") || null;
  DOM.voidBtn = document.getElementById("voidBtn") || null;
  DOM.discBtn = document.getElementById("discBtn") || null;
  DOM.shiftModal = document.getElementById("shiftModal") || null;
  DOM.floatInput = document.getElementById("floatInput") || null;
  DOM.openShiftBtn = document.getElementById("openShiftBtn") || null;

  posApplyPermissions();
  posRefreshSession();
  dsRefreshPending();
  setInterval(dsRefreshPending, 60000);

  /* Bind shift open */
  if (DOM.openShiftBtn) {
    DOM.openShiftBtn.addEventListener("click", posOpenShift);
  }

  /* Bind search input — filter as you type */
  if (DOM.searchBox) {
    DOM.searchBox.addEventListener("input", function() {
      POS_STATE.searchQuery = DOM.searchBox.value.toLowerCase();
      posRenderProducts();
    });
  }

  /* Bind clear-cart */
  if (DOM.voidBtn) {
    DOM.voidBtn.addEventListener("click", function() {
      if (POS_STATE.cart.length === 0) return;
      if (confirm("Remove all items from the cart?")) {
        posClearCart();
      }
    });
  }

  /* Bind hold */
  if (DOM.holdBtn) {
    DOM.holdBtn.addEventListener("click", function() {
      if (POS_STATE.cart.length === 0) { alert("Cart is empty."); return; }
      apiPost("/transactions", {
        lines: posCartLines(),
        discount_amount: posCartTotals().cartDiscount,
        payment_cash: 0,
        payment_card: 0,
        payment_account: 0,
        notes: "held",
        status: "held"
      }).then(function() {
        posResetCart();
        alert("Ticket saved.");
      }).catch(function(err) {
        if (err && err.network) {
          DB.saveTicket(POS_STATE.cart, function(saveErr) {
            if (saveErr) {
              alert("Failed to save ticket offline: " + (saveErr.message || "storage error"));
              return;
            }
            posResetCart();
            alert("Ticket saved on this device (offline).");
          });
          return;
        }
        alert("Failed to save ticket: " + (err.message || "Unknown error"));
      });
    });
  }
  var ticketsBtnEl = document.getElementById("ticketsBtn");
  if (ticketsBtnEl) {
    ticketsBtnEl.addEventListener("click", function() {
      posLoadTickets();
      openPanel("ticketsPanel");
    });
  }
  var ticketsBackEl = document.getElementById("ticketsBack");
  if (ticketsBackEl) {
    ticketsBackEl.addEventListener("click", function() {
      closePanel("ticketsPanel");
    });
  }

  /* Bind discount */
  if (DOM.discBtn) {
    DOM.discBtn.addEventListener("click", function() {
      var discPct = prompt("Discount % on the whole sale (0 removes it):", String(roundCents(POS_STATE.cartDiscountPct * 100)));
      if (discPct !== null && discPct !== "") {
        var pct = parseFloat(discPct);
        if (isNaN(pct) || pct < 0 || pct > 100) {
          alert("Invalid discount percentage");
        } else {
          posApplyDiscount(pct / 100);
        }
      }
    });
  }

  /* Bind charge */
  if (DOM.chargeBtn) {
    DOM.chargeBtn.addEventListener("click", posShowPaymentModal);
  }

  bindProductModal();
  bindAddProduct();
  bindInventorySearch();
  bindPurchaseForm();
  bindReportButtons();
  safeAddListener("closeShiftBtn", function(e) { e.preventDefault(); posCloseShift(); });
  safeAddListener("saveSettingsBtn", saveSettings);
  loadSettings();
  /* Auto-sync every 30 seconds */
  SYNC.startAutoSync(30);
  posBindSyncBadge();

  /* Load shift or show modal */
  posCheckShift();
}
