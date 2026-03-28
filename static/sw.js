/* ============================================
   Candy Route Planner - Service Worker
   ============================================ */

var CACHE_NAME = "candy-route-v8";

var PRECACHE_URLS = [
  "/static/css/tailwind.css",
  "/static/js/app.js",
  "/static/js/offline.js",
  "/static/vendor/alpine.min.js",
  "/static/vendor/htmx.min.js",
  "/static/vendor/chart.min.js",
  "/static/manifest.json",
  "/static/icons/favicon.svg",
];

/* ------------------------------------------
   Install: pre-cache static assets only
   ------------------------------------------ */
self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(PRECACHE_URLS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

/* ------------------------------------------
   Activate: clean up old caches
   ------------------------------------------ */
self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (cacheNames) {
      return Promise.all(
        cacheNames
          .filter(function (name) {
            return name.startsWith("candy-route-") && name !== CACHE_NAME;
          })
          .map(function (name) {
            return caches.delete(name);
          })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

/* ------------------------------------------
   Fetch: routing strategies
   ------------------------------------------ */
self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);

  // Only handle same-origin GET requests
  if (url.origin !== self.location.origin) return;
  if (event.request.method !== "GET") return;

  // Static assets: cache-first
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // API calls: network only (don't cache dynamic JSON)
  if (url.pathname.startsWith("/api/")) {
    return; // let browser handle normally
  }

  // Page navigations: network only, no caching
  // This prevents stale CSRF tokens and login redirects
  if (event.request.mode === "navigate") {
    return; // let browser handle normally
  }
});

/* ------------------------------------------
   Strategies
   ------------------------------------------ */
function cacheFirst(request) {
  return caches.match(request).then(function (cached) {
    if (cached) return cached;
    return fetch(request).then(function (response) {
      if (response.ok) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, clone);
        });
      }
      return response;
    });
  });
}

/* ------------------------------------------
   Helpers
   ------------------------------------------ */
function isStaticAsset(pathname) {
  return pathname.startsWith("/static/");
}
