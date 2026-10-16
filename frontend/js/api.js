/* POS API Client — KEYPOS Register */
/* Android 6 compatible — no arrow functions, no async/await */

/* The till and the Sheet app share one origin, so each keeps its own login: both can stay open at once. */
var POS_TOKEN_KEY = "pos_token";
var POS_USER_KEY = "pos_user";
var IN_SHEET_APP = window.location.pathname.indexOf("/sheet/") === 0;
var TOKEN_KEY = IN_SHEET_APP ? "sheet_token" : POS_TOKEN_KEY;
var USER_KEY = IN_SHEET_APP ? "sheet_user" : POS_USER_KEY;

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/* The login's claims (user id, expiry). Only read locally; the server checks the signature. */
function tokenClaims(token) {
  try {
    var part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    while (part.length % 4) part += "=";
    return JSON.parse(atob(part));
  } catch (e) {
    return null;
  }
}

function sessionExpired() {
  var claims = tokenClaims(getToken() || "");
  return !claims || !claims.exp || claims.exp * 1000 <= Date.now();
}

/* Keep the session: a signed-in user object without the token itself. */
function saveSession(data) {
  localStorage.setItem(TOKEN_KEY, data.access_token);
  var user = {};
  for (var key in data) {
    if (key !== "access_token") user[key] = data[key];
  }
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/* Sign out of this device only; the till's id, settings and offline queue stay. */
function signOut() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.location.replace("index.html");
}

/* Day Sheet accounts only use the KEYPOS Sheet app (/sheet/). */
function isSheetOnly(user) {
  return !!(user && user.permissions && user.permissions.sheet_only);
}

function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "{}");
  } catch (e) {
    return {};
  }
}

/* A Day Sheet account signed in on the till's login page (or before the split) moves to the Sheet app. */
function adoptSheetSession() {
  if (!IN_SHEET_APP || getToken()) return;
  var token = localStorage.getItem(POS_TOKEN_KEY);
  var user = localStorage.getItem(POS_USER_KEY);
  try {
    if (!token || !isSheetOnly(JSON.parse(user || "{}"))) return;
  } catch (e) {
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, user);
  localStorage.removeItem(POS_TOKEN_KEY);
  localStorage.removeItem(POS_USER_KEY);
}

adoptSheetSession();

function apiHeaders() {
  var token = getToken();
  var headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = "Bearer " + token;
  }
  return headers;
}

/* FastAPI sends detail as a string, or as a list of validation errors (422). */
function apiErrorMessage(data, response) {
  var detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (detail && detail.length) {
    return detail.map(function(d) { return (d.loc || []).slice(1).join(".") + ": " + d.msg; }).join("; ");
  }
  return "Request failed (" + response.status + ")";
}

/* body may be FormData (file uploads); the browser then sets its own Content-Type. */
function apiFetch(method, endpoint, body) {
  var headers = apiHeaders();
  var options = { method: method, headers: headers };
  if (body instanceof FormData) {
    delete headers["Content-Type"];
    options.body = body;
  } else if (body !== undefined) {
    options.body = JSON.stringify(body);
  }
  return fetch("/api" + endpoint, options).catch(function(e) {
    /* fetch itself failed: no response at all (offline, DNS, server down).
       Callers use err.network to decide whether an action can be queued offline. */
    var err = e instanceof Error ? e : new Error(String(e));
    err.network = true;
    throw err;
  }).then(function(r) {
    if (r.status === 401) {
      signOut();
      var expired = new Error("Your session has ended. Please sign in again.");
      expired.signedOut = true;
      throw expired;
    }
    if (!r.ok) {
      return r.json().catch(function() { return null; }).then(function(data) {
        var err = new Error(apiErrorMessage(data, r));
        err.status = r.status;
        throw err;
      });
    }
    return r;
  });
}

function apiRequest(method, endpoint, body) {
  return apiFetch(method, endpoint, body).then(function(r) {
    return r.status === 204 ? null : r.json();
  });
}

/* A request answered with a file: resolves { blob, name, headers }. */
function apiFile(method, endpoint, body) {
  return apiFetch(method, endpoint, body).then(function(r) {
    var match = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
    return r.blob().then(function(blob) {
      return { blob: blob, name: match ? match[1] : "download", headers: r.headers };
    });
  });
}

/* Hand a downloaded file to the browser's Downloads. */
function saveBlob(blob, name) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
}

function apiGet(endpoint) {
  return apiRequest("GET", endpoint);
}

function apiPost(endpoint, body) {
  return apiRequest("POST", endpoint, body);
}

function apiPut(endpoint, body) {
  return apiRequest("PUT", endpoint, body);
}

function apiDelete(endpoint) {
  return apiRequest("DELETE", endpoint);
}

/* ── Domain-specific helpers (free functions for pos.js) ── */

function changePassword(currentPassword, newPassword) {
  return apiPost("/auth/password", { current_password: currentPassword, new_password: newPassword });
}

function fetchProducts(search, category_id, _unused) {
  var q = "?is_active=true";
  if (search) q += "&search=" + encodeURIComponent(search);
  if (category_id != null && category_id !== "") q += "&category_id=" + category_id;
  return apiGet("/products" + q);
}

function fetchCategories() {
  return apiGet("/categories");
}

function getCurrentShift() {
  return apiGet("/shifts/current");
}

function openShift(openingFloat) {
  return apiPost("/shifts/open", {opening_float: openingFloat});
}

function closeShift(closingCash) {
  return apiPost("/shifts/close", {closing_cash: closingCash});
}

function createTransaction(txnData) {
  return apiPost("/transactions", txnData);
}

function getHeldTransactions() {
  return apiGet("/transactions/held");
}

function resumeTransaction(txnId) {
  return apiPost("/transactions/" + txnId + "/resume", {});
}

/* Refunds always cover the whole receipt and require a reason. */
function refundTransaction(txnId, reason) {
  return apiPost("/transactions/" + txnId + "/refund", { reason: reason });
}

/* Stock corrections: send either change (+/-) or counted_qty, always with a reason. */
function adjustStock(productId, payload) {
  return apiPost("/products/" + productId + "/adjust-stock", payload);
}

function getShifts(limit) {
  return apiGet("/shifts?limit=" + (limit || 20));
}

function getShiftReport(shiftId) {
  return apiGet("/shifts/" + shiftId + "/report");
}

function getCustomers(searchStr) {
  return apiGet("/customers?search=" + encodeURIComponent(searchStr || ""));
}

function getSalesReport(fromDate, toDate) {
  return apiGet("/reports/sales-summary?from_date=" + fromDate + "&to_date=" + toDate);
}

function getPnlReport(fromDate, toDate) {
  return apiGet("/reports/pnl?from_date=" + fromDate + "&to_date=" + toDate);
}

function getInventoryValue() {
  return apiGet("/reports/inventory-value");
}

function getLowStock() {
  return apiGet("/reports/low-stock");
}

function getPriceEditReport(fromDate, toDate) {
  return apiGet("/reports/price-edits?from_date=" + fromDate + "&to_date=" + toDate);
}