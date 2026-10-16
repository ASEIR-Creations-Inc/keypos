/* KEYPOS — Day Sheet: the Excel sheet filled in on a phone during the day, refreshed when
   the catalogue changes, and uploaded once as one receipt plus its expenses; and sheets
   sent from the KEYPOS Sheet app (/sheet/), which an approver reviews, then approves
   (recorded in their shift, one receipt per block of lines) or returns to the employee
   with a note. */
/* Android 6 compatible — no arrow functions, no const/let */

var DS_LANG_KEY = "pos_daysheet_lang";
var DS_TABS = { sheet: "Sheet", sales: "Sales line", expenses: "Expense line", summary: "Summary" };

var DS_STATUS = {
  open: ["badge-blue", "OPEN"], uploaded: ["badge-green", "UPLOADED"], draft: ["badge-blue", "DRAFT (APP)"],
  submitted: ["badge-red", "WAITING"], returned: ["badge-red", "RETURNED"], approved: ["badge-green", "APPROVED"]
};

function loadDaySheets() {
  loadSheetApprovals();
  var lang = document.getElementById("daySheetLang");
  if (lang) lang.value = localStorage.getItem(DS_LANG_KEY) || "pt";
  var list = document.getElementById("daySheetList");
  apiGet("/daysheets").then(function(sheets) {
    if (!sheets.length) {
      list.innerHTML = "<div class='list-item-sub' style='padding:8px 0;'>No sheets yet.</div>";
      return;
    }
    list.innerHTML = sheets.map(dsSheetRow).join("");
  }).catch(function(err) {
    list.innerHTML = "<div class='list-item-sub'>" + escapeHtml(err.message) + "</div>";
  });
}

function dsSheetRow(s) {
  var app = s.kind === "app";
  var recorded = s.status === "uploaded" || s.status === "approved";
  var look = DS_STATUS[s.status] || ["badge-blue", s.status.toUpperCase()];
  var badge = "<span class='badge " + look[0] + "'>" + look[1] + "</span>";
  var sub = dsDate(s.sheet_date) + (app ? " · Sheet app" : " · v" + s.version) + " · " + escapeHtml(s.created_by_name);
  if (recorded) {
    sub += "<br>" + (s.receipt_ref ? escapeHtml(s.receipt_ref) + (s.receipt_count > 1 ? " +" + (s.receipt_count - 1) + " more" : "") : "expenses only") +
      (s.difference !== null ? " · difference " + dsSigned(s.difference) : "");
  }
  var action = "";
  if (app && s.status !== "draft") {
    action = "<button class='list-item-action action-blue' onclick='openSheetReview(" + s.id + ")'>VIEW</button>";
  } else if (!app && !recorded) {
    action = "<button class='list-item-action action-blue' onclick='dsDownloadAgain(" + s.id + ")'>&#11015; v" + s.version + "</button>";
  }
  return "<div class='list-item'><div class='list-item-info'><div class='list-item-title'>" +
    escapeHtml(s.code) + " " + badge + "</div><div class='list-item-sub'>" + sub + "</div></div>" + action + "</div>";
}

function dsDate(iso) {
  var p = String(iso).split("-");
  return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : iso;
}

function dsSigned(value) {
  var n = parseFloat(value) || 0;
  return (n > 0 ? "+" : "") + money(n);
}

function dsSave(file, message) {
  saveBlob(file.blob, file.name);
  alert(message + "\n\nFile: " + file.name + "\nSheet: " + file.headers.get("X-Day-Sheet") +
    " (version " + file.headers.get("X-Day-Sheet-Version") + ")");
  loadDaySheets();
}

function dsDownloadNew() {
  var lang = document.getElementById("daySheetLang").value;
  localStorage.setItem(DS_LANG_KEY, lang);
  apiFile("POST", "/daysheets?lang=" + encodeURIComponent(lang)).then(function(file) {
    dsSave(file, "Today's sheet is downloaded. Open it in Excel and fill it in during the day.");
  }).catch(function(err) {
    alert("Download failed: " + err.message);
  });
}

function dsDownloadAgain(id) {
  apiFile("GET", "/daysheets/" + id + "/file").then(function(file) {
    dsSave(file, "Downloaded again. Use this file and delete older copies.");
  }).catch(function(err) {
    alert("Download failed: " + err.message);
  });
}

function dsPickedFile() {
  var input = document.getElementById("daySheetFile");
  if (!input.files || !input.files.length) {
    alert("Choose your day sheet file first (close it in Excel so the latest changes are saved).");
    return null;
  }
  return input.files[0];
}

function dsForm(file) {
  var form = new FormData();
  form.append("file", file, file.name);
  return form;
}

function dsInspect(file) {
  return apiRequest("POST", "/daysheets/inspect", dsForm(file));
}

function dsSheetProblem(result) {
  for (var i = 0; i < result.problems.length; i++) {
    if (result.problems[i].tab === "sheet") return result.problems[i].message;
  }
  return "This sheet can't be used.";
}

function dsRefresh() {
  var file = dsPickedFile();
  if (!file) return;
  dsInspect(file).then(function(r) {
    if (!r.can_refresh) {
      alert(dsSheetProblem(r));
      return null;
    }
    var ok = confirm("Refresh sheet " + r.code + "?\n\nVersion " + r.version + " · " + r.sales_rows + " sales rows · " +
      r.expense_rows + " expense rows\n\nCheck the code matches the Summary tab of your sheet. Your rows are kept; " +
      "the product list and stock are updated. You get version " + (r.version + 1) + " — stop using version " + r.version + ".");
    if (!ok) return null;
    return apiFile("POST", "/daysheets/refresh", dsForm(file)).then(function(f) {
      document.getElementById("daySheetFile").value = "";
      document.getElementById("daySheetPreview").innerHTML = "";
      dsSave(f, "Refreshed. Open the new version and carry on typing.");
    });
  }).catch(function(err) {
    alert("Refresh failed: " + err.message);
  });
}

function dsCheck() {
  var file = dsPickedFile();
  if (!file) return;
  var box = document.getElementById("daySheetPreview");
  box.innerHTML = "<div class='list-item-sub' style='padding:8px 0;'>Checking...</div>";
  dsInspect(file).then(function(r) {
    box.innerHTML = dsPreview(r);
    safeAddListener("daySheetIssueBtn", function() { dsUpload(file, r); });
  }).catch(function(err) {
    box.innerHTML = "";
    alert("Check failed: " + err.message);
  });
}

function dsMoneyRow(label, value, strong) {
  var style = strong ? "font-weight:700;" : "";
  return "<tr><td style='padding:4px 0;" + style + "'>" + label + "</td><td style='text-align:right;" + style + "'>" +
    (value === null ? "—" : money(value)) + "</td></tr>";
}

function dsPreview(r) {
  var html = "<div style='background:#fff;border:1px solid #E0E0E0;border-radius:6px;padding:12px;margin:8px 0;'>";
  html += "<div style='font-size:17px;font-weight:700;'>" + escapeHtml(r.code) + " · v" + r.version + "</div>";
  html += "<div class='list-item-sub'>" + dsDate(r.sheet_date) + " · by " + escapeHtml(r.created_by_name) + " · " +
    r.sales_rows + " sales rows · " + r.expense_rows + " expense rows</div>";
  html += dsProblems(r.problems, "Fix these in the sheet, then upload again. Nothing was recorded.");
  html += dsFigures(r);
  if (r.can_upload) {
    html += "<button class='btn-primary mt-8' id='daySheetIssueBtn' style='width:100%;'>ISSUE RECEIPT</button>";
  }
  return html + "</div>";
}

function dsProblems(problems, heading) {
  if (!problems.length) return "";
  return "<div style='margin-top:10px;padding:10px;background:#FFEBEE;border-radius:4px;color:#C62828;'>" +
    "<b>" + escapeHtml(heading) + "</b><ul style='margin:6px 0 0 18px;padding:0;'>" +
    problems.map(function(p) {
      var where = (p.block ? "Block " + p.block + " · " : "") + DS_TABS[p.tab] + (p.row ? " " + (p.row - 1) : "");
      return "<li><b>" + where + ":</b> " + escapeHtml(p.message) + "</li>";
    }).join("") + "</ul></div>";
}

/* The cash check, receipt lines and expenses of a checked sheet (Excel inspection or app review). */
function dsFigures(r) {
  var t = r.totals;
  var html = "<table style='width:100%;margin-top:10px;font-size:14px;border-collapse:collapse;'>";
  html += dsMoneyRow("Sales (" + r.lines.length + " lines)", t.grand_total, false);
  if (parseFloat(t.tax)) html += dsMoneyRow("Tax", t.tax, false) + dsMoneyRow("Receipt total", t.receipt_total, true);
  html += dsMoneyRow("− Card (machine slip)", t.card, false);
  html += dsMoneyRow("= Cash sales", t.cash_sales, true);
  if (parseFloat(t.card_marked)) html += dsMoneyRow("Card marked on lines (reference only)", t.card_marked, false);
  html += dsMoneyRow("Cash counted", t.counted, false);
  html += dsMoneyRow("+ Expenses from drawer", t.drawer_expenses, false);
  if (parseFloat(t.starting_cash)) html += dsMoneyRow("− Starting cash", t.starting_cash, false);
  html += dsMoneyRow("= Cash accounted for", t.accounted, true);
  html += dsMoneyRow("Other expenses (not from drawer)", t.other_expenses, false);
  html += "</table>";
  if (t.difference !== null) {
    var d = parseFloat(t.difference);
    var colour = d > 0 ? "#2E7D32" : d < 0 ? "#C62828" : "#616161";
    var word = d > 0 ? "EXTRA CASH" : d < 0 ? "SHORT" : "BALANCED";
    html += "<div style='margin-top:8px;font-size:17px;font-weight:700;color:" + colour + ";'>Difference " +
      dsSigned(d) + " · " + word + "</div>";
  }

  if (t.card_marked !== null && t.card_marked !== undefined && parseFloat(t.card_marked) > parseFloat(t.card)) {
    html += "<div style='margin-top:4px;color:#E65100;font-size:13px;'>The card marked on lines is more than the slip. The slip counts.</div>";
  }
  var blocks = r.blocks || [];
  if (blocks.length > 1) {
    html += "<div style='margin-top:12px;font-weight:600;'>Receipts (one per block)</div>" +
      "<table style='width:100%;font-size:13px;border-collapse:collapse;'>" +
      "<tr style='color:#757575;'><td>Block</td><td style='text-align:right;'>Total</td><td style='text-align:right;'>Card</td><td style='text-align:right;'>Cash</td></tr>";
    html += blocks.map(function(b) {
      return "<tr style='border-bottom:1px solid #F5F5F5;'><td style='padding:4px 0;'>" + b.block + " · " + b.lines + " lines" +
        (b.receipt_ref ? "<br><span class='list-item-sub'>" + escapeHtml(b.receipt_ref) + "</span>" : "") +
        "</td><td style='text-align:right;'>" + money(b.total) + "</td><td style='text-align:right;'>" + money(b.card) +
        "</td><td style='text-align:right;'>" + money(b.cash) + "</td></tr>";
    }).join("");
    html += "</table>";
  }
  if (r.lines.length) {
    var several = blocks.length > 1;
    var pays = { card: "Card", split: "Split" };
    html += "<div style='margin-top:12px;font-weight:600;'>Receipt lines</div><table style='width:100%;font-size:13px;border-collapse:collapse;'>";
    html += r.lines.map(function(l, i) {
      var head = several && (i === 0 || r.lines[i - 1].block !== l.block) ?
        "<tr><td colspan='3' style='padding:8px 0 2px;font-weight:600;color:#1565C0;'>Block " + l.block + "</td></tr>" : "";
      var mark = pays[l.pay] ? " <span class='list-item-sub'>· " + pays[l.pay] +
        (l.pay === "split" ? " " + money(l.card) : "") + "</span>" : "";
      return head + "<tr style='border-bottom:1px solid #F5F5F5;'><td style='padding:4px 0;'>" + escapeHtml(l.name) + mark +
        "</td><td style='text-align:right;'>" + parseFloat(l.qty) + " × " + money(l.price) +
        "</td><td style='text-align:right;padding-left:8px;'>" + money(l.total) + "</td></tr>";
    }).join("");
    html += "</table>";
  }
  if (r.expenses.length) {
    html += "<div style='margin-top:12px;font-weight:600;'>Expenses</div><table style='width:100%;font-size:13px;border-collapse:collapse;'>";
    html += r.expenses.map(function(e) {
      return "<tr style='border-bottom:1px solid #F5F5F5;'><td style='padding:4px 0;'>" +
        escapeHtml(e.description || e.category || "Expense") + (e.category && e.description ? " · " + escapeHtml(e.category) : "") +
        "</td><td>" + (e.paid_from_drawer ? "Drawer" : "Other") + "</td><td style='text-align:right;'>" + money(e.amount) + "</td></tr>";
    }).join("");
    html += "</table>";
  }
  return html;
}

function dsUpload(file, r) {
  var t = r.totals;
  var ok = confirm("Upload " + r.code + " version " + r.version + "?\n\n" +
    (r.lines.length ? "One receipt: " + money(t.receipt_total) + " (card " + money(t.card) + ", cash " + money(t.cash_sales) + ")\n" : "No sales\n") +
    (r.expenses.length ? r.expenses.length + " expense(s): " + money(parseFloat(t.drawer_expenses) + parseFloat(t.other_expenses)) + "\n" : "") +
    "\nStock is deducted now. A sheet can only be uploaded once.");
  if (!ok) return;
  var btn = document.getElementById("daySheetIssueBtn");
  btn.disabled = true;
  btn.textContent = "UPLOADING...";
  apiRequest("POST", "/daysheets/upload", dsForm(file)).then(function(res) {
    document.getElementById("daySheetFile").value = "";
    document.getElementById("daySheetPreview").innerHTML = "";
    alert(res.code + " uploaded.\n\n" + (res.receipt_ref ? "Receipt " + res.receipt_ref + ": " + money(res.totals.receipt_total) + "\n" : "") +
      (res.expense_count ? res.expense_count + " expense(s) recorded\n" : "") +
      (res.totals.difference !== null ? "Cash difference " + dsSigned(res.totals.difference) : ""));
    loadDaySheets();
    if (typeof posRefreshStock === "function") posRefreshStock();
  }).catch(function(err) {
    btn.disabled = false;
    btn.textContent = "ISSUE RECEIPT";
    alert("Upload failed: " + err.message);
  });
}

safeAddListener("daySheetNewBtn", dsDownloadNew);
safeAddListener("daySheetRefreshBtn", dsRefresh);
safeAddListener("daySheetCheckBtn", dsCheck);
document.getElementById("daySheetFile").addEventListener("change", function() {
  document.getElementById("daySheetPreview").innerHTML = "";
});

/* ── Sheets sent from the KEYPOS Sheet app ── */

function loadSheetApprovals() {
  var box = document.getElementById("sheetApprovals");
  if (!hasPermission("approve_sheets")) { box.style.display = "none"; return; }
  box.style.display = "";
  var list = document.getElementById("sheetApprovalList");
  apiGet("/daysheets?status=submitted").then(function(sheets) {
    dsShowPending(sheets.length);
    list.innerHTML = sheets.length ? sheets.map(function(s) {
      return "<div class='list-item'><div class='list-item-info'><div class='list-item-title'>" + escapeHtml(s.created_by_name) +
        " · " + escapeHtml(s.code) + "</div><div class='list-item-sub'>" + dsDate(s.sheet_date) + " · sent " +
        dsWhen(s.submitted_at) + "</div></div><button class='list-item-action action-blue' onclick='openSheetReview(" +
        s.id + ")'>REVIEW</button></div>";
    }).join("") : "<div class='list-item-sub' style='padding:8px 0;'>Nothing waiting.</div>";
  }).catch(function(err) {
    list.innerHTML = "<div class='list-item-sub'>" + escapeHtml(err.message) + "</div>";
  });
}

function dsWhen(iso) {
  if (!iso) return "";
  var d = new Date(iso);
  return ("0" + d.getDate()).slice(-2) + "/" + ("0" + (d.getMonth() + 1)).slice(-2) + " " +
    ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
}

function dsShowPending(count) {
  var badge = document.getElementById("sheetPendingBadge");
  if (!badge) return;
  badge.textContent = count;
  badge.style.display = count ? "" : "none";
}

/* The menu's "waiting" count, for approvers. */
function dsRefreshPending() {
  if (!hasPermission("approve_sheets") || !navigator.onLine) return;
  apiGet("/daysheets?status=submitted").then(function(sheets) { dsShowPending(sheets.length); }).catch(function() {});
}

function openSheetReview(id) {
  var body = document.getElementById("sheetReviewBody");
  body.innerHTML = "<div class='list-item-sub'>Loading...</div>";
  openPanel("sheetReviewPanel");
  apiGet("/daysheets/" + id + "/review").then(function(r) {
    document.getElementById("sheetReviewTitle").textContent = r.code;
    body.innerHTML = dsReview(r);
    safeAddListener("sheetApproveBtn", function() { dsApprove(r); });
    safeAddListener("sheetReturnBtn", function() { dsReturn(r); });
  }).catch(function(err) {
    body.innerHTML = "<div class='list-item-sub'>" + escapeHtml(err.message) + "</div>";
  });
}

function dsReview(r) {
  var look = DS_STATUS[r.status] || ["badge-blue", r.status];
  var html = "<div style='font-size:17px;font-weight:700;'>" + escapeHtml(r.code) + " <span class='badge " + look[0] + "'>" +
    look[1] + "</span></div><div class='list-item-sub'>" + dsDate(r.sheet_date) + " · by " + escapeHtml(r.created_by_name) +
    (r.submitted_at ? " · sent " + dsWhen(r.submitted_at) : "") + "</div>";
  if (r.status === "approved") {
    var refs = r.receipt_refs && r.receipt_refs.length ? r.receipt_refs : r.receipt_ref ? [r.receipt_ref] : [];
    html += "<div class='list-item-sub' style='margin-top:6px;color:#2E7D32;'>Approved by " + escapeHtml(r.approved_by_name || "") +
      " " + dsWhen(r.approved_at) + (refs.length ? " · " + escapeHtml(refs.join(", ")) : "") + "</div>";
  }
  if (r.return_note) {
    html += "<div class='list-item-sub' style='margin-top:6px;'>Last returned " + dsWhen(r.returned_at) + ": " +
      escapeHtml(r.return_note) + "</div>";
  }
  html += dsProblems(r.problems, "This sheet can't be approved yet:");
  html += dsFigures(r);
  if (r.status === "submitted" && hasPermission("approve_sheets")) {
    if (r.can_approve) {
      html += "<button class='btn-primary mt-8' id='sheetApproveBtn' style='width:100%;'>APPROVE · ISSUE RECEIPT</button>";
    }
    html += "<button class='btn-secondary mt-8' id='sheetReturnBtn'>RETURN TO EMPLOYEE</button>";
  }
  return html;
}

function dsApprove(r) {
  var t = r.totals;
  var count = (r.blocks || []).length;
  var receipts = count > 1 ? count + " receipts in YOUR shift" : "One receipt in YOUR shift";
  var ok = confirm("Approve " + r.code + " from " + r.created_by_name + "?\n\n" +
    (r.lines.length ? receipts + ": " + money(t.receipt_total) + " (card " + money(t.card) + ", cash " + money(t.cash_sales) + ")\n" : "No sales\n") +
    (r.expenses.length ? r.expenses.length + " expense(s): " + money(parseFloat(t.drawer_expenses) + parseFloat(t.other_expenses)) + "\n" : "") +
    (t.difference !== null ? "Cash difference " + dsSigned(t.difference) + "\n" : "") +
    "\nStock is deducted now. Take the employee's cash into your drawer.");
  if (!ok) return;
  var btn = document.getElementById("sheetApproveBtn");
  btn.disabled = true;
  apiPost("/daysheets/" + r.id + "/approve", {}).then(function(res) {
    var refs = res.receipt_refs || [];
    alert(res.code + " approved." + (refs.length > 1 ? "\nReceipts " + refs.join(", ") + ": " + money(res.totals.receipt_total) :
      res.receipt_ref ? "\nReceipt " + res.receipt_ref + ": " + money(res.totals.receipt_total) : ""));
    dsAfterDecision(res.id);
    if (typeof posRefreshStock === "function") posRefreshStock();
  }).catch(function(err) {
    btn.disabled = false;
    alert("Not approved: " + err.message);
  });
}

function dsReturn(r) {
  var note = prompt("Return " + r.code + " to " + r.created_by_name + ".\nWhat should they fix? (they will see this note)");
  if (note === null) return;
  if (!note.trim()) { alert("Write a note for the employee."); return; }
  apiPost("/daysheets/" + r.id + "/return", { note: note.trim() }).then(function(res) {
    alert(res.code + " was returned to " + res.created_by_name + ".");
    dsAfterDecision(res.id);
  }).catch(function(err) {
    alert("Not returned: " + err.message);
  });
}

function dsAfterDecision(id) {
  openSheetReview(id);
  loadDaySheets();
}

safeAddListener("sheetReviewBack", function() { closePanel("sheetReviewPanel"); });
