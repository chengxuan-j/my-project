// Service Worker：页面导航走「网络优先」，静态资源「缓存优先」，API 不缓存。
// 注意：不要对 HTML 文档做缓存优先，否则发版后客户端会一直加载旧页面/旧 chunk。
const CACHE_NAME = 'elderly-companion-v3';
// 仅预缓存真正不变的静态资源，不再预缓存页面 HTML
const PRECACHE = ['/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 只处理同源 GET 请求
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  // API 请求直接走网络，不缓存
  if (url.pathname.startsWith('/api/')) return;

  // 页面导航：网络优先，失败时回退缓存（保证发版后能拿到最新 HTML）
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return resp;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // 静态资源：缓存优先（文件名带内容哈希，可安全长期缓存）
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((resp) => {
          if (resp.status === 200) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return resp;
        })
    )
  );
});
