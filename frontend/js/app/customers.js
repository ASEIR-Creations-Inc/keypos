/* KEYPOS — customers and account ledger. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Inventory ── */
var CUSTOMERS_STATE = { currentCustomerId: null };

function loadCustomers(search) {
  var query = search || "";
  if (query) { query = "?search=" + encodeURIComponent(query); }
  apiGet("/customers" + query)
    .then(function(data) {
      renderCustomersTable(data.customers || data || []);
    })
    .catch(function(err) {
      var list = document.getElementById("customersList");
      if (list) {
        list.innerHTML = "<div style='text-align:center;padding:40px;color:#9E9E9E;'>Loading failed: " + escapeHtml(err.message || "Server error") + "</div>";
      }
    });
}

function renderCustomersTable(customers) {
  var list = document.getElementById("customersList");
  var empty = document.getElementById("customersEmpty");
  if (!list) return;

  if (!customers || customers.length === 0) {
    list.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }

  if (empty) empty.style.display = "none";

  var html = "<table class='data-table inv-table'>";
  CUSTOMER_NAMES = {};
  for (var i = 0; i < customers.length; i++) {
    var c = customers[i];
    CUSTOMER_NAMES[c.id] = c.name || "";
    var balance = parseFloat(c.balance || c.total_debt || 0);
    var balClass = "";
    if (balance > 0) balClass = "";
    else if (balance < 0) balClass = "color:#2E7D32;";
    else balClass = "color:#757575;";

    html += "<tr class='cust-row' onclick='showCustomerDetail(" + c.id + ")'>";
    html += "<td class='wrap-name'><div style='font-weight:500;'>" + escapeHtml(c.name) + "</div>" +
      "<div class='inv-sub'>" + escapeHtml(c.phone || "") + "</div></td>";
    html += "<td class='num' style='font-weight:600;" + balClass + "'>" + money(Math.abs(balance)) + "</td>";
    html += "</tr>";
  }
  html += "</table>";
  list.innerHTML = html;
}

function showAddCustomer() {
  var titleEl = document.getElementById("customerPanelTitle");
  if (titleEl) titleEl.textContent = "Add Customer";
  document.getElementById("editCustomerId").value = "";
  document.getElementById("editCustomerName").value = "";
  document.getElementById("editCustomerPhone").value = "";
  document.getElementById("editCustomerEmail").value = "";
  document.getElementById("editCustomerCredit").value = "0";
  openPanel("customerPanel");
}

var CUSTOMER_NAMES = {};

function deleteCustomer(id) {
  if (!confirm("Delete customer " + (CUSTOMER_NAMES[id] || "") + "? This cannot be undone.")) return;
  apiDelete("/customers/" + id).then(function() {
    if (CUSTOMERS_STATE.currentCustomerId === id) closePanel("customerLedgerPanel");
    loadCustomers();
  }).catch(function(err) {
    alert("Failed to delete: " + (err.message || "Unknown error"));
  });
}
function editCustomer(id) {
  apiGet("/customers/" + id)
    .then(function(customer) {
      var titleEl = document.getElementById("customerPanelTitle");
      if (titleEl) titleEl.textContent = "Edit Customer";
      document.getElementById("editCustomerId").value = id;
      document.getElementById("editCustomerName").value = customer.name || "";
      document.getElementById("editCustomerPhone").value = customer.phone || "";
      document.getElementById("editCustomerEmail").value = customer.email || "";
      document.getElementById("editCustomerCredit").value = customer.credit_limit || 0;
      openPanel("customerPanel");
    })
    .catch(function(err) {
      alert("Failed to load customer: " + (err.message || "Error"));
    });
}

function saveCustomer() {
  var id = document.getElementById("editCustomerId").value;
  var name = document.getElementById("editCustomerName").value.trim();
  var phone = document.getElementById("editCustomerPhone").value.trim();
  var email = document.getElementById("editCustomerEmail").value.trim();
  var creditLimit = parseFloat(document.getElementById("editCustomerCredit").value) || 0;

  if (!name) { alert("Customer name is required"); return; }

  var payload = { name: name, phone: phone, email: email, credit_limit: creditLimit };
  var promise;

  if (id) {
    promise = apiPut("/customers/" + id, payload);
  } else {
    promise = apiPost("/customers", payload);
  }

  promise.then(function() {
    closePanel("customerPanel");
    loadCustomers();
    if (id && APP.panelStack.indexOf("customerLedgerPanel") > -1) showCustomerDetail(parseInt(id, 10));
  }).catch(function(err) {
    alert("Failed to save customer: " + (err.message || "Error"));
  });
}

var LEDGER_LABELS = { opening: "", sale: "Sale", refund: "Refund", payment: "Payment" };
var LEDGER_COLORS = { sale: "#F44336", refund: "#2E7D32", payment: "#2E7D32" };

function showCustomerDetail(id) {
  CUSTOMERS_STATE.currentCustomerId = id;

  Promise.all([
    apiGet("/customers/" + id),
    apiGet("/customers/" + id + "/ledger")
  ]).then(function(results) {
    var customer = results[0];
    var ledger = results[1].entries || results[1].ledger || results[1] || [];
    var nameEl = document.getElementById("ledgerCustomerName");
    if (nameEl) nameEl.textContent = customer.name || "Ledger";
    var balance = parseFloat(customer.balance || 0);
    var balEl = document.getElementById("ledgerBalance");
    if (balEl) { balEl.textContent = money(Math.abs(balance)); balEl.style.color = balance > 0 ? "#F44336" : "#2E7D32"; }
    var ledgerList = document.getElementById("ledgerEntries");
    if (ledger.length === 0) {
      ledgerList.innerHTML = "<div style='padding:20px;text-align:center;color:#9E9E9E;'>No ledger entries</div>";
    } else {
      var lhtml = "";
      for (var i = 0; i < ledger.length; i++) {
        var entry = ledger[i];
        var amt = parseFloat(entry.amount || 0);
        var amtColor = LEDGER_COLORS[entry.type] || "#757575";
        var when = entry.date ? localDateTime(entry.date) : "";
        lhtml += "<div style='padding:8px 12px;border-bottom:1px solid #F5F5F5;display:flex;justify-content:space-between;'>" +
          "<div><span style='font-weight:500;'>" + escapeHtml(LEDGER_LABELS[entry.type] || entry.type) + " " + escapeHtml(entry.ref) + "</span>" +
          "<span style='display:block;font-size:12px;color:#9E9E9E;'>" + escapeHtml(when) + "</span></div>" +
          "<div style='text-align:right;'><span style='font-weight:600;color:" + amtColor + ";'>" + money(Math.abs(amt)) + "</span>" +
          "<span style='display:block;font-size:12px;color:#9E9E9E;'>Bal " + money(entry.balance_after) + "</span></div></div>";
      }
      ledgerList.innerHTML = lhtml;
    }

    document.getElementById("paymentAmount").value = "";
    openPanel("customerLedgerPanel");
  }).catch(function(err) {
    alert("Failed to load customer details: " + (err.message || "Error"));
  });
}

function receivePayment(customerId) {
  var amount = parseFloat(document.getElementById("paymentAmount").value);
  if (!amount || amount <= 0) { alert("Enter a valid payment amount"); return; }
  var methodEl = document.getElementById("paymentMethod");
  var method = (methodEl && methodEl.value) || "cash";

  apiPost("/customers/" + customerId + "/payment", { amount: amount, method: method })
    .then(function() {
      alert("Payment of " + money(amount) + " (" + method + ") received" +
        (method === "cash" && POS_STATE.shift ? " and added to the drawer." : "."));
      document.getElementById("paymentAmount").value = "";
      showCustomerDetail(customerId);
      loadCustomers();
    })
    .catch(function(err) {
      alert("Payment failed: " + (err.message || "Error"));
    });
}

/* Bind customer button listeners */
safeAddListener("addCustomerBtn", function() { showAddCustomer(); });
safeAddListener("ledgerEditBtn", function() { editCustomer(CUSTOMERS_STATE.currentCustomerId); });
safeAddListener("ledgerDeleteBtn", function() { deleteCustomer(CUSTOMERS_STATE.currentCustomerId); });
safeAddListener("saveCustomerBtn", function() { saveCustomer(); });
safeAddListener("receivePaymentBtn", function() {
  receivePayment(CUSTOMERS_STATE.currentCustomerId);
});

var cancelCustomerBtn = document.getElementById("cancelCustomerBtn");
if (cancelCustomerBtn) { cancelCustomerBtn.addEventListener("click", function() { closePanel("customerPanel"); }); }

var closeCustomerDetailBtn = document.getElementById("closeCustomerDetailBtn");
if (closeCustomerDetailBtn) { closeCustomerDetailBtn.addEventListener("click", function() { document.getElementById("customerDetailModal").style.display = "none"; }); }

var customersSearchInput = document.getElementById("customersSearch");
if (customersSearchInput) { customersSearchInput.addEventListener("keyup", function(e) {
  if (e.keyCode === 13) {
    loadCustomers(customersSearchInput.value);
  }
}); }
