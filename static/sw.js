const CACHE = "fitforge-v1";

const SHELL = [
  "/",
  "/dashboard",
  "/static/css/style.css",
  "/static/manifest.json"
];

// Install: cache the app shell
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL))
  );
});

// Activate: wipe old caches
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network first, fall back to cache
// API calls (/api/, /onboarding/, /workout/log etc.) always go to network.
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);

  // Always hit the network for POST requests and API/data routes
  if (e.request.method !== "GET" ||
      url.pathname.startsWith("/api/") ||
      url.pathname.startsWith("/onboarding/") ||
      url.pathname.endsWith("/log") ||
      url.pathname.endsWith("/save") ||
      url.pathname.endsWith("/delete") ||
      url.pathname.endsWith("/evolve") ||
      url.pathname.endsWith("/weight") ||
      url.pathname.endsWith("/theme") ||
      url.pathname.endsWith("/reset")) {
    return;
  }

  // For page and asset requests: try network, fall back to cache
  e.respondWith(
    fetch(e.request)
      .then(res => {
        // Cache fresh responses for next time
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
