/* ============================================
   Candy Route Planner - Service Worker
   ============================================ */

var CACHE_NAME = "candy-route-v3";

var PRECACHE_URLS = [
  "/",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/offline.js",
  "/static/manifest.json",
  "/static/icons/favicon.svg",
];

/* ------------------------------------------
   Install: pre-cache static assets
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

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // Static assets: cache-first
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // API calls: network-first with cache fallback
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Page navigations: network-first, offline fallback
  if (event.request.mode === "navigate") {
    event.respondWith(
      networkFirst(event.request).catch(function () {
        return caches.match("/offline");
      })
    );
    return;
  }

  // Everything else: network-first
  event.respondWith(networkFirst(event.request));
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

function networkFirst(request) {
  return fetch(request)
    .then(function (response) {
      if (response.ok) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, clone);
        });
      }
      return response;
    })
    .catch(function () {
      return caches.match(request);
    });
}

/* ------------------------------------------
   Helpers
   ------------------------------------------ */
function isStaticAsset(pathname) {
  var extensions = [
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".webp",
  ];
  var lower = pathname.toLowerCase();
  return extensions.some(function (ext) {
    return lower.endsWith(ext);
  });
}
