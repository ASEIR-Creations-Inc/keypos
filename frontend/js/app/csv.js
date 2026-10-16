/* KEYPOS — CSV import and export. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Import / Export ── */
function loadImportExport() {}

function ieDownload(url, filename) {
  apiFile("GET", url).then(function(file) {
    saveBlob(file.blob, filename);
  }).catch(function(err) {
    alert("Download failed: " + (err.message || "Unknown error"));
  });
}

function ieImport(fileInputId, endpoint, label) {
  var fileInput = document.getElementById(fileInputId);
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    alert("Select a CSV file first.");
    return;
  }
  var formData = new FormData();
  formData.append("file", fileInput.files[0]);
  var btn = document.getElementById(fileInputId.replace("File", "Btn"));
  if (btn) { btn.disabled = true; btn.textContent = "IMPORTING..."; }
  apiRequest("POST", endpoint, formData).then(function(data) {
    if (btn) { btn.disabled = false; btn.textContent = "Import " + label; }
    fileInput.value = "";
    var msg = label + " import complete!\nImported: " + (data.imported_count || 0) + "\nUpdated: " + (data.updated_count || 0) + "\nSkipped: " + (data.skipped_count || 0);
    if (data.errors && data.errors.length) { msg += "\n\nErrors:\n" + data.errors.slice(0,3).join("\n"); }
    alert(msg);
  }).catch(function(err) {
    if (btn) { btn.disabled = false; btn.textContent = "Import " + label; }
    alert("Import failed: " + (err.message || "Unknown error"));
  });
}

function deleteAllInventory() {
  var input = prompt("Type DELETE to confirm clearing all products from inventory. This cannot be undone.");
  if (!input || input.trim() !== "DELETE") { alert("Cancelled — you must type DELETE exactly."); return; }
  apiGet("/products").then(function(products) {
    var active = products.filter(function(p) { return p.is_active; });
    if (active.length === 0) { alert("No active products to delete."); return; }
    var promises = active.map(function(p) { return apiDelete("/products/" + p.id); });
    Promise.all(promises).then(function() {
      alert("All " + active.length + " products have been removed.");
      loadInventory();
    }).catch(function(err) {
      alert("Failed to delete all: " + (err.message || "Error"));
    });
  });
}
safeAddListener("exportProductsBtn", function() { ieDownload("/export/products", "products.csv"); });
safeAddListener("exportCustomersBtn", function() { ieDownload("/export/customers", "customers.csv"); });
safeAddListener("exportSalesBtn", function() { ieDownload("/export/sales", "sales.csv"); });
safeAddListener("exportExpensesBtn", function() { ieDownload("/export/expenses", "expenses.csv"); });
safeAddListener("templateProductsBtn", function() { ieDownload("/templates/products", "products_template.csv"); });
safeAddListener("templateCustomersBtn", function() { ieDownload("/templates/customers", "customers_template.csv"); });
safeAddListener("importProductsBtn", function() { ieImport("importProductsFile", "/import/products", "Products"); });
safeAddListener("importCustomersBtn", function() { ieImport("importCustomersFile", "/import/customers", "Customers"); });
