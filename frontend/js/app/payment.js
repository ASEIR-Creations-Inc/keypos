/* KEYPOS — payment panel. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Show Payment Modal ── */
var PAYMENT_MODAL_STATE = {
  total: 0,
  method: "",
  cashTendered: 0
};

function posShowPaymentModal() {
  if (POS_STATE.cart.length === 0) return;
  if (!posShiftOk()) {
    alert("No open shift");
    return;
  }

  var grandTotal = posCartTotals().total;

  PAYMENT_MODAL_STATE.total = grandTotal;
  PAYMENT_MODAL_STATE.method = "";

  var payTotalDisplay = document.getElementById("payTotalDisplay");
  if (payTotalDisplay) payTotalDisplay.textContent = money(grandTotal);

  /* Reset modal state */
  var cashTenderedInput = document.getElementById("cashTenderedInput");
  if (cashTenderedInput) cashTenderedInput.value = "";
  var changeDisplay = document.getElementById("changeDisplay");
  if (changeDisplay) changeDisplay.textContent = "Change: " + money(0);

  posShowPaySection(null);
  openPanel("paymentPanel");

  /* Bind payment method buttons (once) */
  if (!posPaymentModalBound) {
    posPaymentModalBound = true;

    document.getElementById("payCashBtn").addEventListener("click", function() {
      PAYMENT_MODAL_STATE.method = "cash";
      posShowPaySection("payCashSection");
      document.getElementById("cashTenderedInput").focus();
    });

    document.getElementById("payCardBtn").addEventListener("click", function() {
      PAYMENT_MODAL_STATE.method = "card";
      posShowPaySection("payCardSection");
    });

    document.getElementById("paySplitBtn").addEventListener("click", function() {
      PAYMENT_MODAL_STATE.method = "split";
      posShowPaySection("paySplitSection");
      document.getElementById("splitCashInput").value = "";
      document.getElementById("splitCardInput").value = "";
      posValidateSplit();
    });

    document.getElementById("confirmCashBtn").addEventListener("click", function() {
      posProcessPayment("cash");
    });

    document.getElementById("confirmCardBtn").addEventListener("click", function() {
      posProcessPayment("card");
    });

    document.getElementById("confirmSplitBtn").addEventListener("click", function() {
      posProcessPayment("split");
    });

    document.getElementById("payAccountBtn").addEventListener("click", function() {
      PAYMENT_MODAL_STATE.method = "account";
      posShowPaySection("payAccountSection");
      /* Populate customer dropdown */
      var select = document.getElementById("accountCustomerSelect");
      select.innerHTML = '<option value="">-- Select Customer --</option>';
      apiGet("/customers").then(function(data) {
        var customers = data.customers || data || [];
        customers.forEach(function(c) {
          var opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name + (c.phone ? " (" + c.phone + ")" : "");
          select.appendChild(opt);
        });
      });
    });
    document.getElementById("accountCustomerSelect").addEventListener("change", function() {
      var customerId = this.value;
      var display = document.getElementById("accountBalanceDisplay");
      if (!customerId) { display.textContent = ""; return; }
      apiGet("/customers/" + customerId).then(function(c) {
        var balance = parseFloat(c.balance || 0);
        var limit = parseFloat(c.credit_limit || 0);
        display.textContent = "Balance: " + money(balance) + " | Limit: " + money(limit);
        display.style.color = balance >= limit ? "#F44336" : "#757575";
      });
    });
    document.getElementById("confirmAccountBtn").addEventListener("click", function() {
      var customerId = document.getElementById("accountCustomerSelect").value;
      if (!customerId) { alert("Select a customer."); return; }
      posProcessPayment("account", parseInt(customerId));
    });
    document.getElementById("cancelPayBtn").addEventListener("click", function() {
      closePanel("paymentPanel");
    });

    /* Live change calculator for cash */
    document.getElementById("cashTenderedInput").addEventListener("input", function() {
      var tendered = parseFloat(this.value) || 0;
      var change = tendered - PAYMENT_MODAL_STATE.total;
      document.getElementById("changeDisplay").textContent = "Change: " + money(Math.max(change, 0));
    });

    /* Live validation for split */
    document.getElementById("splitCashInput").addEventListener("input", posValidateSplit);
    document.getElementById("splitCardInput").addEventListener("input", posValidateSplit);
  }
}
var posPaymentModalBound = false;
var PAY_SECTIONS = ["payCashSection", "payCardSection", "paySplitSection", "payAccountSection"];

function posShowPaySection(activeId) {
  for (var i = 0; i < PAY_SECTIONS.length; i++) {
    var el = document.getElementById(PAY_SECTIONS[i]);
    if (el) el.style.display = PAY_SECTIONS[i] === activeId ? "block" : "none";
  }
}

function posValidateSplit() {
  var cash = parseFloat(document.getElementById("splitCashInput").value) || 0;
  var card = parseFloat(document.getElementById("splitCardInput").value) || 0;
  var remaining = PAYMENT_MODAL_STATE.total - (cash + card);
  var confirmSplitBtn = document.getElementById("confirmSplitBtn");
  if (confirmSplitBtn) {
    confirmSplitBtn.disabled = Math.abs(remaining) > 0.01;
  }
  var remainingEl = document.getElementById("splitRemaining");
  if (remainingEl) remainingEl.textContent = "Remaining: " + money(remaining);
}

function posProcessPayment(method, customerId) {
  if (!posShiftOk()) {
    alert("No open shift");
    return;
  }

  var totals = posCartTotals();
  var totalAmount = totals.total;

  var paymentCash = 0;
  var paymentCard = 0;
  var cashTendered = 0;

  if (method === "cash") {
    cashTendered = parseFloat(document.getElementById("cashTenderedInput").value) || 0;
    if (cashTendered < totalAmount) {
      alert("Insufficient cash tendered");
      return;
    }
    paymentCash = totalAmount;
  } else if (method === "card") {
    paymentCard = totalAmount;
  } else if (method === "split") {
    var cashVal = parseFloat(document.getElementById("splitCashInput").value) || 0;
    var cardVal = parseFloat(document.getElementById("splitCardInput").value) || 0;
    if (Math.abs(cashVal + cardVal - totalAmount) > 0.01) {
      alert("Split amounts must equal total");
      return;
    }
    paymentCash = cashVal;
    paymentCard = cardVal;
  } else if (method === "account") {
    /* Account sale — charged to customer */
  }


  var btn = document.getElementById(method === "cash" ? "confirmCashBtn" : method === "card" ? "confirmCardBtn" : method === "account" ? "confirmAccountBtn" : "confirmSplitBtn");
  if (btn) { btn.disabled = true; btn.textContent = "PROCESSING..."; }

  var txnPayload = {
    lines: posCartLines(),
    payment_cash: paymentCash,
    payment_card: paymentCard,
    payment_account: method === "account" ? totalAmount : 0,
    customer_id: customerId || null,
    discount_amount: totals.cartDiscount,
    reissue_of_id: POS_STATE.reissueOfId || null,
    notes: "POS sale",
    /* Same ref online and in the offline queue: if the reply is lost after the server
       recorded the sale, the queued copy is recognised at sync instead of recorded twice. */
    device_id: DB.getDeviceId(),
    client_ref: DB.makeClientRef()
  };

  createTransaction(txnPayload).then(function(txn) {
    posResetCart();
    posRefreshStock();

    /* Close modal */
    closePanel("paymentPanel");

    /* Show receipt */
    var change = cashTendered > 0 ? (cashTendered - totalAmount) : 0;
    var receiptMsg = "Sale complete!\n" + ((txn && txn.ref_number) || "") + "\nTotal: " + money(totalAmount);
    if (txn && txn.reissue_of_ref) receiptMsg += "\nRe-issue of " + txn.reissue_of_ref;
    if (method === "cash") {
      receiptMsg += "\nCash: " + money(cashTendered);
      receiptMsg += "\nChange: " + money(change);
    } else if (method === "split") {
      receiptMsg += "\nCash: " + money(paymentCash) + "\nCard: " + money(paymentCard);
    } else if (method === "card") {
      receiptMsg += "\nCard payment";
    } else if (method === "account") {
      receiptMsg += "\nAccount sale - charged to customer";
    }
    alert(receiptMsg);

    if (btn) { btn.disabled = false; btn.textContent = method === "cash" ? "CONFIRM CASH" : method === "card" ? "CONFIRM CARD" : method === "account" ? "CONFIRM ACCOUNT" : "CONFIRM SPLIT"; }
  }).catch(function(err) {
    if (btn) { btn.disabled = false; btn.textContent = method === "cash" ? "CONFIRM CASH" : method === "card" ? "CONFIRM CARD" : method === "account" ? "CONFIRM ACCOUNT" : "CONFIRM SPLIT"; }
    if (err && err.network) {
      /* No server response at all: save the sale on the device and sync it later. */
      posQueueOfflineSale(txnPayload, method, cashTendered, totals);
      return;
    }
    console.error("Payment failed:", err);
    var errMsg = (err && err.message) ? err.message : "Payment failed";
    alert("Sale NOT recorded: " + errMsg + "\nThe cart has been kept. Please try again.");
  });
}
