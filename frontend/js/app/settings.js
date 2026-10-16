/* KEYPOS — store settings. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Settings ── */
var STORE_SETTINGS = { store_name: "KEYPOS", currency_symbol: "$", tax_rate: 0, low_stock_threshold: 5 };

/* The last settings seen are kept on the device, so an offline start still shows the
   shop's own currency symbol and tax rate. */
function loadSettings() {
  var cached = localStorage.getItem("store_settings");
  if (cached) {
    try { applySettings(JSON.parse(cached)); } catch (e) { localStorage.removeItem("store_settings"); }
  }
  return apiGet("/settings").then(applySettings).catch(function(err) {
    console.error("Failed to load settings:", err);
  });
}

function applySettings(s) {
  STORE_SETTINGS = s;
  localStorage.setItem("store_settings", JSON.stringify(s));
  POS_STATE.taxRate = (parseFloat(s.tax_rate) || 0) / 100;
  document.title = s.store_name || "KEYPOS";
  var nameEl = document.getElementById("drawerStoreName");
  if (nameEl) nameEl.textContent = s.store_name || "KEYPOS";
  posRenderProducts();
  posRenderCart();
}

var SHOP_TIME_ZONES = [
  "UTC", "Africa/Luanda", "Africa/Maputo", "Africa/Johannesburg", "Africa/Lagos", "Africa/Kinshasa",
  "Africa/Bissau", "Atlantic/Cape_Verde", "Africa/Sao_Tome", "Europe/Lisbon", "Europe/London",
  "America/Sao_Paulo", "Asia/Dili", "Asia/Macau"
];

function fillTimezoneSelect(current) {
  var zones = SHOP_TIME_ZONES.indexOf(current) === -1 ? SHOP_TIME_ZONES.concat([current]) : SHOP_TIME_ZONES;
  var sel = document.getElementById("settingTimezone");
  sel.innerHTML = zones.map(function(z) {
    return '<option value="' + escapeHtml(z) + '">' + escapeHtml(z.replace(/_/g, " ")) + '</option>';
  }).join("");
  sel.value = current;
}

function loadSettingsForm() {
  fillTimezoneSelect(STORE_SETTINGS.timezone || "UTC");
  document.getElementById("settingStoreName").value = STORE_SETTINGS.store_name || "";
  document.getElementById("settingCurrency").value = STORE_SETTINGS.currency_symbol || "";
  document.getElementById("settingTaxRate").value = parseFloat(STORE_SETTINGS.tax_rate) || 0;
  document.getElementById("settingLowStock").value = parseFloat(STORE_SETTINGS.low_stock_threshold) || 0;
}

function saveSettings() {
  var taxRate = parseFloat(document.getElementById("settingTaxRate").value) || 0;
  var lowStock = parseFloat(document.getElementById("settingLowStock").value) || 0;
  if (taxRate < 0 || taxRate > 100) { alert("Tax rate must be between 0 and 100."); return; }
  if (lowStock < 0) { alert("Low stock threshold cannot be negative."); return; }
  var payload = {
    store_name: document.getElementById("settingStoreName").value.trim() || "KEYPOS",
    currency_symbol: document.getElementById("settingCurrency").value.trim() || "$",
    tax_rate: taxRate,
    low_stock_threshold: lowStock,
    timezone: document.getElementById("settingTimezone").value || "UTC"
  };
  apiPut("/settings", payload).then(function(saved) {
    applySettings(saved);
    alert("Settings saved.");
  }).catch(function(err) {
    alert("Failed to save settings: " + (err.message || "Unknown error"));
  });
}
