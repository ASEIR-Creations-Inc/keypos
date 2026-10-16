/* KEYPOS — recent sales, refunds and re-issues. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Recent Sales: whole-receipt refunds and re-issues ── */
var SALES_STATE = { current: null };
var SALE_STATUS_COLORS = { completed: "#4CAF50", refunded: "#FF9800", voided: "#9E9E9E" };

function loadRecentSales() {
  var list = document.getElementById("salesList");
  list.innerHTML = "<div style='text-align:center;padding:20px;color:#9E9E9E;'>Loading...</div>";
  apiGet("/transactions?limit=50").then(function(txns) {
    var sales = (txns || []).filter(function(t) { return t.status !== "held"; });
    if (sales.length === 0) {
      list.innerHTML = "<div style='text-align:center;padding:40px;color:#9E9E9E;'>No sales yet</div>";
      return;
    }
    list.innerHTML = sales.map(function(t) {
      var when = t.created_at ? localDateTime(t.created_at) : "";
      var statusText = t.status.toUpperCase();
      if (t.status === "refunded" && t.reissued_as_ref) statusText += " · RE-ISSUED";
      var tags = "";
      if (t.is_offline) tags += " <span style='font-size:10px;font-weight:700;color:#FF9800;'>OFFLINE</span>";
      if (t.oversold) tags += " <span style='font-size:10px;font-weight:700;color:#F44336;'>OVERSOLD</span>";
      return "<div onclick='showSaleDetail(" + t.id + ")' style='cursor:pointer;border:1px solid #E0E0E0;border-radius:8px;padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;'>" +
        "<div><div style='font-weight:600;'>" + escapeHtml(t.ref_number) + tags + "</div>" +
        "<div style='font-size:12px;color:#9E9E9E;'>" + escapeHtml(when) + (t.customer_name ? " · " + escapeHtml(t.customer_name) : "") + "</div></div>" +
        "<div style='text-align:right;'><div style='font-weight:700;'>" + money(t.total_amount) + "</div>" +
        "<div style='font-size:11px;font-weight:600;color:" + (SALE_STATUS_COLORS[t.status] || "#757575") + ";'>" + escapeHtml(statusText) + "</div></div></div>";
    }).join("");
  }).catch(function(err) {
    list.innerHTML = "<div style='text-align:center;padding:40px;color:#F44336;'>Failed to load sales: " + escapeHtml(err.message) + "</div>";
  });
}

function saleDetailRow(label, value) {
  return "<div style='display:flex;justify-content:space-between;padding:3px 0;'><span>" + label + "</span><span>" + value + "</span></div>";
}

function showSaleDetail(id) {
  apiGet("/transactions/" + id).then(function(txn) {
    SALES_STATE.current = txn;

    var html = "<div style='font-size:13px;color:#757575;margin-bottom:8px;'>" +
      escapeHtml(txn.created_at ? localDateTime(txn.created_at) : "") +
      (txn.customer_name ? " · " + escapeHtml(txn.customer_name) : "") +
      " · <b style='color:" + (SALE_STATUS_COLORS[txn.status] || "#757575") + ";'>" + escapeHtml(txn.status.toUpperCase()) + "</b></div>";
    if (txn.is_offline) {
      html += "<div style='font-size:12px;color:#FF9800;margin-bottom:8px;'>Rung up offline on the device and synced to the server later.</div>";
    }
    if (txn.oversold) {
      html += "<div style='font-size:12px;color:#F44336;margin-bottom:8px;'>OVERSOLD — an item on this receipt pushed stock below zero (sold offline beyond the counted stock). Manager review needed.</div>";
    }
    if (txn.reissue_of_ref) {
      html += "<div style='font-size:12px;color:#4CAF50;margin-bottom:8px;'>Re-issue of refunded receipt " + escapeHtml(txn.reissue_of_ref) + "</div>";
    }
    if (txn.reissued_as_ref) {
      html += "<div style='font-size:12px;color:#4CAF50;margin-bottom:8px;'>Items kept were re-issued as " + escapeHtml(txn.reissued_as_ref) + "</div>";
    }
    html += (txn.transaction_lines || []).map(function(l) {
      var isRefunded = parseFloat(l.refunded_qty || 0) >= parseFloat(l.qty) && txn.status === "refunded";
      return "<div style='display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #F5F5F5;" + (isRefunded ? "opacity:0.6;" : "") + "'>" +
        "<div style='flex:1;'><div style='font-weight:500;'>" + escapeHtml(l.product_name || "Item") +
        (isRefunded ? " <span style='color:#FF9800;font-size:11px;'>RETURNED</span>" : "") + "</div>" +
        "<div style='font-size:12px;color:#9E9E9E;'>" + parseFloat(l.qty) + " × " + money(l.sell_price) +
        (parseFloat(l.discount) > 0 ? " − " + money(l.discount) : "") + "</div></div>" +
        "<span style='font-weight:600;'>" + money(l.line_total) + "</span></div>";
    }).join("");

    html += "<div style='margin-top:12px;font-size:14px;'>";
    html += saleDetailRow("Subtotal", money(txn.subtotal));
    if (parseFloat(txn.discount_amount) > 0) html += saleDetailRow("Discount", "-" + money(txn.discount_amount));
    if (parseFloat(txn.tax_amount) > 0) html += saleDetailRow("Tax", money(txn.tax_amount));
    html += saleDetailRow("<b>Total</b>", "<b>" + money(txn.total_amount) + "</b>");
    if (parseFloat(txn.payment_cash) > 0) html += saleDetailRow("Cash", money(txn.payment_cash));
    if (parseFloat(txn.payment_card) > 0) html += saleDetailRow("Card", money(txn.payment_card));
    if (parseFloat(txn.payment_account) > 0) html += saleDetailRow("On account", money(txn.payment_account));
    if (parseFloat(txn.change_given) > 0) html += saleDetailRow("Change", money(txn.change_given));
    html += "</div>";

    if (txn.refund) {
      var rf = txn.refund;
      html += "<div style='margin-top:12px;border:1px solid #FF9800;border-radius:8px;padding:10px 12px;background:#FFF8E1;font-size:13px;'>" +
        "<div style='font-weight:700;color:#E65100;margin-bottom:4px;'>REFUNDED " + escapeHtml(rf.ref_number || "") + "</div>" +
        saleDetailRow("Amount", money(rf.amount)) +
        (parseFloat(rf.refund_cash) ? saleDetailRow("Cash back", money(rf.refund_cash)) : "") +
        (parseFloat(rf.refund_card) ? saleDetailRow("Card back", money(rf.refund_card)) : "") +
        (parseFloat(rf.refund_account) ? saleDetailRow("Account credited", money(rf.refund_account)) : "") +
        saleDetailRow("Reason", escapeHtml(rf.reason || "")) +
        saleDetailRow("When", escapeHtml(rf.created_at ? localDateTime(rf.created_at) : "")) +
        "</div>";
    } else if (txn.status === "completed" && !txn.refundable) {
      html += "<div style='margin-top:12px;font-size:12px;color:#9E9E9E;'>The shift of this receipt is closed. Refunds are no longer possible.</div>";
    }

    document.getElementById("saleDetailTitle").textContent = txn.ref_number;
    document.getElementById("saleDetailBody").innerHTML = html;
    document.getElementById("saleRefundBtn").style.display = txn.refundable && txn.status === "completed" ? "" : "none";
    document.getElementById("saleReissueBtn").style.display = txn.status === "refunded" && !txn.reissued_as_ref ? "" : "none";
    openPanel("saleDetailPanel");
  }).catch(function(err) {
    alert("Failed to load sale: " + (err.message || "Unknown error"));
  });
}

function refundWholeReceipt() {
  var txn = SALES_STATE.current;
  if (!txn) return;
  if (!confirm("Refund the WHOLE receipt " + txn.ref_number + " (" + money(txn.total_amount) + ")?\n\nAll items go back to stock and the money is returned the way it was paid. A refund receipt is produced.")) return;
  var reason = prompt("Reason for the refund (required — kept in the audit trail):", "");
  if (reason === null) return;
  reason = reason.replace(/^\s+|\s+$/g, "");
  if (!reason) { alert("A reason is required."); return; }
  refundTransaction(txn.id, reason).then(function(updated) {
    closePanel("saleDetailPanel");
    loadRecentSales();
    posRefreshStock();
    var rf = updated.refund || {};
    var slip = [
      "REFUND RECEIPT",
      rf.ref_number || "",
      "Refund of " + updated.ref_number,
      "Amount: " + money(rf.amount),
      parseFloat(rf.refund_cash) ? "  Cash back: " + money(rf.refund_cash) : "",
      parseFloat(rf.refund_card) ? "  Card back: " + money(rf.refund_card) : "",
      parseFloat(rf.refund_account) ? "  Account credited: " + money(rf.refund_account) : "",
      "Reason: " + reason
    ].filter(Boolean).join("\n");
    alert(slip);
    if (confirm("Refund done. If the customer kept some items, ring them up now as a new receipt linked to " + updated.ref_number + "?")) {
      reissueReceipt(updated);
    }
  }).catch(function(err) {
    alert("Refund failed: " + (err.message || "Unknown error"));
  });
}

/* Loads a refunded receipt's items into the cart; the next charge links to it as a re-issue. */
function reissueReceipt(txn) {
  if (POS_STATE.cart.length > 0 && !confirm("Replace the items in the cart with this receipt's items?")) return;
  POS_STATE.cart = (txn.transaction_lines || []).map(function(l) {
    return {
      product_id: l.product_id,
      name: l.product_name || "Item",
      price: parseFloat(l.sell_price) || 0,
      qty: parseFloat(l.qty) || 1,
      discount: parseFloat(l.discount) || 0
    };
  });
  var lineDiscounts = 0;
  for (var i = 0; i < POS_STATE.cart.length; i++) lineDiscounts += POS_STATE.cart[i].discount;
  var afterLines = (parseFloat(txn.subtotal) || 0) - lineDiscounts;
  var cartDiscount = (parseFloat(txn.discount_amount) || 0) - lineDiscounts;
  POS_STATE.cartDiscountPct = afterLines > 0 && cartDiscount > 0 ? cartDiscount / afterLines : 0;
  POS_STATE.reissueOfId = txn.id;
  DB.saveCart(POS_STATE.cart, function() {});
  posRenderCart();
  closePanel("saleDetailPanel");
  closePanel("salesPanel");
  alert("Items loaded. Remove the ones the customer did not keep, then charge — the new receipt is linked to " + txn.ref_number + ".");
}

function reissueCurrentSale() {
  var txn = SALES_STATE.current;
  if (!txn) return;
  reissueReceipt(txn);
}

safeAddListener("salesHistoryBtn", function(e) {
  e.preventDefault();
  if (typeof closeDrawer === "function") closeDrawer();
  loadRecentSales();
  openPanel("salesPanel");
});
safeAddListener("salesBack", function() { closePanel("salesPanel"); });
safeAddListener("saleDetailBack", function() { closePanel("saleDetailPanel"); });
safeAddListener("saleRefundBtn", refundWholeReceipt);
safeAddListener("saleReissueBtn", reissueCurrentSale);
