/* Change VERSION for every mobile asset release. Never cache customer data. */
const VERSION = 'bzh-mobile-v8';
const OFFLINE = '/aplikace/offline';
const ASSETS = [OFFLINE, '/static/pwa/mobile.css', '/static/pwa/mobile.js', '/static/pwa/navigation.js', '/static/pwa/push.js', '/static/pwa/rewards.js',
  '/static/pwa/icon-v3-192.png', '/static/pwa/icon-v3-512.png', '/static/pwa/icon-maskable-v3.png', '/static/pwa/apple-touch-v3.png', '/static/pwa/badge-v3.png'];
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
  if (/^\/(admin|api|logout|cart|checkout|objednavka|platba|reset-password|affiliate|rezervace|muj-ucet|odmeny|pozvat|a)(\/|$)/.test(url.pathname)) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () =>
      (await caches.match(OFFLINE)) || new Response('Jste offline. Připojte se k internetu.', {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}})));
    return;
  }
  if (ASSETS.includes(url.pathname)) {
    // Versioned app-shell assets are immutable for this release: cache-first avoids
    // a network round trip on every tab change. A new VERSION invalidates them.
    event.respondWith((async () => {
      const cached = await caches.match(url.pathname);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok) {
        const cache = await caches.open(VERSION);
        await cache.put(url.pathname, response.clone());
      }
      return response;
    })());
  }
});

self.addEventListener('message', event => {
  if (event.data?.type === 'MOBILE_VERSION' && event.ports[0]) event.ports[0].postMessage(VERSION);
});
self.addEventListener('push', event => {
  let data={};
  try { data=event.data ? event.data.json() : {}; } catch { data={}; }
  const title=typeof data.title === 'string' && data.title.trim() ? data.title : 'Nová zpráva';
  const body=typeof data.body === 'string' ? data.body : 'Máme pro vás novinku. Otevřete aplikaci.';
  let url='/kalendar';
  try {
    const target=new URL(data.url || url,self.location.origin);
    if(target.origin === self.location.origin && !target.username && !target.password) url=target.pathname+target.search+target.hash;
  } catch {}
  event.waitUntil(self.registration.showNotification(title, {body,icon:'/static/pwa/icon-v3-192.png',badge:'/static/pwa/badge-v3.png',tag:typeof data.tag==='string' ? data.tag : undefined,data:{url}}));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  let target=new URL('/kalendar',self.location.origin);
  try {const candidate=new URL(event.notification.data?.url || '/kalendar',self.location.origin); if(candidate.origin===self.location.origin)target=candidate;}catch{}
  event.waitUntil((async()=>{
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    for (const client of windows) {
      if(new URL(client.url).origin===self.location.origin && 'focus' in client) {
        if ('navigate' in client) await client.navigate(target.href);
        return client.focus();
      }
    }
    return self.clients.openWindow(target.href);
  })());
});
