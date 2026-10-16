/* KEYPOS Sheet service worker (scope /sheet/) — keeps the app available offline.
   CACHE_NAME and SHELL_FILES are written by tools/stamp.py; tests/check-shell.py fails
   when they are stale. Sheets themselves live in the phone's storage (sheet.js). */
var CACHE_NAME = "keypos-sheet-dd1d7d46";
var SHELL_FILES = [
  "/sheet/index.html",
  "/sheet/manifest.json",
  "/sheet/icon-192.png",
  "/sheet/icon-512.png",
  "/js/api.js?v=c31d411a",
  "/sheet/sheet.css?v=d0e0af32",
  "/sheet/sheet.js?v=6686dc70"
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
        if (key.indexOf("keypos-sheet-") === 0 && key !== CACHE_NAME) return caches.delete(key);
        return null;
      }));
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function(event) {
  var url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf("/api") === 0) return;

  /* Network-first for the page, so a deploy is never masked by a stale copy. */
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(function() {
        return caches.open(CACHE_NAME).then(function(cache) {
          return cache.match("/sheet/index.html");
        });
      })
    );
    return;
  }

  /* Versioned scripts and styles: cache first, network when the cache doesn't have it. */
  event.respondWith(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          if (response && response.ok) cache.put(event.request, response.clone());
          return response;
        });
      });
    })
  );
});
