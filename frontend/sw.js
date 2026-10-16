/* KEYPOS service worker — keeps the app shell available offline.
   CACHE_NAME and SHELL_FILES are written by tools/stamp.py (content hashes of every
   file the pages load); tests/check-shell.py fails when they are stale. */
var CACHE_NAME = "keypos-shell-653e3bd4";
var SHELL_FILES = [
  "/index.html",
  "/pos.html",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/css/app.css?v=ce98f8af",
  "/js/api.js?v=c31d411a",
  "/js/app/access.js?v=80a930f0",
  "/js/app/cart.js?v=0f4c0241",
  "/js/app/catalog.js?v=b96890c8",
  "/js/app/core.js?v=4237d8a5",
  "/js/app/csv.js?v=dc7c65ae",
  "/js/app/customers.js?v=9abc08b3",
  "/js/app/daysheet.js?v=d4c2611d",
  "/js/app/expenses.js?v=2b13ce96",
  "/js/app/init.js?v=1753329e",
  "/js/app/inventory.js?v=4489dab9",
  "/js/app/nav.js?v=2bb96b49",
  "/js/app/offline.js?v=c569850b",
  "/js/app/payment.js?v=be22a9ab",
  "/js/app/purchases.js?v=4cfb2c9b",
  "/js/app/reports.js?v=37fb0971",
  "/js/app/sales.js?v=a44a5f74",
  "/js/app/settings.js?v=ca7278bd",
  "/js/app/shift.js?v=6473243e",
  "/js/app/tickets.js?v=e483b7d4",
  "/js/app/users.js?v=aa2d1a48",
  "/js/db.js?v=205481ed",
  "/js/sync.js?v=c5396012"
];

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(SHELL_FILES);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(key) {
        /* The Sheet app (/sheet/sw.js) keeps its own keypos-sheet- caches on this origin. */
        if (key.indexOf("keypos-sheet-") !== 0 && key !== CACHE_NAME) return caches.delete(key);
        return null;
      }));
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function(event) {
  var url = new URL(event.request.url);
  /* API calls are never cached — data freshness matters more than offline reads,
     and product/category offline fallbacks come from IndexedDB. */
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf("/api") === 0) return;
  if (url.pathname.indexOf("/sheet/") === 0) return;

  /* Navigations are network-first so a deploy is never masked by a stale cached
     shell; offline they fall back to the cached page. */
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).then(function(response) {
        var copy = response.clone();
        caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, copy); });
        return response;
      }).catch(function() {
        return caches.open(CACHE_NAME).then(function(cache) {
          return cache.match(event.request).then(function(hit) {
            return hit || cache.match("/pos.html");
          });
        });
      })
    );
    return;
  }

  /* Stale-while-revalidate: serve from cache immediately, refresh the cache in
     the background, fall back to cache when the network is down. */
  event.respondWith(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.match(event.request).then(function(cached) {
        var fetched = fetch(event.request).then(function(response) {
          if (response && response.ok) cache.put(event.request, response.clone());
          return response;
        }).catch(function() {
          /* Offline with a version the cache has not seen: an older copy of the
             same file beats a page with no script at all. */
          return cached || cache.match(event.request, {ignoreSearch: true});
        });
        return cached || fetched;
      });
    })
  );
});
