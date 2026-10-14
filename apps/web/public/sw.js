// Mealwright service worker (hand-written, no library): the app shell works offline.
//
// - Built assets (/_next/static/..., icons): cache first. Their names change with every build,
//   so a cached copy is never stale; old ones go when the cache version changes.
// - Page loads (navigations): network first, keeping the last copy of each page for offline.
//   Redirects (signed out -> sign-in) and errors are never kept.
// - Everything else, including the API (another origin) and Clerk, goes straight to the
//   network: user data is never kept here. The app keeps its own offline copies, per user.
// - The page asks for "clear-pages" when the user signs out.

const VERSION = "v1";
const PAGES = `pages-${VERSION}`;
const ASSETS = `assets-${VERSION}`;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([PAGES, ASSETS]);
      for (const name of await caches.keys()) {
        if (!keep.has(name)) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-pages") event.waitUntil(caches.delete(PAGES));
});

function isAsset(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    /^\/(icon[\w-]*\.(svg|png)|apple-touch-icon\.png)$/.test(url.pathname)
  );
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { cacheName: ASSETS });
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(ASSETS);
    await cache.put(request, response.clone());
  }
  return response;
}

const OFFLINE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline</title><style>body{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px;text-align:center;color:#1c2b23;background:#fcfcf9}@media(prefers-color-scheme:dark){body{color:#eef3ee;background:#121a16}}</style></head><body><div><h1>You're offline</h1><p>This page hasn't been opened on this device yet. <a href="/plan/shopping">Your shopping list</a> and <a href="/plan">your plan</a> work offline once visited.</p></div></body></html>`;

async function networkFirst(request) {
  const cache = await caches.open(PAGES);
  try {
    const response = await fetch(request);
    if (response.ok && !response.redirected && response.type === "basic") {
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request, { ignoreSearch: true });
    return cached || new Response(OFFLINE, { headers: { "Content-Type": "text/html" } });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/__clerk")) return;
  if (isAsset(url)) {
    event.respondWith(cacheFirst(request));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
  }
});
