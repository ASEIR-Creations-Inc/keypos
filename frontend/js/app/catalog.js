/* KEYPOS — products and categories. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Load Products & Categories ── */
function posLoadData() {
  fetchCategories().then(function(cats) {
    POS_STATE.categories = [ { id: 0, name: "ALL" } ].concat(cats || []);
    posRenderCategories();
    DB.cacheCategories(POS_STATE.categories, function(err) {
      if (err) console.error("Cache categories error:", err);
    });
  }).catch(function(err) {
    console.error("Failed to load categories:", err);
    DB.getCachedCategories(function(err, cached) {
      if (!err && cached) {
        POS_STATE.categories = [ { id: 0, name: "ALL" } ].concat(cached);
      } else {
        POS_STATE.categories = [ { id: 0, name: "ALL" } ];
      }
      posRenderCategories();
    });
  });

  fetchProducts(null, null, undefined).then(function(prods) {
    POS_STATE.products = prods || [];
    posRenderProducts();
    posCacheProducts();
  }).catch(function(err) {
    console.error("Failed to load products:", err);
    DB.getCachedProducts(function(err, cached) {
      if (!err && cached && cached.length > 0) {
        POS_STATE.products = cached;
        posRenderProducts();
      }
    });
  });
}

/* Updates stock levels only, keeping prices typed at the till for this session. */
function posRefreshStock() {
  fetchProducts(null, null, undefined).then(function(prods) {
    var stockById = {};
    for (var i = 0; i < (prods || []).length; i++) stockById[prods[i].id] = prods[i].stock_qty;
    for (var j = 0; j < POS_STATE.products.length; j++) {
      var p = POS_STATE.products[j];
      if (stockById.hasOwnProperty(p.id)) p.stock_qty = stockById[p.id];
    }
    posRenderCart();
  }).catch(function() {});
}

function posCacheProducts() {
  DB.cacheProducts(POS_STATE.products, function(err) {
    if (err) console.error("Cache products error:", err);
  });
}

/* ── Render Categories ── */
function posRenderCategories() {
  if (!DOM.catBar) return;
  var bar = DOM.catBar;
  var html = "";
  for (var i = 0; i < POS_STATE.categories.length; i++) {
    var c = POS_STATE.categories[i];
    var cls = c.id === POS_STATE.selectedCategoryId ? "active" : "";
    html += '<button class="cat-btn ' + cls + '" data-id="' + c.id + '" data-name="' + escapeHtml(c.name) + '">' + escapeHtml(c.name) + '</button>';
  }
  bar.innerHTML = html;

  /* Bind category buttons */
  var buttons = bar.querySelectorAll(".cat-btn");
  for (var j = 0; j < buttons.length; j++) {
    buttons[j].addEventListener("click", (function(btn) {
      return function() {
        var allBtns = bar.querySelectorAll(".cat-btn");
        for (var k = 0; k < allBtns.length; k++) {
          allBtns[k].classList.remove("active");
        }
        btn.classList.add("active");
        POS_STATE.selectedCategoryId = parseInt(btn.getAttribute("data-id")) || 0;
        posRenderProducts();
      };
    })(buttons[j]));
  }
}

/* ── Render Products ── */
function posRenderProducts() {
  if (!DOM.productGrid) return;
  var grid = DOM.productGrid;
  var search = POS_STATE.searchQuery || "";
  var catId = POS_STATE.selectedCategoryId;

  var filtered = [];
  for (var i = 0; i < POS_STATE.products.length; i++) {
    var p = POS_STATE.products[i];
    var matchCat = true;
    if (catId !== 0) {
      matchCat = (p.category_id === catId);
    }
    var matchSearch = true;
    if (search && search.length > 0) {
      var nameMatch = (p.name || "").toLowerCase().indexOf(search) !== -1;
      var skuMatch = (p.sku || "").toLowerCase().indexOf(search) !== -1;
      var barcodeMatch = (p.barcode || "").toLowerCase().indexOf(search) !== -1;
      matchSearch = nameMatch || skuMatch || barcodeMatch;
    }
    if (matchCat && matchSearch) {
      filtered.push(p);
    }
  }

  var html = "";
  for (var j = 0; j < filtered.length; j++) {
    var item = filtered[j];
    var price = parseFloat(item.sell_price) || 0;
    html += '<div class="product-tile">';
    html += '<div class="tile-inner" data-id="' + item.id + '" tabindex="0">';
    html += '<div class="tile-name">' + escapeHtml(item.name) + '</div>';
    html += '<div class="tile-price">' + money(price) + '</div>';
    html += '</div></div>';
  }

  if (html === "") {
    html = '<div style="width:100%;text-align:center;padding:40px;color:#9E9E9E;">No products found</div>';
  }
  grid.innerHTML = html;

  /* Bind product tile clicks */
  var tiles = grid.querySelectorAll(".product-tile");
  for (var k = 0; k < tiles.length; k++) {
    tiles[k].addEventListener("click", (function(tile) {
      return function() {
        var inner = tile.querySelector(".tile-inner");
        var pid = parseInt(inner.getAttribute("data-id"));
        posAddToCart(pid);
      };
    })(tiles[k]));
  }
}
