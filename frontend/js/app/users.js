/* KEYPOS — users. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Users ── */
function loadUsers() {
  apiGet("/users").then(function(data) {
    var users = data || [];
    var list = document.getElementById("usersList");
    var empty = document.getElementById("usersEmpty");
    if (!users || users.length === 0) {
      if (list) list.innerHTML = "";
      if (empty) empty.style.display = "block";
      return;
    }
    if (empty) empty.style.display = "none";
    var html = "<table style='width:100%;border-collapse:collapse;'><tbody>";
    for (var i = 0; i < users.length; i++) {
      var u = users[i];
      var roleColor = u.role === "admin" ? "#F44336" : u.role === "manager" ? "#FF9800" : u.role === "sheet" ? "#1565C0" : "#4CAF50";
      html += "<tr style='border-bottom:1px solid #F5F5F5;cursor:pointer;' onclick='editUser(" + u.id + ")'>";
      html += "<td class='wrap-name' style='padding:10px 6px;'><div style='font-weight:500;'>" + escapeHtml(u.name) + "</div><div style='font-size:12px;color:#9E9E9E;'>@" + escapeHtml(u.username) + "</div></td>";
      html += "<td style='padding:10px 6px;'><span class='role-badge' style='background:" + roleColor + ";'>" + (u.role === "sheet" ? "day sheet" : u.role || "") + "</span>" +
        (u.is_active ? "" : "<div style='color:#F44336;font-size:12px;margin-top:4px;'>Inactive</div>") + "</td>";
      if (POS_STATE.user && POS_STATE.user.id === u.id) {
        html += "<td style='padding:10px 6px;font-size:12px;color:#9E9E9E;white-space:nowrap;'>you</td>";
      } else if (u.is_active) {
        html += "<td style='padding:10px 6px;'><button class='inv-action-btn' style='color:#D32F2F;border-color:#EF9A9A;' onclick='event.stopPropagation();deleteUser(" + u.id + ")'>DEACTIVATE</button></td>";
      } else {
        html += "<td style='padding:10px 6px;'><button class='inv-action-btn' style='color:#2E7D32;border-color:#A5D6A7;' onclick='event.stopPropagation();reactivateUser(" + u.id + ")'>REACTIVATE</button></td>";
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    if (list) list.innerHTML = html;
  }).catch(function() {
    var list = document.getElementById("usersList");
    if (list) list.innerHTML = "<div style='padding:20px;text-align:center;color:#F44336;'>Failed to load users</div>";
  });
}

var USER_ROLE_DEFAULTS = {
  sheet: { can_edit_price:false, can_refund:false, can_discount:false, can_approve_sheets:false, inventory_access:"none", purchases_access:"none", reports_access:"none", customers_access:"none", expenses_access:"none", users_access:"none" },
  cashier: { can_edit_price:false, can_refund:false, can_discount:false, can_approve_sheets:false, inventory_access:"read", purchases_access:"none", reports_access:"own", customers_access:"read", expenses_access:"own", users_access:"none" },
  manager: { can_edit_price:true, can_refund:true, can_discount:true, can_approve_sheets:false, inventory_access:"read", purchases_access:"read", reports_access:"team", customers_access:"full", expenses_access:"team", users_access:"none" },
  admin: { can_edit_price:true, can_refund:true, can_discount:true, can_approve_sheets:true, inventory_access:"full", purchases_access:"full", reports_access:"full", customers_access:"full", expenses_access:"full", users_access:"full" }
};

function applyRoleDefaultsToForm(role) {
  var d = USER_ROLE_DEFAULTS[role];
  if (!d) return;
  document.getElementById("permEditPrice").checked = d.can_edit_price;
  document.getElementById("permRefund").checked = d.can_refund;
  document.getElementById("permDiscount").checked = d.can_discount;
  document.getElementById("permApproveSheets").checked = d.can_approve_sheets;
  document.getElementById("accessInventory").value = d.inventory_access;
  document.getElementById("accessPurchases").value = d.purchases_access;
  document.getElementById("accessReports").value = d.reports_access;
  document.getElementById("accessCustomers").value = d.customers_access;
  document.getElementById("accessExpenses").value = d.expenses_access;
  document.getElementById("accessUsers").value = d.users_access;
}

function editUser(id) {
  apiGet("/users").then(function(users) {
    var user = null;
    for (var i = 0; i < users.length; i++) {
      if (users[i].id === id) { user = users[i]; break; }
    }
    if (!user) return;
    document.getElementById("editUserId").value = id;
    document.getElementById("editUserName").value = user.name || "";
    document.getElementById("editUserUsername").value = user.username || "";
    document.getElementById("editUserPassword").value = "";
    document.getElementById("editUserPassword").placeholder = "Leave blank to keep";
    document.getElementById("editUserRole").value = user.role || "cashier";
    document.getElementById("permEditPrice").checked = user.can_edit_price || false;
    document.getElementById("permRefund").checked = user.can_refund || false;
    document.getElementById("permDiscount").checked = user.can_discount || false;
    document.getElementById("permApproveSheets").checked = user.can_approve_sheets || false;
    document.getElementById("accessInventory").value = user.inventory_access || "read";
    document.getElementById("accessPurchases").value = user.purchases_access || "none";
    document.getElementById("accessReports").value = user.reports_access || "own";
    document.getElementById("accessCustomers").value = user.customers_access || "read";
    document.getElementById("accessExpenses").value = user.expenses_access || "own";
    document.getElementById("accessUsers").value = user.users_access || "none";
    var titleEl = document.getElementById("userFormTitle");
    if (titleEl) titleEl.textContent = "Edit User";
    openPanel("userFormPanel");
  });
}

function saveUser() {
  var id = document.getElementById("editUserId").value;
  var name = document.getElementById("editUserName").value.trim();
  var username = document.getElementById("editUserUsername").value.trim();
  var password = document.getElementById("editUserPassword").value;
  var role = document.getElementById("editUserRole").value;
  if (!name) { alert("Enter a name."); return; }
  if (!username) { alert("Enter a username."); return; }
  if (!id && !password) { alert("Set a password for the new user."); return; }
  if (password && password.length < 8) { alert("The password needs at least 8 characters."); return; }
  var payload = {
    name: name, username: username, role: role,
    can_edit_price: document.getElementById("permEditPrice").checked,
    can_refund: document.getElementById("permRefund").checked,
    can_discount: document.getElementById("permDiscount").checked,
    can_approve_sheets: document.getElementById("permApproveSheets").checked,
    inventory_access: document.getElementById("accessInventory").value,
    purchases_access: document.getElementById("accessPurchases").value,
    reports_access: document.getElementById("accessReports").value,
    customers_access: document.getElementById("accessCustomers").value,
    expenses_access: document.getElementById("accessExpenses").value,
    users_access: document.getElementById("accessUsers").value
  };
  if (password) payload.password = password;
  var promise = id ? apiPut("/users/" + id, payload) : apiPost("/users", payload);
  promise.then(function() {
    closePanel("userFormPanel");
    loadUsers();
  }).catch(function(err) {
    alert("Failed: " + (err.message || "Error"));
  });
}

function deleteUser(id) {
  if (!confirm("Deactivate this user? They will no longer be able to log in, but their sales and transaction history will be kept.")) return;
  apiDelete("/users/" + id).then(function() {
    loadUsers();
  }).catch(function(err) {
    alert("Failed: " + (err.message || "Error"));
  });
}

function reactivateUser(id) {
  apiPut("/users/" + id, { is_active: true }).then(function() {
    loadUsers();
  }).catch(function(err) {
    alert("Failed: " + (err.message || "Error"));
  });
}
safeAddListener("saveUserBtn", function() { saveUser(); });
