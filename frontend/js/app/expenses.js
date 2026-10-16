/* KEYPOS — expenses. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Expenses ── */
var EXPENSES_STATE = { categories: [] };

function loadExpenses() {
  var fromEl = document.getElementById("expenseFrom");
  var toEl = document.getElementById("expenseTo");
  if (fromEl && !fromEl.value) fromEl.value = monthStartStr();
  if (toEl && !toEl.value) toEl.value = localDateStr();
  var from = fromEl ? fromEl.value : "";
  var to = toEl ? toEl.value : "";
  var query = from && to ? "?from_date=" + from + "&to_date=" + to : "";
  apiGet("/expenses" + query).then(function(data) {
    var expenses = data.items || data.expenses || data || [];
    var list = document.getElementById("expensesList");
    var empty = document.getElementById("expensesEmpty");
    if (!expenses || expenses.length === 0) {
      if (list) list.innerHTML = "";
      if (empty) empty.style.display = "block";
      return;
    }
    if (empty) empty.style.display = "none";
    var html = "<table style='width:100%;border-collapse:collapse;'><tbody>";
    for (var i = 0; i < expenses.length; i++) {
      var e = expenses[i];
      var date = e.expense_date || "";
      html += "<tr style='border-bottom:1px solid #F5F5F5;cursor:pointer;' onclick='editExpense(" + e.id + ")'>";
      html += "<td style='padding:10px;'><div style='font-weight:500;'>" + escapeHtml(e.category_name || "Uncategorized") +
        (e.paid_from_drawer ? " <span style='font-size:10px;background:#FF9800;color:#fff;padding:1px 5px;border-radius:3px;'>DRAWER</span>" : "") +
        "</div><div style='font-size:12px;color:#9E9E9E;'>" + date + "</div></td>";
      html += "<td style='padding:10px;color:#757575;font-size:13px;'>" + escapeHtml(e.description) + "</td>";
      html += "<td style='padding:10px;text-align:right;font-weight:600;color:#F44336;'>" + money(e.amount) + "</td>";
      html += "</tr>";
    }
    html += "</tbody></table>";
    if (list) list.innerHTML = html;
  }).catch(function() {
    var list = document.getElementById("expensesList");
    if (list) list.innerHTML = "<div style='padding:20px;text-align:center;color:#F44336;'>Failed to load expenses</div>";
  });
  /* Load categories for form */
  apiGet("/expenses/categories").then(function(data) {
    var cats = data.categories || data || [];
    EXPENSES_STATE.categories = cats;
    var select = document.getElementById("expenseCategory");
    if (select) {
      select.innerHTML = "<option value=''>-- Select --</option>";
      cats.forEach(function(c) {
        var opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = c.name;
        select.appendChild(opt);
      });
    }
  });
}

var EXPENSE_LINES = [];

function addExpenseCategory() {
  var name = prompt("Enter category name:");
  if (!name || !name.trim()) return;
  apiPost("/expenses/categories", { name: name.trim() }).then(function() {
    loadExpenses();
    alert("Category added.");
  }).catch(function(err) {
    alert("Failed: " + (err.message || "Error"));
  });
}

function addExpenseLine() {
  var categoryId = document.getElementById("expenseCategory").value;
  var categoryName = document.getElementById("expenseCategory").options[document.getElementById("expenseCategory").selectedIndex].text;
  var amount = parseFloat(document.getElementById("expenseAmount").value) || 0;
  var desc = document.getElementById("expenseDesc").value.trim();
  var drawer = !!document.getElementById("expenseDrawer").checked;
  if (!categoryId) { alert("Select a category."); return; }
  if (amount <= 0) { alert("Enter a valid amount."); return; }
  EXPENSE_LINES.push({ category_id: parseInt(categoryId), category_name: categoryName, amount: amount, description: desc, paid_from_drawer: drawer });
  document.getElementById("expenseAmount").value = "";
  document.getElementById("expenseDesc").value = "";
  document.getElementById("expenseCategory").value = "";
  renderExpenseLines();
}

function renderExpenseLines() {
  var container = document.getElementById("expenseLinesList");
  var totalEl = document.getElementById("expenseLinesTotal");
  if (!container) return;
  if (EXPENSE_LINES.length === 0) { container.innerHTML = ""; if (totalEl) totalEl.textContent = "Total: " + money(0); return; }
  var total = 0;
  var html = "";
  for (var i = 0; i < EXPENSE_LINES.length; i++) {
    var line = EXPENSE_LINES[i];
    total += line.amount;
    html += "<div style='display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #F5F5F5;align-items:center;'>";
    html += "<div><div style='font-weight:500;font-size:13px;'>" + escapeHtml(line.category_name) +
      (line.paid_from_drawer ? " <span style='font-size:10px;background:#FF9800;color:#fff;padding:1px 5px;border-radius:3px;'>DRAWER</span>" : "") + "</div>";
    html += "<div style='font-size:12px;color:#9E9E9E;'>" + escapeHtml(line.description || "") + "</div></div>";
    html += "<div style='display:flex;align-items:center;gap:8px;'>";
    html += "<span style='font-weight:600;'>" + money(line.amount) + "</span>";
    html += "<button onclick='removeExpenseLine(" + i + ")' style='background:#F44336;color:#fff;border:none;padding:2px 8px;border-radius:4px;font-size:12px;'>X</button>";
    html += "</div></div>";
  }
  container.innerHTML = html;
  if (totalEl) totalEl.textContent = "Total: " + money(total);
}

function removeExpenseLine(index) {
  EXPENSE_LINES.splice(index, 1);
  renderExpenseLines();
}

function saveExpense() {
  var date = document.getElementById("expenseDate").value;
  var saveBtn = document.getElementById("saveExpenseBtn");
  var editId = saveBtn ? saveBtn.getAttribute("data-edit-id") : null;
  if (!date) { alert("Select a date."); return; }
  /* Edit mode - single expense update */
  if (editId) {
    var categoryId = document.getElementById("expenseCategory").value;
    var amount = document.getElementById("expenseAmount").value;
    var desc = document.getElementById("expenseDesc").value;
    var drawerEdit = !!document.getElementById("expenseDrawer").checked;
    if (!categoryId) { alert("Select a category."); return; }
    if (!amount || parseFloat(amount) <= 0) { alert("Enter valid amount."); return; }
    apiPut("/expenses/" + editId, {
      category_id: parseInt(categoryId),
      amount: parseFloat(amount),
      description: desc || "",
      expense_date: date,
      paid_from_drawer: drawerEdit
    }).then(function() {
      saveBtn.removeAttribute("data-edit-id");
      saveBtn.textContent = "SAVE ALL";
      document.getElementById("expenseFormTitle").textContent = "Add Expenses";
      closePanel("expenseFormPanel");
      loadExpenses();
    }).catch(function(err) {
      alert("Failed to update: " + (err.message || "Error"));
    });
    return;
  }
  /* Add mode - multiple lines */
  if (EXPENSE_LINES.length === 0) { alert("Add at least one expense line."); return; }
  var promises = EXPENSE_LINES.map(function(line) {
    return apiPost("/expenses", {
      category_id: line.category_id,
      amount: line.amount,
      description: line.description || "",
      expense_date: date,
      paid_from_drawer: !!line.paid_from_drawer
    });
  });
  Promise.all(promises).then(function() {
    EXPENSE_LINES = [];
    renderExpenseLines();
    closePanel("expenseFormPanel");
    loadExpenses();
  }).catch(function(err) {
    alert("Failed to save: " + (err.message || "Error"));
  });
}

function editExpense(id) {
  apiGet("/expenses/" + id).then(function(e) {
    document.getElementById("expenseDate").value = e.expense_date || "";
    document.getElementById("expenseCategory").value = e.category_id || "";
    document.getElementById("expenseAmount").value = e.amount || "";
    document.getElementById("expenseDesc").value = e.description || "";
    document.getElementById("expenseDrawer").checked = !!e.paid_from_drawer;
    EXPENSE_LINES = [];
    renderExpenseLines();
    var titleEl = document.getElementById("expenseFormTitle");
    if (titleEl) titleEl.textContent = "Edit Expense";
    var saveBtn = document.getElementById("saveExpenseBtn");
    if (saveBtn) { saveBtn.setAttribute("data-edit-id", id); saveBtn.textContent = "UPDATE"; }
    document.getElementById("deleteExpenseBtn").setAttribute("data-id", id);
    document.getElementById("deleteExpenseBtn").style.display = "";
    openPanel("expenseFormPanel");
  }).catch(function(err) {
    alert("Failed to load: " + (err.message || "Error"));
  });
}
function deleteExpense(id) {
  if (!confirm("Delete this expense?")) return;
  apiDelete("/expenses/" + id).then(function() {
    closePanel("expenseFormPanel");
    loadExpenses();
  }).catch(function(err) {
    alert("Failed to delete: " + (err.message || "Error"));
  });
}
safeAddListener("saveExpenseBtn", function() { saveExpense(); });
safeAddListener("addExpenseLineBtn", function() { addExpenseLine(); });
safeAddListener("deleteExpenseBtn", function() { deleteExpense(this.getAttribute("data-id")); });
