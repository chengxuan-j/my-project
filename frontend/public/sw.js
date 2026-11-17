// Service Worker：页面导航走「网络优先」，只缓存带内容哈希的构建产物，API 与 RSC 一律不缓存。
// 注意：
//  1) 不要对 HTML 文档做缓存优先，否则发版后客户端会一直加载旧页面/旧 chunk。
//  2) **不要缓存 RSC 数据请求**（URL 带 ?_rsc=，或带 RSC / Next-Router-Prefetch 头）。
//     这类响应结构与当前构建的 chunk 强绑定，命中旧缓存会让 Next 内部的
//     `parallelRoutes` 变成 null，前端直接抛
//     `TypeError: Cannot read properties of null (reading 'get')` 并白屏。
const CACHE_NAME = 'elderly-companion-v4';
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

  // RSC 数据请求：绝不拦截、绝不缓存（否则见文件顶部注释的崩溃）
  if (
    url.searchParams.has('_rsc') ||
    request.headers.get('RSC') === '1' ||
    request.headers.get('Next-Router-Prefetch') === '1'
  ) {
    return;
  }

  // 只对带内容哈希的构建产物、静态媒体做缓存优先
  const isHashedAsset = url.pathname.startsWith('/_next/static/');
  const isMedia = /\.(png|jpe?g|gif|svg|webp|ico|woff2?|ttf|otf|mp3|wav|webm)$/i.test(url.pathname);
  if (!isHashedAsset && !isMedia) return;

  // 其余请求（含未知的 Next 内部数据请求）一律不接管，交给浏览器默认行为
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
