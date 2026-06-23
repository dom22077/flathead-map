// Minimal service worker — enables "Add to Home Screen" / standalone app.
// Caches only the static shell (icon, manifest). Parcel data and map tiles
// always come from the network (data is private; tiles are cross-origin).
const CACHE = 'parcels-shell-v1';
const SHELL = ['/static/icon.png', '/static/manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Only handle same-origin static shell from cache; everything else hits network.
  if (url.origin === location.origin && SHELL.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
