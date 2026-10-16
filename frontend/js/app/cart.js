/* KEYPOS — cart and cart item editor. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Cart Item Edit ── */
function openCartItem(productId) {
  var item = null;
  for (var i = 0; i < POS_STATE.cart.length; i++) {
    if (POS_STATE.cart[i].product_id === productId) { item = POS_STATE.cart[i]; break; }
  }
  if (!item) return;
  var stockQty = 0;
  for (var j = 0; j < POS_STATE.products.length; j++) {
    if (POS_STATE.products[j].id === productId) { stockQty = parseFloat(POS_STATE.products[j].stock_qty) || 0; break; }
  }
  document.getElementById("cartItemProductId").value = productId;
  document.getElementById("cartItemTitle").textContent = item.name;
  document.getElementById("cartItemName").textContent = item.name;
  document.getElementById("cartItemStock").textContent = "Stock available: " + stockQty.toFixed(0);
  document.getElementById("cartItemPrice").value = item.price.toFixed(2);
  document.getElementById("cartItemQty").value = item.qty;
  document.getElementById("cartItemDiscount").value = (item.discount || 0).toFixed(2);
  updateCartItemTotal();
  openPanel("cartItemPanel");
}

function updateCartItemTotal() {
  var price = parseFloat(document.getElementById("cartItemPrice").value) || 0;
  var qty = parseInt(document.getElementById("cartItemQty").value) || 1;
  var discount = parseFloat(document.getElementById("cartItemDiscount").value) || 0;
  var total = (price * qty) - discount;
  var el = document.getElementById("cartItemLineTotal");
  if (el) el.textContent = "Line Total: " + money(total);
}

function applyCartItem() {
  var productId = parseInt(document.getElementById("cartItemProductId").value);
  var price = parseFloat(document.getElementById("cartItemPrice").value) || 0;
  var qty = parseInt(document.getElementById("cartItemQty").value) || 1;
  var discount = parseFloat(document.getElementById("cartItemDiscount").value) || 0;
  if (price <= 0) { alert("Enter a valid price."); return; }
  if (qty <= 0) { alert("Enter a valid quantity."); return; }
  if (discount < 0 || discount > roundCents(price * qty)) { alert("Discount must be between 0 and the line amount."); return; }
  for (var i = 0; i < POS_STATE.cart.length; i++) {
    if (POS_STATE.cart[i].product_id === productId) {
      POS_STATE.cart[i].price = price;
      POS_STATE.cart[i].qty = qty;
      POS_STATE.cart[i].discount = discount;
      break;
    }
  }
  DB.saveCart(POS_STATE.cart, function() {});
  posRenderCart();
  closePanel("cartItemPanel");
}

function removeCartItem() {
  var productId = parseInt(document.getElementById("cartItemProductId").value);
  POS_STATE.cart = POS_STATE.cart.filter(function(item) { return item.product_id !== productId; });
  DB.saveCart(POS_STATE.cart, function() {});
  posRenderCart();
  closePanel("cartItemPanel");
}

/* ── Cart ── */
function posAddToCart(productId) {
  var product = null;
  for (var i = 0; i < POS_STATE.products.length; i++) {
    if (POS_STATE.products[i].id === productId) {
      product = POS_STATE.products[i];
      break;
    }
  }
  if (!product) return;
  /* If no sell price, prompt cashier */
  if (!product.sell_price || parseFloat(product.sell_price) === 0) {
    var inputPrice = prompt("Enter sell price for " + product.name + ":");
    if (inputPrice === null) return;
    var parsedPrice = parseFloat(inputPrice);
    if (isNaN(parsedPrice) || parsedPrice <= 0) { alert("Invalid price."); return; }
    product.sell_price = parsedPrice;
  }

  /* Check stock availability */
  var currentQtyInCart = 0;
  for (var c = 0; c < POS_STATE.cart.length; c++) {
    if (POS_STATE.cart[c].product_id === productId) {
      currentQtyInCart = POS_STATE.cart[c].qty;
      break;
    }
  }
  if (parseFloat(product.stock_qty) <= currentQtyInCart) {
    alert("Insufficient stock for " + product.name);
    return;
  }
  var existing = null;
  for (var j = 0; j < POS_STATE.cart.length; j++) {
    if (POS_STATE.cart[j].product_id === productId) {
      existing = POS_STATE.cart[j];
      break;
    }
  }

  if (existing) {
    existing.qty = existing.qty + 1;
  } else {
    POS_STATE.cart.push({
      product_id: product.id,
      name: product.name,
      price: parseFloat(product.sell_price) || 0,
      qty: 1,
      discount: 0
    });
  }

  posRenderCart();
}

function posUpdateQty(productId, delta) {
  var item = null;
  for (var i = 0; i < POS_STATE.cart.length; i++) {
    if (POS_STATE.cart[i].product_id === productId) {
      item = POS_STATE.cart[i];
      break;
    }
  }
  if (!item) return;

  item.qty = item.qty + delta;
  if (item.qty <= 0) {
    var newCart = [];
    for (var j = 0; j < POS_STATE.cart.length; j++) {
      if (POS_STATE.cart[j].product_id !== productId) {
        newCart.push(POS_STATE.cart[j]);
      }
    }
    POS_STATE.cart = newCart;
  }

  posRenderCart();
}

function posClearCart() {
  posResetCart();
}

function posApplyDiscount(pct) {
  POS_STATE.cartDiscountPct = pct;
  posRenderCart();
}

function posRenderCart() {
  if (!DOM.orderList) return;
  var list = DOM.orderList;
  var html = "";

  for (var i = 0; i < POS_STATE.cart.length; i++) {
    var item = POS_STATE.cart[i];
    var itemDiscount = posLineDiscount(item);
    var lineTotal = posLineGross(item) - itemDiscount;

    var stockQty2 = 0;
    for (var si4 = 0; si4 < POS_STATE.products.length; si4++) {
      if (POS_STATE.products[si4].id === item.product_id) { stockQty2 = parseFloat(POS_STATE.products[si4].stock_qty) || 0; break; }
    }
    var overStock2 = item.qty > stockQty2;
    html += '<div class="order-line" data-id="' + item.product_id + '" onclick="openCartItem(' + item.product_id + ')" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #F0F0F0;">';
    html += '<div style="flex:1;">';
    html += '<div style="font-weight:600;font-size:14px;color:#212121;">' + escapeHtml(item.name) + '</div>';
    html += '<div style="font-size:12px;color:#9E9E9E;margin-top:2px;">' + money(item.price) + ' ea · Qty: <span style="font-weight:700;color:' + (overStock2 ? '#F44336' : '#212121') + ';">' + item.qty + '</span></div>';
    html += '</div>';
    html += '<div style="text-align:right;">';
    html += '<div style="font-weight:700;font-size:15px;color:' + (overStock2 ? '#F44336' : '#4CAF50') + ';">' + money(lineTotal) + '</div>';
    if (itemDiscount > 0) html += '<div style="font-size:11px;color:#FF9800;">-' + money(itemDiscount) + '</div>';
    html += '</div>';
    html += '</div>';
    html += '<div class="qty-controls">';
    html += '<button class="qty-btn minus" data-id="' + item.product_id + '">−</button>';
    var stockQty = 0;
    for (var si = 0; si < POS_STATE.products.length; si++) {
      if (POS_STATE.products[si].id === item.product_id) {
        stockQty = parseFloat(POS_STATE.products[si].stock_qty) || 0;
        break;
      }
    }
    var qtyColor = item.qty > stockQty ? 'color:#F44336;font-weight:700;' : '';
    html += '<span class="qty-display" style="' + qtyColor + '">' + item.qty + '</span>';
    html += '<button class="qty-btn plus" data-id="' + item.product_id + '">+</button>';
    html += '</div>';
    html += '<div class="line-total" data-id="' + item.product_id + '">' + money(lineTotal) + '</div>';
    html += '</div>';
  }

  if (html === "") {
    html = '<div style="text-align:center;padding:40px;color:#9E9E9E;">No items added</div>';
  }
  list.innerHTML = html;

  var totals = posCartTotals();
  var grandTotal = totals.total;

  if (DOM.subtotalEl) {
    DOM.subtotalEl.textContent = money(totals.subtotal);
  }
  if (DOM.discountEl) {
    var pctLabel = POS_STATE.cartDiscountPct > 0 ? " (" + roundCents(POS_STATE.cartDiscountPct * 100) + "% off)" : "";
    DOM.discountEl.textContent = (totals.discount > 0 ? "-" : "") + money(totals.discount) + pctLabel;
  }
  if (DOM.taxEl) {
    DOM.taxEl.textContent = money(totals.tax);
  }
  if (DOM.grandTotalEl) {
    DOM.grandTotalEl.textContent = money(grandTotal);
  }
  var totalItems = 0;
  for (var j = 0; j < POS_STATE.cart.length; j++) {
    totalItems += POS_STATE.cart[j].qty;
  }
  if (DOM.orderCount) {
    DOM.orderCount.textContent = totalItems + " items";
  }
  if (DOM.cartBadge) {
    DOM.cartBadge.textContent = totalItems;
  }
  if (DOM.chargeBtn) {
    var hasStockIssue = false;
    for (var si2 = 0; si2 < POS_STATE.cart.length; si2++) {
      var cartItem = POS_STATE.cart[si2];
      for (var si3 = 0; si3 < POS_STATE.products.length; si3++) {
        if (POS_STATE.products[si3].id === cartItem.product_id) {
          if (cartItem.qty > parseFloat(POS_STATE.products[si3].stock_qty)) {
            hasStockIssue = true;
          }
          break;
        }
      }
    }
    DOM.chargeBtn.textContent = hasStockIssue ? "STOCK ISSUE" : "CHARGE " + money(grandTotal);
    DOM.chargeBtn.disabled = POS_STATE.cart.length === 0 || hasStockIssue;
  }

  /* Bind qty buttons */
  var qtyBtns = list.querySelectorAll(".qty-btn");
  for (var k = 0; k < qtyBtns.length; k++) {
    qtyBtns[k].addEventListener("click", (function(btn) {
      return function() {
        var pid = parseInt(btn.getAttribute("data-id"));
        var delta = btn.classList.contains("plus") ? 1 : -1;
        posUpdateQty(pid, delta);
      };
    })(qtyBtns[k]));
  }

  /* Persist cart to IndexedDB */
  DB.saveCart(POS_STATE.cart, function(err) {
    if (err) console.error("Save cart error:", err);
  });
}
safeAddListener("cartItemBack", function() { closePanel("cartItemPanel"); });
safeAddListener("applyCartItemBtn", function() { applyCartItem(); });
safeAddListener("removeCartItemBtn", function() { removeCartItem(); });
safeAddListener("cartItemMinus", function() { var q = document.getElementById("cartItemQty"); q.value = Math.max(1, parseInt(q.value||1)-1); updateCartItemTotal(); });
safeAddListener("cartItemPlus", function() { var q = document.getElementById("cartItemQty"); q.value = parseInt(q.value||1)+1; updateCartItemTotal(); });
var cartItemPriceEl = document.getElementById("cartItemPrice");
var cartItemQtyEl = document.getElementById("cartItemQty");
var cartItemDiscEl = document.getElementById("cartItemDiscount");
if (cartItemPriceEl) cartItemPriceEl.addEventListener("input", updateCartItemTotal);
if (cartItemQtyEl) cartItemQtyEl.addEventListener("input", updateCartItemTotal);
if (cartItemDiscEl) cartItemDiscEl.addEventListener("input", updateCartItemTotal);
