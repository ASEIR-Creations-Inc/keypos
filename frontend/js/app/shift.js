/* KEYPOS — shifts and Z-reports. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Shift ── */
function posSetShiftUI(isOpen) {
  if (DOM.shiftStatus) {
    DOM.shiftStatus.classList.toggle("closed", !isOpen);
    DOM.shiftStatus.textContent = isOpen ? "SHIFT ACTIVE" : "SHIFT CLOSED";
  }
  if (DOM.shiftModal) DOM.shiftModal.classList.toggle("visible", !isOpen);
  var banner = document.getElementById("shiftClosedBanner");
  if (banner) banner.style.display = isOpen ? "none" : "block";
}

function posCheckShift() {
  getCurrentShift().then(function(shift) {
    POS_STATE.shift = shift;
    POS_STATE.offlineMode = false;
    posCacheShift(shift);
    posSetShiftUI(true);
    posLoadData();
  }).catch(function(err) {
    if (err && err.network) {
      /* Server unreachable: keep selling from the cached shift and cached catalog.
         Sales are queued on the device and booked to whichever shift is open at sync. */
      POS_STATE.shift = posReadCachedShift();
      POS_STATE.offlineMode = true;
      posSetShiftUI(true);
      posLoadData();
      return;
    }
    POS_STATE.shift = null;
    posSetShiftUI(false);
  });
}

function posOpenShift() {
  var floatVal = parseFloat((DOM.floatInput && DOM.floatInput.value) || "0") || 0;
  openShift(floatVal).then(function(shift) {
    POS_STATE.shift = shift;
    POS_STATE.offlineMode = false;
    posCacheShift(shift);
    if (DOM.floatInput) DOM.floatInput.value = "";
    posSetShiftUI(true);
    posLoadData();
  }).catch(function(err) {
    alert("Failed to open shift: " + (err.message || "Unknown error"));
  });
}

function posCloseShift() {
  if (typeof closeDrawer === "function") closeDrawer();
  if (!POS_STATE.shift) { alert("There is no open shift."); return; }
  if (POS_STATE.cart.length > 0 && !confirm("The cart still has items. Close the shift anyway?")) return;
  var counted = prompt("Count the cash drawer and enter the closing cash amount:");
  if (counted === null) return;
  var closingCash = parseFloat(counted);
  if (isNaN(closingCash) || closingCash < 0) { alert("Enter a valid cash amount."); return; }
  closeShift(closingCash).then(function(z) {
    POS_STATE.shift = null;
    POS_STATE.offlineMode = false;
    posClearShiftCache();
    posSetShiftUI(false);
    showZReport(z);
  }).catch(function(err) {
    alert("Failed to close shift: " + (err.message || "Unknown error"));
  });
}

function zReportTime(value) {
  return localDateTime(value);
}

function zReportTimeShort(value) {
  return localDateTime(value).substring(11, 16);
}

/* Plain-text Z report, used for printing. */
function formatZReport(z) {
  var s = z.shift || {};
  var r = z.report || {};
  var variance = parseFloat(s.variance) || 0;
  var lines = [
    "Z REPORT - Shift #" + s.id,
    "Opened: " + zReportTime(s.opened_at),
    s.closed_at ? "Closed: " + zReportTime(s.closed_at) : "Still open (figures so far)",
    "",
    "Transactions: " + (r.total_transactions || 0),
    "Gross sales: " + money(r.gross_sales),
    "Discounts: " + money(r.total_discounts),
    "Refunds: " + money(r.total_refunds) + " (" + (r.refund_count || 0) + ")",
    "Net sales: " + money(r.net_sales),
    "Tax: " + money(r.tax_collected),
    "",
    "Cash: " + money(r.cash_sales),
    "Card: " + money(r.card_sales),
    "Account: " + money(r.account_sales),
    "",
    "Customer payments: cash " + money(r.customer_payments_cash) + ", card " + money(r.customer_payments_card),
    "Drawer expenses: " + money(r.drawer_expenses),
    "",
    "Opening float: " + money(s.opening_float),
    "Expected cash" + (s.closed_at ? "" : " so far") + ": " + money(r.expected_cash),
    s.closed_at ? "Counted cash: " + money(s.closing_cash) : null,
    s.closed_at ? "Variance: " + money(variance) : null,
    "",
    "Price edits: " + (r.price_edit_count || 0) + " (" + money(r.price_edit_variance) + ")"
  ].filter(function(line) { return line !== null; });
  if ((r.offline_sales_count || 0) > 0) {
    for (var li = 0; li < lines.length; li++) {
      if (lines[li].indexOf("Account: ") === 0) {
        lines.splice(li + 1, 0, "Offline sales: " + r.offline_sales_count + " (" + money(r.offline_sales_total) + ")");
        break;
      }
    }
  }
  var refunds = z.refunds || [];
  if (refunds.length) {
    lines.push("", "REFUNDED RECEIPTS (" + refunds.length + "):");
    refunds.forEach(function(rf) {
      lines.push("- " + (rf.refund_ref || "refund") + ": " + rf.sale_ref + " " + money(rf.amount) +
        " (" + (rf.reason || "no reason") + ") by " + (rf.refunded_by || "?") +
        (rf.reissued_as ? ", re-issued as " + rf.reissued_as : ""));
    });
  }
  var activity = z.activity || [];
  if (activity.length) {
    lines.push("", "SHIFT ACTIVITY (" + activity.length + " entries):");
    activity.forEach(function(e) {
      lines.push("- " + zReportTimeShort(e.created_at) + " [" + e.action + "] " + e.summary + " (" + (e.user_name || "?") + ")");
    });
  }
  return lines.join("\n");
}

/* ── Z Report panel ── */
var Z_REPORT_STATE = { current: null };

var AUDIT_ACTION_LABELS = {
  shift_open: "Shift opened", shift_close: "Shift closed",
  sale: "Sale", sale_held: "Ticket held", held_resumed: "Ticket resumed",
  refund: "Refund", price_edit: "Price edit",
  payment_received: "Customer payment",
  expense_added: "Expense", expense_edited: "Expense edited", expense_deleted: "Expense deleted",
  stock_adjusted: "Stock adjusted", purchase_posted: "Purchase received",
  product_created: "Product created", product_edited: "Product edited", product_deactivated: "Product deactivated"
};

function showZReport(z) {
  Z_REPORT_STATE.current = z;
  var s = z.shift || {};
  var r = z.report || {};
  var variance = parseFloat(s.variance) || 0;

  var titleEl = document.getElementById("zReportTitle");
  if (titleEl) titleEl.textContent = "Z Report — Shift #" + s.id;

  var html = "<div style='font-size:12px;color:#757575;margin-bottom:10px;'>" +
    "Opened " + escapeHtml(zReportTime(s.opened_at)) + " · " +
    (s.closed_at ? "Closed " + escapeHtml(zReportTime(s.closed_at)) : "<b style='color:#2E7D32;'>Still open</b> (figures so far)") + "</div>";
  html += reportKPI("Transactions", r.total_transactions || 0);
  html += reportKPI("Gross sales", money(r.gross_sales), "#4CAF50");
  html += reportKPI("Discounts", money(r.total_discounts), "#F44336");
  html += reportKPI("Refunds (" + (r.refund_count || 0) + ")", money(r.total_refunds), "#FF9800");
  html += reportKPI("Net sales", money(r.net_sales), "#4CAF50");
  html += reportKPI("Tax", money(r.tax_collected));
  html += reportKPI("Cash sales", money(r.cash_sales));
  html += reportKPI("Card sales", money(r.card_sales));
  html += reportKPI("Account sales", money(r.account_sales));
  if ((r.offline_sales_count || 0) > 0) {
    html += reportKPI("Offline sales (" + r.offline_sales_count + ")", money(r.offline_sales_total), "#FF9800");
  }
  html += reportKPI("Customer payments, cash", money(r.customer_payments_cash));
  html += reportKPI("Customer payments, card", money(r.customer_payments_card));
  html += reportKPI("Drawer expenses", money(r.drawer_expenses), "#F44336");
  html += reportKPI("Opening float", money(s.opening_float));
  html += reportKPI(s.closed_at ? "Expected cash" : "Expected cash so far", money(r.expected_cash));
  if (s.closed_at) {
    html += reportKPI("Counted cash", money(s.closing_cash));
    html += reportKPI("Variance", money(variance), variance === 0 ? "#4CAF50" : "#F44336");
  }
  html += reportKPI("Price edits", (r.price_edit_count || 0) + " (" + money(r.price_edit_variance) + ")");

  var refunds = z.refunds || [];
  html += "<h3 style='margin:16px 0 8px;'>Refunded receipts (" + refunds.length + ")</h3>";
  if (refunds.length === 0) {
    html += "<div style='color:#9E9E9E;font-size:13px;padding:4px 0;'>None</div>";
  } else {
    html += reportTable(
      ["Refund #", "Receipt", "Amount", "Reason", "By", "Re-issued as"],
      refunds.map(function(rf) {
        return [
          escapeHtml(rf.refund_ref || ""), escapeHtml(rf.sale_ref || ""), money(rf.amount),
          escapeHtml(rf.reason || ""), escapeHtml(rf.refunded_by || ""), escapeHtml(rf.reissued_as || "—")
        ];
      })
    );
  }

  var activity = z.activity || [];
  html += "<h3 style='margin:16px 0 8px;'>Shift activity (" + activity.length + ")</h3>";
  html += "<div style='font-size:12px;color:#9E9E9E;margin-bottom:8px;'>Every stock, cash, card and account movement of this shift, except the sales listed above.</div>";
  if (activity.length === 0) {
    html += "<div style='color:#9E9E9E;font-size:13px;padding:4px 0;'>No activity recorded</div>";
  } else {
    html += activity.map(function(e) {
      var label = AUDIT_ACTION_LABELS[e.action] || e.action;
      var moneyBits = [];
      if (parseFloat(e.cash)) moneyBits.push("cash " + money(e.cash));
      if (parseFloat(e.card)) moneyBits.push("card " + money(e.card));
      if (parseFloat(e.account)) moneyBits.push("account " + money(e.account));
      return "<div style='padding:8px 0;border-bottom:1px solid #F5F5F5;'>" +
        "<div style='display:flex;justify-content:space-between;'>" +
        "<span style='font-size:11px;font-weight:700;color:#4CAF50;text-transform:uppercase;'>" + escapeHtml(label) + "</span>" +
        "<span style='font-size:11px;color:#9E9E9E;'>" + escapeHtml(zReportTimeShort(e.created_at)) + " · " + escapeHtml(e.user_name || "") + "</span></div>" +
        "<div style='font-size:13px;margin-top:2px;'>" + escapeHtml(e.summary) + "</div>" +
        (moneyBits.length ? "<div style='font-size:12px;color:#757575;margin-top:2px;'>" + moneyBits.map(escapeHtml).join(" · ") + "</div>" : "") +
        "</div>";
    }).join("");
  }

  document.getElementById("zReportBody").innerHTML = html;
  openPanel("zReportPanel");
}

function printZReport() {
  if (!Z_REPORT_STATE.current) return;
  var text = formatZReport(Z_REPORT_STATE.current);
  var win = window.open("", "_blank");
  if (!win) { alert("Printing is blocked by the browser."); return; }
  win.document.write("<pre style='font-family:monospace;font-size:12px;'>" + escapeHtml(text) + "</pre>");
  win.document.close();
  win.focus();
  win.print();
}

/* ── Shift reports browser (Reports screen) ── */
function fetchShiftReportsList() {
  getShifts(30).then(function(shifts) {
    var html = "<h3 style='margin-bottom:12px;'>Shift Reports</h3>";
    if (!shifts || shifts.length === 0) {
      html += "<p style='text-align:center;padding:20px;color:#9E9E9E;'>No shifts recorded</p>";
      renderReportContent(html);
      return;
    }
    html += shifts.map(function(s) {
      var closed = s.status === "closed";
      var variance = parseFloat(s.variance || 0);
      return "<div onclick='openShiftZ(" + s.id + ")' style='cursor:pointer;border:1px solid #E0E0E0;border-radius:8px;padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;'>" +
        "<div><div style='font-weight:600;'>Shift #" + s.id + " <span style='font-size:11px;color:" + (closed ? "#757575" : "#4CAF50") + ";'>" + (closed ? "CLOSED" : "OPEN") + "</span></div>" +
        "<div style='font-size:12px;color:#9E9E9E;'>" + escapeHtml(zReportTime(s.opened_at)) + " · " + escapeHtml(s.cashier_name || "") + "</div></div>" +
        "<div style='text-align:right;font-size:12px;'>" +
        (closed ? "<span style='color:" + (variance === 0 ? "#4CAF50" : "#F44336") + ";'>variance " + (variance < 0 ? "-" : "") + money(Math.abs(variance)) + "</span>" : "<span style='color:#4CAF50;'>tap for report</span>") +
        "</div></div>";
    }).join("");
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Shift Reports", err); });
}

function openShiftZ(shiftId) {
  getShiftReport(shiftId).then(showZReport).catch(function(err) {
    alert("Failed to load the shift report: " + (err.message || "Unknown error"));
  });
}

safeAddListener("zReportPrintBtn", printZReport);
safeAddListener("btnShiftReports", function(e) {
  e.preventDefault();
  openReport("shifts", "Shift Reports");
  fetchShiftReportsList();
});
