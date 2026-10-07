/* Change VERSION for every mobile asset release. Never cache customer data. */
const VERSION = 'bzh-mobile-v1';
const OFFLINE = '/aplikace/offline';
const ASSETS = [OFFLINE, '/static/pwa/mobile.css', '/static/pwa/mobile.js',
  '/static/pwa/icon-192.png', '/static/pwa/icon-512.png', '/static/pwa/icon-maskable.png', '/static/pwa/apple-touch-icon.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(ASSETS)));
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('bzh-mobile-') && key !== VERSION) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('message', event => {
  if (event.data?.type === 'ACTIVATE_UPDATE') self.skipWaiting();
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  // These routes may carry private data or perform changes: pass straight through.
  if (/^\/(admin|api|logout|cart|checkout|objednavka|platba|reset-password|affiliate|rezervace)(\/|$)/.test(url.pathname)) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () =>
      (await caches.match(OFFLINE)) || new Response('Jste offline. Připojte se k internetu.', {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}})));
    return;
  }
  if (ASSETS.includes(url.pathname)) {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response.ok) {
          const cache = await caches.open(VERSION);
          await cache.put(url.pathname, response.clone());
        }
        return response;
      } catch (error) {
        const cached = await caches.match(url.pathname);
        if (cached) return cached;
        throw error;
      }
    })());
  }
});
