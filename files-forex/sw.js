const CACHE = 'fj-forex-v2';
// Hanya file lokal — './' dihilangkan karena bisa redirect 301 di GitHub Pages
const CORE = [
  './index.html',
  './manifest.json'
];

// File data dinamis — selalu ambil dari network (update harian)
const DYNAMIC = ['news_data.js', 'kalender.json', 'sentimen.json', 'geopolitik.json'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);
  const isDynamic = DYNAMIC.some(f => url.pathname.endsWith(f));

  if (isDynamic) {
    // Network-first: data harian harus selalu fresh
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }

  // Cache-first untuk aset statis; navigation fallback ke index.html
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (res && res.status === 200 && res.type !== 'opaque') {
          caches.open(CACHE).then(c => c.put(e.request, res.clone()));
        }
        return res;
      }).catch(() => {
        if (e.request.mode === 'navigate') return caches.match('./index.html');
        return cached;
      });
    })
  );
});
