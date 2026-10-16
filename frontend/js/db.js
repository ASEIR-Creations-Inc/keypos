/* IndexedDB Module — Offline Storage for KEYPOS */
/* Android 6 compatible — no arrow functions, no const/let */

var DB = (function() {
  var DB_NAME = "keypos_db";
  var DB_VERSION = 2;
  var db = null;

  function open(callback) {
    var request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = function(e) {
      var database = e.target.result;
      var txn = e.target.transaction;

      if (!database.objectStoreNames.contains("sync_queue")) {
        var store = database.createObjectStore("sync_queue", {keyPath: "id", autoIncrement: true});
        store.createIndex("synced", "synced", {unique: false});
      }
      if (e.oldVersion < 2) {
        /* v1 stored booleans, which are not valid IndexedDB keys, so the synced
           index could never be queried. v2 stores 0/1 and migrates old rows. */
        var queue = txn.objectStore("sync_queue");
        queue.openCursor().onsuccess = function(ev) {
          var cursor = ev.target.result;
          if (!cursor) return;
          var row = cursor.value;
          row.synced = row.synced ? 1 : 0;
          row.dead = row.dead ? 1 : 0;
          cursor.update(row);
          cursor.continue();
        };
      }
      
      if (!database.objectStoreNames.contains("products")) {
        database.createObjectStore("products", {keyPath: "id"});
      }
      
      if (!database.objectStoreNames.contains("categories")) {
        database.createObjectStore("categories", {keyPath: "id"});
      }
      
      if (!database.objectStoreNames.contains("held_orders")) {
        database.createObjectStore("held_orders", {keyPath: "id", autoIncrement: true});
      }
    };
    
    request.onsuccess = function(e) {
      db = e.target.result;
      if (callback) callback(null, db);
    };
    
    request.onerror = function(e) {
      if (callback) callback(e.target.error);
    };
  }

  function makeClientRef() {
    /* Unique per action attempt-set: generated once when queued, sent on every retry,
       so the server can answer a repeated push from the queue instead of re-processing. */
    return getDeviceId() + "-" + Date.now().toString(36) + "-" + Math.random().toString(36).substr(2, 6);
  }

  function addToSyncQueue(actionType, payload, callback, clientRef) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("sync_queue", "readwrite");
    var store = tx.objectStore("sync_queue");
    var item = {
      action_type: actionType,
      payload: payload,
      synced: 0,
      dead: 0,
      attempts: 0,
      client_ref: clientRef || makeClientRef(),
      auth_token: getToken(),
      created_at: new Date().toISOString(),
      device_id: getDeviceId()
    };
    var req = store.add(item);
    req.onsuccess = function() {
      if (callback) callback(null, req.result);
    };
    req.onerror = function() {
      if (callback) callback(req.error);
    };
  }

  function getPendingSync(callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("sync_queue", "readonly");
    var store = tx.objectStore("sync_queue");
    var index = store.index("synced");
    var req = index.getAll(0);
    req.onsuccess = function() {
      var items = (req.result || []).filter(function(it) { return !it.dead; });
      if (callback) callback(null, items);
    };
    req.onerror = function() {
      if (callback) callback(req.error);
    };
  }

  /* Items the server kept rejecting: stop retrying them, but keep them visible. */
  var MAX_ATTEMPTS = 8;

  function markFailed(id, callback) {
    if (!db) { if (callback) callback(new Error("DB not open")); return; }
    var tx = db.transaction("sync_queue", "readwrite");
    var store = tx.objectStore("sync_queue");
    var getReq = store.get(id);
    getReq.onsuccess = function() {
      var item = getReq.result;
      if (!item) { if (callback) callback(null); return; }
      item.attempts = (item.attempts || 0) + 1;
      if (item.attempts >= MAX_ATTEMPTS) item.dead = 1;
      var putReq = store.put(item);
      putReq.onsuccess = function() { if (callback) callback(null); };
      putReq.onerror = function() { if (callback) callback(putReq.error); };
    };
    getReq.onerror = function() { if (callback) callback(getReq.error); };
  }

  function getQueueCounts(callback) {
    if (!db) { if (callback) callback(new Error("DB not open"), null); return; }
    var tx = db.transaction("sync_queue", "readonly");
    var store = tx.objectStore("sync_queue");
    var req = store.index("synced").getAll(0);
    req.onsuccess = function() {
      var pending = 0;
      var dead = 0;
      var items = req.result || [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].dead) dead++; else pending++;
      }
      if (callback) callback(null, { pending: pending, dead: dead });
    };
    req.onerror = function() { if (callback) callback(req.error, null); };
  }

  function markSynced(id, callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("sync_queue", "readwrite");
    var store = tx.objectStore("sync_queue");
    var getReq = store.get(id);
    getReq.onsuccess = function() {
      var item = getReq.result;
      if (!item) { callback(new Error("Item not found")); return; }
      item.synced = 1;
      var putReq = store.put(item);
      putReq.onsuccess = function() {
        if (callback) callback(null);
      };
      putReq.onerror = function() {
        if (callback) callback(putReq.error);
      };
    };
    getReq.onerror = function() {
      if (callback) callback(getReq.error);
    };
  }

  function cacheProducts(products, callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("products", "readwrite");
    var store = tx.objectStore("products");
    store.clear();
    for (var i = 0; i < products.length; i++) {
      store.put(products[i]);
    }
    tx.oncomplete = function() {
      if (callback) callback(null);
    };
    tx.onerror = function() {
      if (callback) callback(tx.error);
    };
  }

  function getCachedProducts(callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("products", "readonly");
    var store = tx.objectStore("products");
    var req = store.getAll();
    req.onsuccess = function() {
      if (callback) callback(null, req.result);
    };
    req.onerror = function() {
      if (callback) callback(req.error);
    };
  }

  function cacheCategories(categories, callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("categories", "readwrite");
    var store = tx.objectStore("categories");
    store.clear();
    for (var i = 0; i < categories.length; i++) {
      store.put(categories[i]);
    }
    tx.oncomplete = function() {
      if (callback) callback(null);
    };
    tx.onerror = function() {
      if (callback) callback(tx.error);
    };
  }

  function getCachedCategories(callback) {
    if (!db) { callback(new Error("DB not open")); return; }
    var tx = db.transaction("categories", "readonly");
    var store = tx.objectStore("categories");
    var req = store.getAll();
    req.onsuccess = function() {
      if (callback) callback(null, req.result);
    };
    req.onerror = function() {
      if (callback) callback(req.error);
    };
  }

  function saveCart(cartItems, callback) {
    if (!db) { if (callback) callback(new Error("DB not open")); return; }
    var tx = db.transaction("held_orders", "readwrite");
    var store = tx.objectStore("held_orders");
    var item = { id: 1, items: cartItems, saved_at: new Date().toISOString() };
    var req = store.put(item);
    req.onsuccess = function() { if (callback) callback(null); };
    req.onerror = function() { if (callback) callback(req.error); };
  }
  function getCart(callback) {
    if (!db) { if (callback) callback(new Error("DB not open"), null); return; }
    var tx = db.transaction("held_orders", "readonly");
    var store = tx.objectStore("held_orders");
    var req = store.get(1);
    req.onsuccess = function() {
      if (callback) callback(null, req.result ? req.result.items : []);
    };
    req.onerror = function() { if (callback) callback(req.error, null); };
  }

  function getDeviceId() {
    var id = localStorage.getItem("device_id");
    if (!id) {
      id = "device_" + Math.random().toString(36).substr(2, 9);
      localStorage.setItem("device_id", id);
    }
    return id;
  }

  function saveTicket(cartItems, callback) {
    if (!db) { if (callback) callback(new Error("DB not open")); return; }
    var tx = db.transaction("held_orders", "readwrite");
    var store = tx.objectStore("held_orders");
    var item = { id: Date.now(), items: cartItems, saved_at: new Date().toISOString() };
    var req = store.put(item);
    req.onsuccess = function() { if (callback) callback(null, item.id); };
    req.onerror = function() { if (callback) callback(req.error); };
  }
  function getTickets(callback) {
    if (!db) { if (callback) callback(new Error("DB not open"), null); return; }
    var tx = db.transaction("held_orders", "readonly");
    var store = tx.objectStore("held_orders");
    var req = store.getAll();
    req.onsuccess = function() {
      var tickets = (req.result || []).filter(function(t) { return t.id !== 1; });
      if (callback) callback(null, tickets);
    };
    req.onerror = function() { if (callback) callback(req.error, null); };
  }
  function deleteTicket(id, callback) {
    if (!db) { if (callback) callback(new Error("DB not open")); return; }
    var tx = db.transaction("held_orders", "readwrite");
    var store = tx.objectStore("held_orders");
    var req = store.delete(id);
    req.onsuccess = function() { if (callback) callback(null); };
    req.onerror = function() { if (callback) callback(req.error); };
  }
  return {
    open: open,
    addToSyncQueue: addToSyncQueue,
    getPendingSync: getPendingSync,
    markSynced: markSynced,
    markFailed: markFailed,
    getQueueCounts: getQueueCounts,
    cacheProducts: cacheProducts,
    getCachedProducts: getCachedProducts,
    cacheCategories: cacheCategories,
    getCachedCategories: getCachedCategories,
    saveCart: saveCart,
    getCart: getCart,
    saveTicket: saveTicket,
    getTickets: getTickets,
    deleteTicket: deleteTicket,
    getDeviceId: getDeviceId,
    makeClientRef: makeClientRef
  };
})();