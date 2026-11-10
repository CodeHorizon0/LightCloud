const CACHE_PREFIX = "lightcloud-shell-";
const CACHE_NAME = CACHE_PREFIX + "__BUILD_VERSION__";
const ASSETS = JSON.parse("__PRECACHE_ASSETS__");
const PATHS = new Set(ASSETS);

self.addEventListener("install", function (event) {
  event.waitUntil(
    (async function () {
      try {
        const cache = await caches.open(CACHE_NAME);
        await cache.addAll(
          ASSETS.map(function (path) {
            return new Request(path, { cache: "reload", credentials: "omit" });
          }),
        );
      } catch (error) {
        await caches.delete(CACHE_NAME);
        throw error;
      }
    })(),
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    (async function () {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter(function (name) {
            return name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME;
          })
          .map(function (name) {
            return caches.delete(name);
          }),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  const navigation =
    request.mode === "navigate" &&
    ["/", "/login", "/register"].includes(url.pathname);
  const path = navigation ? "/index.html" : url.pathname;
  // Only build assets enter this cache. Authenticated API responses never do.
  if (!PATHS.has(path)) return;
  event.respondWith(
    (async function () {
      const cache = await caches.open(CACHE_NAME);
      const saved = await cache.match(path);
      if (saved) return saved;
      return fetch(request);
    })(),
  );
});
