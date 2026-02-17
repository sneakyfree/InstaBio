/**
 * InstaBio Shared Utilities
 * Common functions used across all frontend pages.
 */

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} str - Raw string that may contain HTML
 * @returns {string} Escaped string safe for innerHTML
 */
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

/**
 * P3: Centralized auth guard.
 * Redirects to /onboard if no token is found (except on public pages).
 */
(function authGuard() {
    const publicPaths = ['/', '/onboard', '/index.html'];
    const path = window.location.pathname;
    const token = localStorage.getItem('instabio_token');

    if (!token && !publicPaths.includes(path)) {
        window.location.href = '/onboard';
    }
})();

/**
 * P2: Shared navigation bar with logout.
 * Call renderNav('pageName') to insert the nav bar at the top of the page.
 * pageName should be one of: 'record', 'vault', 'biography', 'journal', 'progress'
 */
function renderNav(activePage) {
    const pages = [
        { id: 'record', label: '🎙️ Record', href: '/record' },
        { id: 'vault', label: '📁 Vault', href: '/vault' },
        { id: 'biography', label: '📖 Biography', href: '/biography' },
        { id: 'journal', label: '📓 Journal', href: '/journal' },
        { id: 'progress', label: '📊 Progress', href: '/progress' },
    ];

    const userName = localStorage.getItem('instabio_name') || '';

    const nav = document.createElement('nav');
    nav.id = 'instabio-nav';
    nav.innerHTML = `
        <style>
            #instabio-nav {
                background: #2D5016;
                padding: 12px 20px;
                position: sticky;
                top: 0;
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 8px;
            }
            #instabio-nav .nav-brand {
                color: white;
                font-size: 22px;
                font-weight: 700;
                text-decoration: none;
            }
            #instabio-nav .nav-links {
                display: flex;
                gap: 4px;
                align-items: center;
                flex-wrap: wrap;
            }
            #instabio-nav .nav-link {
                color: rgba(255,255,255,0.85);
                text-decoration: none;
                padding: 8px 12px;
                border-radius: 8px;
                font-size: 16px;
                transition: background 0.2s;
                white-space: nowrap;
            }
            #instabio-nav .nav-link:hover {
                background: rgba(255,255,255,0.15);
            }
            #instabio-nav .nav-link.active {
                background: rgba(255,255,255,0.25);
                color: white;
                font-weight: 600;
            }
            #instabio-nav .nav-logout {
                color: rgba(255,255,255,0.7);
                background: none;
                border: 1px solid rgba(255,255,255,0.3);
                padding: 8px 14px;
                border-radius: 8px;
                font-size: 15px;
                cursor: pointer;
                transition: all 0.2s;
            }
            #instabio-nav .nav-logout:hover {
                background: rgba(255,255,255,0.15);
                color: white;
            }
        </style>
        <a href="/" class="nav-brand">🌿 InstaBio</a>
        <div class="nav-links">
            ${pages.map(p => `<a href="${p.href}" class="nav-link${p.id === activePage ? ' active' : ''}">${p.label}</a>`).join('')}
            <button class="nav-logout" onclick="instabioLogout()" title="Sign out">Sign Out</button>
        </div>
    `;

    document.body.insertBefore(nav, document.body.firstChild);

    // Auto-detect active page from URL pathname
    const currentPath = window.location.pathname.replace(/\/+$/, '') || '/';
    nav.querySelectorAll('.nav-link').forEach(link => {
        const linkPath = new URL(link.href).pathname.replace(/\/+$/, '') || '/';
        if (linkPath === currentPath) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

/**
 * Logout handler: invalidate token on server, clear local data, redirect home.
 */
async function instabioLogout() {
    const token = localStorage.getItem('instabio_token');
    try {
        await fetch('/api/logout', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
    } catch (e) {
        // Server might be down — that's fine, still clear locally
    }
    localStorage.removeItem('instabio_token');
    localStorage.removeItem('instabio_name');
    localStorage.removeItem('instabio_user_id');
    window.location.href = '/';
}
