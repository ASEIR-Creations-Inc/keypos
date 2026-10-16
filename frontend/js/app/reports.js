/* KEYPOS — reports. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Reports ── */
var REPORTS_STATE = { activeReport: null };

function loadReports() {
  var todayStr = localDateStr();
  var firstStr = monthStartStr();
  var fromEl = document.getElementById("reportDetailFrom");
  var toEl = document.getElementById("reportDetailTo");
  if (fromEl && !fromEl.value) fromEl.value = firstStr;
  if (toEl && !toEl.value) toEl.value = todayStr;
  bindReportButtons();
}

function openReport(reportId, title) {
  REPORTS_STATE.activeReport = reportId;
  var titleEl = document.getElementById("reportDetailTitle");
  if (titleEl) titleEl.textContent = title;
  var content = document.getElementById("reportDetailContent");
  if (content) content.innerHTML = "<div style=\"text-align:center;padding:40px;color:#9E9E9E;\">Set dates and tap RUN</div>";
  var today = localDateStr();
  var firstDay = monthStartStr();
  var fromEl = document.getElementById("reportDetailFrom");
  var toEl = document.getElementById("reportDetailTo");
  if (fromEl) fromEl.value = firstDay;
  if (toEl) toEl.value = today;
  openPanel("reportDetailPanel");
}

function runActiveReport() {
  var from = document.getElementById("reportDetailFrom").value;
  var to = document.getElementById("reportDetailTo").value;
  if (!from || !to) { alert("Select a date range."); return; }
  var content = document.getElementById("reportDetailContent");
  if (content) content.innerHTML = "<div style=\"text-align:center;padding:40px;color:#9E9E9E;\">Loading...</div>";
  var r = REPORTS_STATE.activeReport;
  if (r === "sales") fetchSalesSummary(from, to);
  else if (r === "shifts") fetchShiftReportsList();
  else if (r === "pnl") fetchPnL(from, to);
  else if (r === "purchases") fetchPurchasesReport(from, to);
  else if (r === "inventory") fetchInventoryValue();
  else if (r === "lowstock") fetchLowStock();
  else if (r === "priceedits") fetchPriceEdits(from, to);
  else if (r === "cashier") fetchCashierReport(from, to);
  else if (r === "tax") fetchTaxReport(from, to);
  else if (r === "stockadj") fetchStockAdjReport(from, to);
}

function bindReportButtons() {
  var reports = [
    { id: "btnSalesSummary", key: "sales", title: "Sales Summary" },
    { id: "btnPnl", key: "pnl", title: "P&L Report" },
    { id: "btnPurchasesReport", key: "purchases", title: "Purchases Report" },
    { id: "btnInventoryValue", key: "inventory", title: "Inventory Value" },
    { id: "btnLowStock", key: "lowstock", title: "Low Stock" },
    { id: "btnPriceEdits", key: "priceedits", title: "Price Edits" },
    { id: "btnCashierReport", key: "cashier", title: "Cashier Report" },
    { id: "btnTaxReport", key: "tax", title: "Tax Report" },
    { id: "btnStockAdjReport", key: "stockadj", title: "Stock Adjustments" }
  ];
  reports.forEach(function(r) {
    var btn = document.getElementById(r.id);
    if (btn && !btn._reportBound) {
      btn._reportBound = true;
      btn.addEventListener("click", function(e) {
        e.preventDefault();
        openReport(r.key, r.title);
      });
    }
  });
  var runBtn = document.getElementById("runReportBtn");
  if (runBtn && !runBtn._bound) {
    runBtn._bound = true;
    runBtn.addEventListener("click", runActiveReport);
  }
}

/* ── Report Renderers ── */

function reportKPI(label, value, color) {
  color = color || "#212121";
  return "<div style=\"background:#F5F5F5;border-radius:8px;padding:12px 16px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;\">" +
    "<span style=\"color:#757575;font-size:13px;\">" + label + "</span>" +
    "<span style=\"font-weight:700;font-size:16px;color:" + color + ";\">" + value + "</span>" +
    "</div>";
}

/* Report cells are text and get escaped; trustedHtml() marks the few this file formats itself. */
function trustedHtml(html) {
  return { html: html };
}

function cellHtml(cell) {
  if (cell && cell.html !== undefined) return cell.html;
  return escapeHtml(cell);
}

function reportTable(headers, rows) {
  if (!rows || rows.length === 0) return "<p style=\"text-align:center;padding:20px;color:#9E9E9E;\">No records found</p>";
  var html = "<div style=\"overflow-x:auto;\"><table style=\"width:100%;border-collapse:collapse;font-size:13px;\">";
  html += "<thead><tr>" + headers.map(function(h) {
    return "<th style=\"padding:8px 10px;text-align:left;border-bottom:2px solid #E0E0E0;color:#757575;font-weight:600;\">" + escapeHtml(h) + "</th>";
  }).join("") + "</tr></thead><tbody>";
  rows.forEach(function(row, idx) {
    var bg = idx % 2 === 0 ? "#fff" : "#FAFAFA";
    html += "<tr style=\"background:" + bg + ";\">" + row.map(function(cell) {
      return "<td style=\"padding:8px 10px;border-bottom:1px solid #F0F0F0;\">" + cellHtml(cell) + "</td>";
    }).join("") + "</tr>";
  });
  html += "</tbody></table></div>";
  return html;
}

function renderReportContent(html) {
  var el = document.getElementById("reportDetailContent");
  if (el) el.innerHTML = html;
}

function renderReportError(name, err) {
  renderReportContent("<div style=\"text-align:center;padding:40px;color:#F44336;\">Failed to load " + name + ": " + ((err && err.message) || "Unknown error") + "</div>");
}

/* ── Fetch Functions ── */

function fetchSalesSummary(from, to) {
  apiGet("/reports/sales-summary?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Sales Summary</h3>";
    html += reportKPI("Total Transactions", d.transaction_count || 0);
    html += reportKPI("Gross Sales", money(d.gross_sales), "#4CAF50");
    html += reportKPI("Net Sales", money(d.net_sales), "#4CAF50");
    html += reportKPI("Cash Sales", money(d.cash_sales));
    html += reportKPI("Card Sales", money(d.card_sales));
    html += reportKPI("Account Sales", money(d.account_sales));
    html += reportKPI("Total Discounts", money(d.total_discounts), "#F44336");
    html += reportKPI("Refunds", d.refund_count || 0);
    html += reportKPI("Refund Total", money(d.refund_total), "#F44336");
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Sales Summary", err); });
}

function fetchPnL(from, to) {
  apiGet("/reports/pnl?from_date=" + from + "&to_date=" + to).then(function(d) {
    var profit = parseFloat(d.net_profit || 0);
    var html = "<h3 style=\"margin-bottom:12px;\">P&L Report</h3>";
    html += reportKPI("Revenue", money(d.revenue), "#4CAF50");
    html += reportKPI("Cost of Goods (COGS)", money(d.cogs), "#F44336");
    html += reportKPI("Gross Profit", money(d.gross_profit), "#4CAF50");
    html += reportKPI("Gross Margin", parseFloat(d.gross_margin_pct || 0).toFixed(1) + "%");
    html += reportKPI("Total Expenses", money(d.total_expenses), "#F44336");
    html += reportKPI("Net Profit", money(profit), profit >= 0 ? "#4CAF50" : "#F44336");
    renderReportContent(html);
  }).catch(function(err) { renderReportError("P&L", err); });
}

function fetchPurchasesReport(from, to) {
  apiGet("/reports/purchases?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Purchases Report</h3>";
    html += reportKPI("Total Orders", d.total_orders || 0);
    html += reportKPI("Total Cost", money(d.total_cost), "#F44336");
    html += "<div style=\"margin-top:16px;\">";
    (d.orders || []).forEach(function(o) {
      html += "<div style=\"border:1px solid #E0E0E0;border-radius:8px;margin-bottom:10px;overflow:hidden;\">";
      html += "<div style=\"background:#F5F5F5;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;\">";
      html += "<div><div style=\"font-weight:600;font-size:13px;\">" + escapeHtml(o.ref_number) + "</div>";
      html += "<div style=\"font-size:12px;color:#757575;\">" + escapeHtml(o.supplier_name || "Unknown") + " · " + escapeHtml(localDateTime(o.created_at).substring(0, 10)) + "</div></div>";
      html += "<div style=\"text-align:right;\">";
      html += "<div style=\"font-weight:700;color:#F44336;\">" + money(o.total_amount) + "</div>";
      html += "<div style=\"font-size:11px;color:" + (o.status === "posted" ? "#4CAF50" : "#FF9800") + ";text-transform:uppercase;\">" + (o.status || "") + "</div>";
      if (o.status === "draft") html += "<button class=\"po-write\" onclick=\"deletePurchaseOrder(" + o.id + ")\" style=\"background:#F44336;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:11px;margin-top:4px;cursor:pointer;\">DEL</button>";
      html += "</div></div>";
      if (o.lines && o.lines.length) {
        html += "<table style=\"width:100%;font-size:12px;border-collapse:collapse;\">";
        html += "<tr style=\"background:#FAFAFA;\"><th style=\"padding:6px 12px;text-align:left;color:#9E9E9E;\">Product</th><th style=\"padding:6px;text-align:right;color:#9E9E9E;\">Qty</th><th style=\"padding:6px;text-align:right;color:#9E9E9E;\">Unit Cost</th><th style=\"padding:6px 12px;text-align:right;color:#9E9E9E;\">Total</th></tr>";
        o.lines.forEach(function(l) {
          html += "<tr><td style=\"padding:6px 12px;\">" + escapeHtml(l.product_name) + "</td>";
          html += "<td style=\"padding:6px;text-align:right;\">" + parseFloat(l.qty || 0).toFixed(0) + "</td>";
          html += "<td style=\"padding:6px;text-align:right;\">" + money(l.unit_cost) + "</td>";
          html += "<td style=\"padding:6px 12px;text-align:right;font-weight:600;\">" + money(l.total_cost) + "</td></tr>";
        });
        html += "</table>";
      }
      html += "</div>";
    });
    html += "</div>";
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Purchases", err); });
}

function fetchInventoryValue() {
  apiGet("/reports/inventory-value").then(function(d) {
    var products = d.products || [];
    var totalValue = 0;
    var totalUnits = 0;
    products.forEach(function(p) {
      totalValue += parseFloat(p.stock_value || 0);
      totalUnits += parseFloat(p.stock_qty || 0);
    });
    var html = "<h3 style=\"margin-bottom:12px;\">Inventory Value</h3>";
    html += reportKPI("Total Products", products.length);
    html += reportKPI("Total Units in Stock", totalUnits.toFixed(0));
    html += reportKPI("Total Stock Value", money(totalValue), "#4CAF50");
    html += "<div style=\"margin-top:16px;\">";
    html += reportTable(
      ["SKU", "Product", "Stock", "Cost Price", "Stock Value"],
      products.map(function(p) {
        return [
          p.sku || "",
          p.name || "",
          parseFloat(p.stock_qty || 0).toFixed(0),
          money(p.cost_price),
          money(p.stock_value)
        ];
      })
    );
    html += "</div>";
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Inventory Value", err); });
}

function fetchLowStock() {
  apiGet("/reports/low-stock").then(function(d) {
    var products = d.products || [];
    var html = "<h3 style=\"margin-bottom:12px;\">Low Stock Alert</h3>";
    html += reportKPI("Items Below Threshold", products.length, products.length > 0 ? "#F44336" : "#4CAF50");
    html += reportTable(
      ["Product", "Current Stock", "Threshold", "Deficit"],
      products.map(function(p) {
        var deficit = parseFloat(p.deficit || 0);
        return [
          p.name || "",
          trustedHtml("<span style=\"color:#F44336;font-weight:600;\">" + parseFloat(p.stock_qty || 0).toFixed(0) + "</span>"),
          parseFloat(p.low_stock_threshold || 0).toFixed(0),
          trustedHtml("<span style=\"color:#F44336;\">" + deficit.toFixed(0) + "</span>")
        ];
      })
    );
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Low Stock", err); });
}

function fetchPriceEdits(from, to) {
  apiGet("/reports/price-edits?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Price Edits</h3>";
    html += reportKPI("Total Edits", d.total_edits || 0);
    html += reportKPI("Net Price Variance", money(d.net_variance));
    html += reportTable(
      ["Date", "Cashier", "Product", "Old Price", "New Price", "Diff"],
      (d.edits || []).map(function(e) {
        var diff = parseFloat(e.difference || 0);
        return [
          localDateTime(e.edited_at),
          escapeHtml(e.cashier_name),
          escapeHtml(e.product_name),
          money(e.original_price),
          money(e.new_price),
          trustedHtml("<span style=\"color:" + (diff >= 0 ? "#4CAF50" : "#F44336") + ";\">" + money(diff) + "</span>")
        ];
      })
    );
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Price Edits", err); });
}

function fetchCashierReport(from, to) {
  apiGet("/reports/cashier?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Cashier Report</h3>";
    html += reportTable(
      ["Cashier", "Txns", "Gross", "Discounts", "Net", "Cash", "Card", "Account"],
      (d.cashiers || []).map(function(c) {
        return [
          escapeHtml(c.cashier_name),
          c.transaction_count || 0,
          money(c.gross_sales),
          money(c.discounts),
          money(c.net_sales),
          money(c.cash),
          money(c.card),
          money(c.account)
        ];
      })
    );
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Cashier Report", err); });
}

function fetchTaxReport(from, to) {
  apiGet("/reports/tax?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Tax Report</h3>";
    html += reportKPI("Total Tax Collected", money(d.total_tax), "#4CAF50");
    html += reportTable(
      ["Date", "Tax Amount"],
      (d.daily_breakdown || []).map(function(row) {
        return [
          row.tax_date || "",
          money(row.tax_amount)
        ];
      })
    );
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Tax Report", err); });
}

function fetchStockAdjReport(from, to) {
  apiGet("/reports/stock-adjustments?from_date=" + from + "&to_date=" + to).then(function(d) {
    var html = "<h3 style=\"margin-bottom:12px;\">Stock Adjustments</h3>";
    html += reportTable(
      ["Date", "Product", "Adjustment", "Reason", "Cashier"],
      (d.adjustments || []).map(function(a) {
        var adj = parseFloat(a.adjustment || 0);
        return [
          localDateTime(a.created_at).substring(0, 10),
          a.product_name || "",
          trustedHtml("<span style=\"color:" + (adj >= 0 ? "#4CAF50" : "#F44336") + ";font-weight:600;\">" + (adj >= 0 ? "+" : "") + adj.toFixed(0) + "</span>"),
          escapeHtml(a.reason),
          escapeHtml(a.adjusted_by_name)
        ];
      })
    );
    renderReportContent(html);
  }).catch(function(err) { renderReportError("Stock Adjustments", err); });
}
