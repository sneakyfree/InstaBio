/**
 * InstaBio Service Worker
 * Enables offline capability and "Add to Home Screen"
 */

const CACHE_NAME = 'instabio-v6';
const STATIC_ASSETS = [
    '/',
    '/onboard',
    '/record',
    '/vault',
    '/biography',
    '/journal',
    '/progress',
    '/soul',
    '/gift',
    '/family',
    '/pricing',
    '/tv',
    '/consent',
    '/static/index.html',
    '/static/onboard.html',
    '/static/record.html',
    '/static/vault.html',
    '/static/biography.html',
    '/static/journal.html',
    '/static/progress.html',
    '/static/soul.html',
    '/static/gift.html',
    '/static/family.html',
    '/static/pricing.html',
    '/static/tv.html',
    '/static/consent.html',
    '/static/i18n.js',
    '/static/shared.js',
    '/manifest.json'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing InstaBio service worker...');

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[SW] Service worker installed');
                return self.skipWaiting();
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker...');

    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => caches.delete(name))
                );
            })
            .then(() => {
                console.log('[SW] Service worker activated');
                return self.clients.claim();
            })
    );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip API requests - always go to network
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // For navigation requests, try network first, then cache
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .catch(() => {
                    return caches.match(request)
                        .then((response) => {
                            return response || caches.match('/');
                        });
                })
        );
        return;
    }

    // For other requests, cache-first strategy
    event.respondWith(
        caches.match(request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    return cachedResponse;
                }

                return fetch(request)
                    .then((response) => {
                        // Don't cache non-successful responses
                        if (!response || response.status !== 200 || response.type !== 'basic') {
                            return response;
                        }

                        // Clone the response
                        const responseToCache = response.clone();

                        // Cache the fetched response
                        caches.open(CACHE_NAME)
                            .then((cache) => {
                                cache.put(request, responseToCache);
                            });

                        return response;
                    });
            })
    );
});

// Background sync for audio uploads (when back online)
self.addEventListener('sync', (event) => {
    if (event.tag === 'upload-audio-chunks') {
        console.log('[SW] Background sync: uploading queued audio chunks');
        event.waitUntil(uploadQueuedChunks());
    }
});

// Offline upload queue using IndexedDB
async function uploadQueuedChunks() {
    try {
        const db = await openDB();
        const tx = db.transaction('offlineQueue', 'readonly');
        const store = tx.objectStore('offlineQueue');
        const items = await getAllFromStore(store);
        tx.oncomplete = () => db.close();

        for (const item of items) {
            try {
                const formData = new FormData();
                formData.append('audio', item.blob, item.filename);

                const resp = await fetch(`/api/session/${item.sessionUuid}/chunk`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${item.token}` },
                    body: formData
                });

                if (resp.ok) {
                    // Remove from queue on success
                    const delTx = (await openDB()).transaction('offlineQueue', 'readwrite');
                    delTx.objectStore('offlineQueue').delete(item.id);
                    console.log(`[SW] Uploaded queued chunk ${item.id}`);
                }
            } catch (e) {
                console.warn(`[SW] Failed to upload chunk ${item.id}, will retry`, e);
            }
        }
    } catch (e) {
        console.error('[SW] Offline queue error:', e);
    }
}

function openDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('instabio-offline', 1);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('offlineQueue')) {
                db.createObjectStore('offlineQueue', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror = (e) => reject(e.target.error);
    });
}

function getAllFromStore(store) {
    return new Promise((resolve, reject) => {
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

// Push notifications (for future use)
self.addEventListener('push', (event) => {
    if (event.data) {
        const data = event.data.json();

        const options = {
            body: data.body || 'You have a new notification',
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            vibrate: [100, 50, 100],
            data: data.url || '/'
        };

        event.waitUntil(
            self.registration.showNotification(data.title || 'InstaBio', options)
        );
    }
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    event.waitUntil(
        clients.openWindow(event.notification.data || '/')
    );
});

console.log('[SW] InstaBio service worker loaded');
