/**
 * InstaBio Service Worker
 * Enables offline capability and "Add to Home Screen"
 */

const CACHE_NAME = 'instabio-v1';
const STATIC_ASSETS = [
    '/',
    '/onboard',
    '/record',
    '/vault',
    '/static/index.html',
    '/static/onboard.html',
    '/static/record.html',
    '/static/vault.html',
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
        // The main app handles the actual upload via IndexedDB queue
    }
});

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
