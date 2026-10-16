/* KEYPOS — inventory screen. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

var INVENTORY_STATE = {
  products: [],
  categories: [],
  units: [],
  editProductId: null,
  onSaved: null,
  sort: { key: "name", dir: 1 },
  categoryFilter: "",
  stockFilter: ""
};

var INVENTORY_NEW_OPTION = "__new";

var INVENTORY_SORTERS = {
  name: function(p) { return (p.name || "").toLowerCase(); },
  category: function(p) { return (p.category_name || "￿").toLowerCase(); },
  stock: function(p) { return parseFloat(p.stock_qty) || 0; },
  price: function(p) { return parseFloat(p.sell_price) || 0; },
  cost: function(p) { return parseFloat(p.cost_price) || 0; }
};

function formatQty(value) {
  return String(parseFloat(value) || 0);
}

function loadInventory() {
  apiGet("/products?is_active=true")
    .then(function(products) {
      INVENTORY_STATE.products = products || [];
      renderInventoryTable();
    })
    .catch(function() {
      DB.getCachedProducts(function(err, cached) {
        if (!err && cached && cached.length > 0) {
          INVENTORY_STATE.products = cached;
        }
        renderInventoryTable();
      });
    });
  loadProductLookups();
}

/* Categories and units feed the inventory filter and the product form's dropdowns. */
function loadProductLookups() {
  return Promise.all([
    apiGet("/categories").catch(function() { return INVENTORY_STATE.categories; }),
    apiGet("/units").catch(function() { return INVENTORY_STATE.units; })
  ]).then(function(results) {
    INVENTORY_STATE.categories = results[0] || [];
    INVENTORY_STATE.units = results[1] || [];
    fillLookupSelect("editProductCategory", INVENTORY_STATE.categories, "-- No category --", "+ New category...");
    fillLookupSelect("editProductUnit", INVENTORY_STATE.units, "-- No unit --", "+ New unit...");
    fillLookupSelect("inventoryCategoryFilter", INVENTORY_STATE.categories, "All categories", null);
  });
}

function fillLookupSelect(id, items, emptyLabel, newLabel) {
  var sel = document.getElementById(id);
  if (!sel) return;
  var current = sel.value;
  var html = '<option value="">' + escapeHtml(emptyLabel) + '</option>';
  for (var i = 0; i < items.length; i++) {
    html += '<option value="' + items[i].id + '">' + escapeHtml(items[i].name) + '</option>';
  }
  if (newLabel) html += '<option value="' + INVENTORY_NEW_OPTION + '">' + escapeHtml(newLabel) + '</option>';
  sel.innerHTML = html;
  sel.value = current === INVENTORY_NEW_OPTION ? "" : current;
  if (sel.selectedIndex < 0) sel.value = "";
}

/* "+ New ..." in a product-form dropdown: ask for a name, create it, select it. */
function createLookupFromSelect(sel, endpoint, label) {
  sel.value = "";
  var name = prompt("New " + label + " name:");
  name = (name || "").replace(/^\s+|\s+$/g, "");
  if (!name) return;
  apiPost(endpoint, { name: name }).then(function(created) {
    return loadProductLookups().then(function() { sel.value = String(created.id); });
  }).catch(function(err) {
    alert("Could not create " + label + ": " + (err.message || "Unknown error"));
  });
}

function inventoryRowMatches(p, query) {
  if (query && (p.name || "").toLowerCase().indexOf(query) === -1 && (p.sku || "").toLowerCase().indexOf(query) === -1) return false;
  if (INVENTORY_STATE.categoryFilter && String(p.category_id) !== INVENTORY_STATE.categoryFilter) return false;
  var stock = parseFloat(p.stock_qty) || 0;
  if (INVENTORY_STATE.stockFilter === "out") return stock <= 0;
  if (INVENTORY_STATE.stockFilter === "low") return stock > 0 && stock <= (parseFloat(p.low_stock_threshold) || 0);
  return true;
}

function sortInventory(rows) {
  var key = INVENTORY_SORTERS[INVENTORY_STATE.sort.key] || INVENTORY_SORTERS.name;
  var dir = INVENTORY_STATE.sort.dir;
  return rows.sort(function(a, b) {
    var x = key(a);
    var y = key(b);
    if (x < y) return -dir;
    if (x > y) return dir;
    return (a.name || "").toLowerCase() < (b.name || "").toLowerCase() ? -1 : 1;
  });
}

function renderInventorySortHeaders() {
  var heads = document.querySelectorAll("#inventoryTable th[data-sort]");
  for (var i = 0; i < heads.length; i++) {
    var active = heads[i].getAttribute("data-sort") === INVENTORY_STATE.sort.key;
    var arrow = heads[i].querySelector(".sort-arrow");
    if (arrow) arrow.textContent = !active ? "↕" : INVENTORY_STATE.sort.dir > 0 ? "▲" : "▼";
    heads[i].classList.toggle("sorted", active);
  }
}

function stockClass(p) {
  var stock = parseFloat(p.stock_qty) || 0;
  if (stock <= 0) return "stock-out";
  return stock <= (parseFloat(p.low_stock_threshold) || 0) ? "stock-low" : "";
}

function renderInventoryTable() {
  var tbody = document.getElementById("inventoryTableBody");
  var empty = document.getElementById("inventoryEmpty");
  var table = document.getElementById("inventoryTable");
  var count = document.getElementById("inventoryCount");
  var query = ((document.getElementById("inventorySearch") || {}).value || "").toLowerCase();

  if (!tbody) return;
  renderInventorySortHeaders();
  var filtered = sortInventory(INVENTORY_STATE.products.filter(function(p) { return inventoryRowMatches(p, query); }));
  if (count) count.textContent = filtered.length + " / " + INVENTORY_STATE.products.length + " items";

  if (filtered.length === 0) {
    tbody.innerHTML = "";
    if (empty) { empty.style.display = "block"; empty.textContent = "No products found"; }
    if (table) table.style.display = "none";
    return;
  }

  if (empty) empty.style.display = "none";
  if (table) table.style.display = "";

  tbody.innerHTML = filtered.map(function(item) {
    var unit = item.unit_name ? ' <span class="inv-sub">' + escapeHtml(item.unit_name) + '</span>' : "";
    return '<tr class="inv-row" data-id="' + item.id + '">' +
      '<td>' + escapeHtml(item.name) +
        '<div class="inv-sub">' + escapeHtml(item.category_name || "No category") + '</div></td>' +
      '<td class="num ' + stockClass(item) + '">' + formatQty(item.stock_qty) + unit + '</td>' +
      '<td class="num">' + money(item.sell_price) + '</td>' +
      '<td class="num">' + money(item.cost_price) + '</td>' +
      '</tr>';
  }).join("");
}

/* Tapping a row opens the product, as in Loyverse; read-only users can't open it. */
function onInventoryRowTap(e) {
  if (document.body.classList.contains("no-inventory-edit")) return;
  var row = e.target;
  while (row && row.tagName !== "TR") row = row.parentNode;
  if (row && row.getAttribute("data-id")) editProduct(parseInt(row.getAttribute("data-id"), 10));
}

/* Search box, filters and clickable column headers (tap again to reverse). */
function bindInventorySearch() {
  var input = document.getElementById("inventorySearch");
  if (input) input.addEventListener("input", renderInventoryTable);
  var categoryFilter = document.getElementById("inventoryCategoryFilter");
  if (categoryFilter) categoryFilter.addEventListener("change", function() {
    INVENTORY_STATE.categoryFilter = categoryFilter.value;
    renderInventoryTable();
  });
  var stockFilter = document.getElementById("inventoryStockFilter");
  if (stockFilter) stockFilter.addEventListener("change", function() {
    INVENTORY_STATE.stockFilter = stockFilter.value;
    renderInventoryTable();
  });
  var body = document.getElementById("inventoryTableBody");
  if (body) body.addEventListener("click", onInventoryRowTap);
  var heads = document.querySelectorAll("#inventoryTable th[data-sort]");
  for (var i = 0; i < heads.length; i++) {
    heads[i].addEventListener("click", function() {
      var key = this.getAttribute("data-sort");
      INVENTORY_STATE.sort = { key: key, dir: INVENTORY_STATE.sort.key === key ? -INVENTORY_STATE.sort.dir : 1 };
      renderInventoryTable();
    });
  }
}

/* Opens the product form. product = null for a new one; prefill = fields for a new one; onSaved gets the saved product. */
function openProductForm(product, prefill, onSaved) {
  var p = product || prefill || {};
  INVENTORY_STATE.editProductId = product ? product.id : null;
  INVENTORY_STATE.onSaved = onSaved || null;
  document.getElementById("productPanelTitle").textContent = product ? "Edit Product" : "Add Product";
  document.getElementById("productEditActions").style.display = product ? "" : "none";
  document.getElementById("productStockInfo").textContent = product
    ? "In stock: " + formatQty(p.stock_qty) + (p.unit_name ? " " + p.unit_name : "")
    : "";
  document.getElementById("editProductId").value = product ? product.id : "";
  document.getElementById("editProductName").value = p.name || "";
  document.getElementById("editProductSku").value = p.sku || "";
  document.getElementById("editProductBarcode").value = p.barcode || "";
  document.getElementById("editProductPrice").value = product ? (parseFloat(p.sell_price) || "") : "";
  document.getElementById("editProductCost").value = product ? (parseFloat(p.cost_price) || 0).toFixed(2) : "";
  document.getElementById("editProductLowStock").value = product
    ? formatQty(p.low_stock_threshold)
    : (parseFloat(STORE_SETTINGS.low_stock_threshold) || "");
  loadProductLookups().then(function() {
    document.getElementById("editProductCategory").value = p.category_id ? String(p.category_id) : "";
    document.getElementById("editProductUnit").value = p.unit_id ? String(p.unit_id) : "";
  });
  openPanel("productPanel");
  if (!product) document.getElementById("editProductName").focus();
}

function bindAddProduct() {
  safeAddListener("addProductBtn", function() { openProductForm(null, null, null); });
}

function editProduct(id) {
  for (var i = 0; i < INVENTORY_STATE.products.length; i++) {
    if (INVENTORY_STATE.products[i].id === id) {
      openProductForm(INVENTORY_STATE.products[i], null, null);
      return;
    }
  }
}

function saveProduct() {
  var id = document.getElementById("editProductId").value;
  var name = document.getElementById("editProductName").value.trim();
  var categoryId = document.getElementById("editProductCategory").value;
  var unitId = document.getElementById("editProductUnit").value;
  var lowStock = document.getElementById("editProductLowStock").value;

  if (!name) { alert("Product name is required."); return; }

  /* Stock and cost are never sent: they change through STOCK adjustments and posted purchases. */
  var payload = {
    name: name,
    barcode: document.getElementById("editProductBarcode").value.trim() || null,
    sell_price: parseFloat(document.getElementById("editProductPrice").value) || 0,
    category_id: categoryId ? parseInt(categoryId, 10) : null,
    unit_id: unitId ? parseInt(unitId, 10) : null
  };
  if (lowStock !== "") payload.low_stock_threshold = parseFloat(lowStock) || 0;

  var saveBtn = document.getElementById("saveProductBtn");
  saveBtn.disabled = true;
  saveBtn.textContent = "SAVING...";

  var request = id ? apiPut("/products/" + parseInt(id, 10), payload) : apiPost("/products", payload);
  request.then(function(saved) {
    var onSaved = INVENTORY_STATE.onSaved;
    INVENTORY_STATE.onSaved = null;
    closePanel("productPanel");
    loadInventory();
    if (onSaved) onSaved(saved);
  }).catch(function(err) {
    alert("Save failed: " + (err.message || "Unknown error"));
  }).then(function() {
    saveBtn.disabled = false;
    saveBtn.textContent = "SAVE PRODUCT";
  });
}

function deleteProduct(id) {
  if (!confirm("Delete this product?")) return;
  apiDelete("/products/" + id)
    .then(function() {
      if (INVENTORY_STATE.editProductId === id) closePanel("productPanel");
      loadInventory();
    })
    .catch(function(err) {
      alert("Delete failed: " + (err.message || "Unknown error"));
    });
}

/* Stock corrections with an audit trail: counted quantity or a +/- change, reason required. */
function adjustProductStock(id) {
  var product = null;
  for (var i = 0; i < INVENTORY_STATE.products.length; i++) {
    if (INVENTORY_STATE.products[i].id === id) { product = INVENTORY_STATE.products[i]; break; }
  }
  if (!product) return;
  var current = parseFloat(product.stock_qty) || 0;
  var input = prompt('Stock of "' + product.name + '" is ' + current + '.\n\nEnter the COUNTED quantity (e.g. 12),\nor a change with a sign (e.g. -2 or +3):');
  if (input === null) return;
  input = input.replace(/^\s+|\s+$/g, "");
  if (!input) return;
  var value = parseFloat(input);
  if (isNaN(value)) { alert("Enter a number."); return; }
  var payload = /^[+-]/.test(input) ? { change: value } : { counted_qty: value };
  var reason = prompt("Reason (required — it is kept in the audit trail):", "");
  if (reason === null) return;
  reason = reason.replace(/^\s+|\s+$/g, "");
  if (!reason) { alert("A reason is required."); return; }
  payload.reason = reason;
  adjustStock(id, payload).then(function(updated) {
    alert("Stock updated: " + current + " → " + (parseFloat(updated.stock_qty) || 0));
    if (INVENTORY_STATE.editProductId === id) {
      product.stock_qty = updated.stock_qty;
      document.getElementById("productStockInfo").textContent = "In stock: " + formatQty(updated.stock_qty) + (product.unit_name ? " " + product.unit_name : "");
    }
    loadInventory();
    posRefreshStock();
  }).catch(function(err) {
    alert("Adjustment failed: " + (err.message || "Unknown error"));
  });
}

/* Bind save/cancel product modal */
function bindProductModal() {
  document.getElementById("saveProductBtn").addEventListener("click", saveProduct);
  document.getElementById("editProductCategory").addEventListener("change", function() {
    if (this.value === INVENTORY_NEW_OPTION) createLookupFromSelect(this, "/categories", "category");
  });
  document.getElementById("editProductUnit").addEventListener("change", function() {
    if (this.value === INVENTORY_NEW_OPTION) createLookupFromSelect(this, "/units", "unit");
  });
  document.getElementById("productAdjustBtn").addEventListener("click", function() {
    adjustProductStock(INVENTORY_STATE.editProductId);
  });
  document.getElementById("productDeleteBtn").addEventListener("click", function() {
    deleteProduct(INVENTORY_STATE.editProductId);
  });
  document.getElementById("cancelProductBtn").addEventListener("click", function() {
    closePanel("productPanel");
  });
}
safeAddListener("deleteAllInventoryBtn", function() { deleteAllInventory(); });
