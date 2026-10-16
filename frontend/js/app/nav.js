/* KEYPOS — screen navigation, slide-in panels, logout and start-up. Loaded last by pos.html. */
/* Android 6 compatible — no arrow functions, no const/let */

var APP = {
  currentScreen: "pos",
  panelStack: []
};

var SCREEN_TITLES = {
  pos: "KEYPOS",
  daysheet: "DAY SHEET",
  importexport: "IMPORT / EXPORT"
};

function showScreen(name) {
  var screens = document.querySelectorAll(".screen");
  for (var i = 0; i < screens.length; i++) {
    screens[i].classList.remove("active");
  }
  var target = document.getElementById("screen-" + name);
  if (target) {
    target.classList.add("active");
    APP.currentScreen = name;
  }
  document.getElementById("headerTitle").textContent = SCREEN_TITLES[name] || name.toUpperCase();
  closeDrawer();
  if (name === "inventory" && typeof loadInventory === "function") loadInventory();
  if (name === "purchases" && typeof loadPurchases === "function") loadPurchases();
  if (name === "reports") { initReportDates(); if (typeof loadReports === "function") loadReports(); }
  if (name === "customers" && typeof loadCustomers === "function") loadCustomers();
  if (name === "expenses" && typeof loadExpenses === "function") loadExpenses();
  if (name === "daysheet" && typeof loadDaySheets === "function") loadDaySheets();
  if (name === "users" && typeof loadUsers === "function") loadUsers();
  if (name === "settings" && typeof loadSettingsForm === "function") loadSettingsForm();
}

/* Opening a panel that is already open (e.g. a refreshed ledger) brings it to the top instead of stacking it twice. */
function openPanel(panelId) {
  var panel = document.getElementById(panelId);
  if (panel) {
    var open = APP.panelStack.indexOf(panelId);
    if (open > -1) APP.panelStack.splice(open, 1);
    panel.classList.add("active");
    panel.style.zIndex = 250 + APP.panelStack.length;
    APP.panelStack.push(panelId);
  }
}

function closePanel(panelId) {
  var panel = document.getElementById(panelId);
  if (panel) {
    panel.classList.remove("active");
    panel.style.zIndex = "";
  }
  var idx = APP.panelStack.indexOf(panelId);
  if (idx > -1) APP.panelStack.splice(idx, 1);
}

function closeTopPanel() {
  if (APP.panelStack.length > 0) {
    var top = APP.panelStack[APP.panelStack.length - 1];
    closePanel(top);
  }
}

function openDrawer() {
  document.getElementById("drawer").classList.add("open");
  document.getElementById("drawerOverlay").classList.add("visible");
}

function closeDrawer() {
  document.getElementById("drawer").classList.remove("open");
  document.getElementById("drawerOverlay").classList.remove("visible");
}

function initReportDates() {
  document.getElementById("reportFrom").value = monthStartStr();
  document.getElementById("reportTo").value = localDateStr();
}

// Drawer
document.getElementById("drawerToggle").addEventListener("click", openDrawer);
document.getElementById("drawerClose").addEventListener("click", closeDrawer);
document.getElementById("drawerOverlay").addEventListener("click", closeDrawer);

// Nav links
var navLinks = document.querySelectorAll(".nav-link");
for (var i = 0; i < navLinks.length; i++) {
  (function(link) {
    link.addEventListener("click", function(e) {
      e.preventDefault();
      showScreen(link.getAttribute("data-screen"));
      closeDrawer();
    });
  })(navLinks[i]);
}

// Cart icon
document.getElementById("cartIcon").addEventListener("click", function() {
  openPanel("cartPanel");
});
document.getElementById("cartBack").addEventListener("click", function() {
  closePanel("cartPanel");
});

// Payment back
document.getElementById("paymentBack").addEventListener("click", function() {
  closePanel("paymentPanel");
});

// Panel backs
document.getElementById("productPanelBack").addEventListener("click", function() {
  closePanel("productPanel");
});
document.getElementById("customerPanelBack").addEventListener("click", function() {
  closePanel("customerPanel");
});
document.getElementById("ledgerBack").addEventListener("click", function() {
  closePanel("customerLedgerPanel");
});
document.getElementById("purchaseFormBack").addEventListener("click", function() {
  closePanel("purchaseFormPanel");
});
document.getElementById("expenseFormBack").addEventListener("click", function() {
  closePanel("expenseFormPanel");
});
document.getElementById("reportDetailBack").addEventListener("click", function() {
  closePanel("reportDetailPanel");
});
document.getElementById("zReportBack").addEventListener("click", function() {
  closePanel("zReportPanel");
});
document.getElementById("userFormBack").addEventListener("click", function() {
  closePanel("userFormPanel");
});

// Add expense FAB
if (document.getElementById("addExpenseBtn")) {
  document.getElementById("addExpenseBtn").addEventListener("click", function() {
    document.getElementById("expenseDate").value = localDateStr();
    document.getElementById("expenseAmount").value = "";
    document.getElementById("expenseDesc").value = "";
    document.getElementById("expenseCategory").value = "";
    document.getElementById("expenseDrawer").checked = false;
    if (typeof EXPENSE_LINES !== "undefined") { EXPENSE_LINES = []; }
    if (typeof renderExpenseLines === "function") renderExpenseLines();
    var saveBtn = document.getElementById("saveExpenseBtn");
    if (saveBtn) { saveBtn.removeAttribute("data-edit-id"); saveBtn.textContent = "SAVE ALL"; }
    var titleEl = document.getElementById("expenseFormTitle");
    if (titleEl) titleEl.textContent = "Add Expenses";
    document.getElementById("deleteExpenseBtn").style.display = "none";
    openPanel("expenseFormPanel");
  });
}

// Add user FAB
if (document.getElementById("addUserBtn")) {
  document.getElementById("addUserBtn").addEventListener("click", function() {
    document.getElementById("editUserId").value = "";
    document.getElementById("editUserName").value = "";
    document.getElementById("editUserUsername").value = "";
    document.getElementById("editUserPassword").value = "";
    document.getElementById("editUserPassword").placeholder = "At least 8 characters";
    document.getElementById("editUserRole").value = "cashier";
    if (typeof applyRoleDefaultsToForm === "function") applyRoleDefaultsToForm("cashier");
    document.getElementById("userFormTitle").textContent = "Add User";
    openPanel("userFormPanel");
  });
}
var editUserRoleEl = document.getElementById("editUserRole");
if (editUserRoleEl) {
  editUserRoleEl.addEventListener("change", function() {
    var editId = document.getElementById("editUserId").value;
    if (!editId && typeof applyRoleDefaultsToForm === "function") {
      applyRoleDefaultsToForm(this.value);
    }
  });
}

// Logout
document.getElementById("logoutBtn").addEventListener("click", function(e) {
  e.preventDefault();
  signOut();
});

// Register SW
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(function() {});
}

// Boot POS
document.addEventListener("DOMContentLoaded", function() {
  posInit();
});
