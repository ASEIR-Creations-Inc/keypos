/* KEYPOS — what the signed-in user may use. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* The server enforces every rule (backend/core/access.py); this only hides what it would refuse. */
var ACCESS_LEVELS = { none: 0, own: 1, read: 1, team: 2, full: 3 };

function userPermissions() {
  return (POS_STATE.user && POS_STATE.user.permissions) || {};
}

function canAccess(area, level) {
  var p = userPermissions();
  if (p.is_admin) return true;
  return (ACCESS_LEVELS[p[area + "_access"]] || 0) >= ACCESS_LEVELS[level];
}

function hasPermission(flag) {
  var p = userPermissions();
  return !!(p.is_admin || p["can_" + flag]);
}

/* data-needs on menu links: "area:level", "admin", or "import" (any area it can import into). */
function menuAllowed(need) {
  if (need === "admin") return !!userPermissions().is_admin;
  if (need === "import") return canAccess("inventory", "full") || canAccess("customers", "full") || canAccess("purchases", "full");
  var parts = need.split(":");
  return canAccess(parts[0], parts[1]);
}

/* Body classes that hide controls (see app.css "Permissions"). */
var BODY_RESTRICTIONS = [
  ["no-discount", function() { return !hasPermission("discount"); }],
  ["no-refund", function() { return !hasPermission("refund"); }],
  ["no-inventory-edit", function() { return !canAccess("inventory", "full"); }],
  ["no-purchases-edit", function() { return !canAccess("purchases", "full"); }],
  ["no-customers-edit", function() { return !canAccess("customers", "full"); }]
];

function posApplyPermissions() {
  for (var i = 0; i < BODY_RESTRICTIONS.length; i++) {
    if (BODY_RESTRICTIONS[i][1]()) document.body.classList.add(BODY_RESTRICTIONS[i][0]);
    else document.body.classList.remove(BODY_RESTRICTIONS[i][0]);
  }
  var links = document.querySelectorAll("[data-needs]");
  for (var j = 0; j < links.length; j++) {
    links[j].parentNode.style.display = menuAllowed(links[j].getAttribute("data-needs")) ? "" : "none";
  }
  var nameEl = document.getElementById("cashierName");
  if (nameEl) nameEl.textContent = (POS_STATE.user && (POS_STATE.user.name || POS_STATE.user.username)) || "";
}

/* Pick up permission changes the admin made since this device signed in. */
function posRefreshSession() {
  if (!navigator.onLine) return;
  apiPost("/auth/refresh", {}).then(function(data) {
    if (!data || !data.access_token) return;
    saveSession(data);
    POS_STATE.token = data.access_token;
    POS_STATE.user = getUser();
    if (isSheetOnly(POS_STATE.user)) { window.location.replace("/sheet/"); return; }
    posApplyPermissions();
  }).catch(function() {});
}

/* ── Change own password ── */
function openPasswordPanel() {
  ["pwCurrent", "pwNew", "pwRepeat"].forEach(function(id) { document.getElementById(id).value = ""; });
  openPanel("passwordPanel");
}

function savePassword() {
  var current = document.getElementById("pwCurrent").value;
  var next = document.getElementById("pwNew").value;
  if (next.length < 8) { alert("The new password needs at least 8 characters."); return; }
  if (next !== document.getElementById("pwRepeat").value) { alert("The new passwords don't match."); return; }
  changePassword(current, next).then(function() {
    closePanel("passwordPanel");
    alert("Password changed.");
  }).catch(function(err) {
    alert("Failed: " + (err.message || "Error"));
  });
}

safeAddListener("changePasswordBtn", function(e) {
  if (e) e.preventDefault();
  if (typeof closeDrawer === "function") closeDrawer();
  openPasswordPanel();
});
safeAddListener("passwordBack", function() { closePanel("passwordPanel"); });
safeAddListener("savePasswordBtn", savePassword);
