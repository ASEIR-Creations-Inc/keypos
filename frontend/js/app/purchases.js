/* KEYPOS — purchase orders. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Purchases ── */
var PURCHASES_STATE = { lines: [], suppliers: [], readOnly: false };

function loadPurchases() {
  if (POS_STATE.products.length === 0) {
    fetchProducts(null, null).then(function(prods) {
      POS_STATE.products = prods || [];
    }).catch(function() {});
  }
  apiGet("/suppliers").then(function(sups) {
    PURCHASES_STATE.suppliers = sups || [];
    var datalist = document.getElementById("supplierSuggestions");
    if (datalist) {
      datalist.innerHTML = PURCHASES_STATE.suppliers.map(function(sup) {
        return "<option value=\"" + escapeHtml(sup.name) + "\">";
      }).join("");
    }
  }).catch(function() {});
  apiGet("/purchases").then(renderPurchasesTable).catch(function(err) {
    var empty = document.getElementById("purchasesEmpty");
    var table = document.getElementById("purchasesTable");
    if (table) table.style.display = "none";
    if (empty) {
      empty.style.display = "block";
      empty.querySelector(".empty-state-text").textContent = "Loading failed: " + (err.message || "Server error");
    }
  });
}

function renderPurchasesTable(orders) {
  var tbody = document.getElementById("purchasesTableBody");
  var table = document.getElementById("purchasesTable");
  var empty = document.getElementById("purchasesEmpty");
  if (!tbody) return;
  if (!orders || orders.length === 0) {
    tbody.innerHTML = "";
    if (table) table.style.display = "none";
    if (empty) {
      empty.style.display = "block";
      empty.querySelector(".empty-state-text").textContent = "No purchases yet";
    }
    return;
  }
  if (table) table.style.display = "";
  if (empty) empty.style.display = "none";
  tbody.innerHTML = orders.map(function(po) {
    var statusColor = po.status === "draft" ? "#F57C00" : "#2E7D32";
    return "<tr class='po-row' onclick='openPurchase(" + po.id + ")'>" +
      "<td><div>" + escapeHtml(po.ref_number) + "</div><div style='font-size:11px;color:#9E9E9E;'>" + escapeHtml(localDateTime(po.created_at).substring(0, 10)) + "</div></td>" +
      "<td>" + escapeHtml(po.supplier_id ? po.supplier_name : "-") + "</td>" +
      "<td class='num'>" + money(po.total_amount) + "</td>" +
      "<td style='color:" + statusColor + ";font-weight:600;'>" + escapeHtml(po.status) + "</td>" +
      "</tr>";
  }).join("");
}

function openPurchaseForm(po) {
  var readOnly = !!po && (po.status !== "draft" || document.body.classList.contains("no-purchases-edit"));
  PURCHASES_STATE.readOnly = readOnly;
  PURCHASES_STATE.lines = po ? po.lines.map(function(l) {
    return { product_id: l.product_id, product: l.product_name, qty: parseFloat(l.qty), unit_cost: parseFloat(l.unit_cost) };
  }) : [];
  document.getElementById("editPurchaseId").value = po ? po.id : "";
  document.getElementById("purchaseFormTitle").textContent = !po ? "New Purchase" : readOnly ? "Purchase " + po.ref_number : "Edit Purchase";
  var supplierEl = document.getElementById("purchaseSupplier");
  supplierEl.value = po && po.supplier_id ? po.supplier_name : "";
  supplierEl.disabled = readOnly;
  document.getElementById("purchaseRef").value = po ? po.ref_number : "";
  document.getElementById("purchaseLineEntry").style.display = readOnly ? "none" : "";
  document.getElementById("purchaseFormFooter").style.display = readOnly ? "none" : "flex";
  document.getElementById("deletePurchaseBtn").style.display = po && !readOnly ? "" : "none";
  clearPurchaseLineInputs();
  renderPurchaseLinesList();
  openPanel("purchaseFormPanel");
}

function openPurchase(id) {
  apiGet("/purchases/" + id).then(openPurchaseForm).catch(function(err) {
    alert("Failed to load purchase: " + (err.message || "Unknown error"));
  });
}

function clearPurchaseLineInputs() {
  var productEl = document.getElementById("lineProduct");
  productEl.value = "";
  productEl.removeAttribute("data-product-id");
  document.getElementById("lineQty").value = "";
  document.getElementById("lineCost").value = "";
  document.getElementById("productDropdown").style.display = "none";
}

function findPurchaseProduct(productEl) {
  var dataId = parseInt(productEl.getAttribute("data-product-id"), 10);
  var name = productEl.value.trim().toLowerCase();
  for (var i = 0; i < POS_STATE.products.length; i++) {
    var p = POS_STATE.products[i];
    if (dataId ? p.id === dataId : (p.name || "").toLowerCase() === name) return p;
  }
  return null;
}

function addPurchaseLine() {
  var productEl = document.getElementById("lineProduct");
  var qty = parseFloat(document.getElementById("lineQty").value) || 0;
  var cost = parseFloat(document.getElementById("lineCost").value) || 0;
  if (!productEl.value.trim()) { alert("Choose a product."); return; }
  if (qty <= 0) { alert("Enter a valid quantity."); return; }
  if (cost <= 0) { alert("Enter a valid unit cost."); return; }
  var product = findPurchaseProduct(productEl);
  if (!product) {
    if (confirm('"' + productEl.value.trim() + '" is not a product yet. Create it now?')) createPurchaseProduct(productEl.value.trim());
    return;
  }
  PURCHASES_STATE.lines.push({ product_id: product.id, product: product.name, qty: qty, unit_cost: cost });
  clearPurchaseLineInputs();
  renderPurchaseLinesList();
}

function removePurchaseLine(index) {
  PURCHASES_STATE.lines.splice(index, 1);
  renderPurchaseLinesList();
}

function renderPurchaseLinesList() {
  var total = 0;
  var html = PURCHASES_STATE.lines.map(function(line, i) {
    var lineTotal = Math.round(line.qty * line.unit_cost * 100) / 100;
    total += lineTotal;
    var removeBtn = PURCHASES_STATE.readOnly ? "" :
      "<button onclick='removePurchaseLine(" + i + ")' style='background:#F44336;color:#fff;border:none;padding:2px 8px;border-radius:4px;font-size:12px;margin-left:8px;'>X</button>";
    return "<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #E0E0E0;'>" +
      "<span>" + escapeHtml(line.product) + " &times; " + line.qty + " @ " + money(line.unit_cost) + "</span>" +
      "<span style='font-weight:600;white-space:nowrap;'>" + money(lineTotal) + removeBtn + "</span>" +
      "</div>";
  }).join("");
  document.getElementById("purchaseLinesList").innerHTML = html;
  document.getElementById("purchaseTotalDisplay").textContent = money(total);
}

/* Matches an existing supplier by name (case-insensitive) or creates a new one. */
function resolveSupplierId(name) {
  if (!name) return Promise.resolve(null);
  var lower = name.toLowerCase();
  for (var i = 0; i < PURCHASES_STATE.suppliers.length; i++) {
    if (PURCHASES_STATE.suppliers[i].name.toLowerCase() === lower) return Promise.resolve(PURCHASES_STATE.suppliers[i].id);
  }
  return apiPost("/suppliers", { name: name }).then(function(sup) {
    PURCHASES_STATE.suppliers.push(sup);
    return sup.id;
  });
}

function savePurchase(post) {
  if (PURCHASES_STATE.lines.length === 0) { alert("Add at least one line."); return; }
  if (post && !confirm("Post this purchase? Stock and cost prices will be updated and it can no longer be edited.")) return;
  var editId = document.getElementById("editPurchaseId").value;
  var btn = document.getElementById(post ? "postPurchaseBtn" : "saveDraftPurchaseBtn");
  var label = btn.textContent;
  btn.disabled = true;
  btn.textContent = post ? "POSTING..." : "SAVING...";
  var lines = PURCHASES_STATE.lines.map(function(l) {
    return { product_id: l.product_id, qty: l.qty, unit_cost: l.unit_cost };
  });
  resolveSupplierId(document.getElementById("purchaseSupplier").value.trim()).then(function(supplierId) {
    var payload = { supplier_id: supplierId, lines: lines };
    return editId ? apiPut("/purchases/" + editId, payload) : apiPost("/purchases", payload);
  }).then(function(po) {
    if (post) return apiPost("/purchases/" + po.id + "/post", {});
  }).then(function() {
    closePanel("purchaseFormPanel");
    loadPurchases();
    if (post) posLoadData();
  }).catch(function(err) {
    alert("Save failed: " + (err.message || "Unknown error"));
  }).then(function() {
    btn.disabled = false;
    btn.textContent = label;
  });
}

function selectPurchaseProduct(p) {
  var productEl = document.getElementById("lineProduct");
  productEl.value = p.name;
  productEl.setAttribute("data-product-id", p.id);
  document.getElementById("productDropdown").style.display = "none";
  document.getElementById("lineQty").focus();
}

/* Opens the product form on top of the purchase; the saved product fills this line. */
function createPurchaseProduct(name) {
  document.getElementById("productDropdown").style.display = "none";
  openProductForm(null, { name: name }, function(saved) {
    POS_STATE.products.push(saved);
    selectPurchaseProduct(saved);
  });
}

function purchaseDropdownItem(text, className, onPick) {
  var div = document.createElement("div");
  div.textContent = text;
  div.className = className;
  div.style.cssText = "padding:12px 16px;cursor:pointer;border-bottom:1px solid #F5F5F5;font-size:14px;";
  div.addEventListener("click", onPick);
  return div;
}

function renderProductDropdown() {
  var productEl = document.getElementById("lineProduct");
  var dropdown = document.getElementById("productDropdown");
  var typed = productEl.value.trim();
  var query = typed.toLowerCase();
  productEl.removeAttribute("data-product-id");
  if (!query) { dropdown.style.display = "none"; return; }
  var exact = false;
  var matches = POS_STATE.products.filter(function(p) {
    var name = (p.name || "").toLowerCase();
    if (name === query) exact = true;
    return name.indexOf(query) !== -1 || (p.sku || "").toLowerCase().indexOf(query) !== -1;
  }).slice(0, 30);
  dropdown.innerHTML = "";
  matches.forEach(function(p) {
    dropdown.appendChild(purchaseDropdownItem(p.name + " (stock " + (parseFloat(p.stock_qty) || 0) + ")", "", function() {
      selectPurchaseProduct(p);
    }));
  });
  if (!exact) {
    dropdown.appendChild(purchaseDropdownItem('+ Create new product "' + typed + '"', "po-new-product", function() {
      createPurchaseProduct(typed);
    }));
  }
  dropdown.style.display = "block";
}

function bindPurchaseForm() {
  safeAddListener("newPurchaseBtn", function() { openPurchaseForm(null); });
  safeAddListener("addPurchaseLineBtn", addPurchaseLine);
  safeAddListener("saveDraftPurchaseBtn", function() { savePurchase(false); });
  safeAddListener("postPurchaseBtn", function() { savePurchase(true); });
  safeAddListener("deletePurchaseBtn", function() {
    deletePurchaseOrder(parseInt(document.getElementById("editPurchaseId").value, 10));
  });
  var productEl = document.getElementById("lineProduct");
  if (productEl) productEl.addEventListener("input", renderProductDropdown);
}

function deletePurchaseOrder(id) {
  if (!confirm("Delete this draft purchase order? This cannot be undone.")) return;
  apiDelete("/purchases/" + id).then(function() {
    if (document.getElementById("editPurchaseId").value === String(id)) closePanel("purchaseFormPanel");
    loadPurchases();
    if (APP.panelStack.indexOf("reportDetailPanel") !== -1) runActiveReport();
  }).catch(function(err) {
    alert("Failed to delete: " + (err.message || "Error"));
  });
}
