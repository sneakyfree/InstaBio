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
    const publicPaths = ['/', '/onboard', '/index.html', '/share'];
    const path = window.location.pathname;
    const token = localStorage.getItem('instabio_token');

    if (!token && !publicPaths.includes(path) && !path.startsWith('/share/')) {
        window.location.href = '/onboard';
    }
})();

/**
 * P2: Shared navigation bar with logout.
 * Call renderNav('pageName') to insert the nav bar at the top of the page.
 */
function renderNav(activePage) {
    const pages = [
        { id: 'record', label: '🎙️ Record', i18nKey: 'nav.record', href: '/record' },
        { id: 'vault', label: '📁 Vault', i18nKey: 'nav.vault', href: '/vault' },
        { id: 'biography', label: '📖 Biography', i18nKey: 'nav.biography', href: '/biography' },
        { id: 'journal', label: '📓 Journal', i18nKey: 'nav.journal', href: '/journal' },
        { id: 'soul', label: '🕊️ Soul', i18nKey: 'nav.soul', href: '/soul' },
        { id: 'progress', label: '📊 Progress', i18nKey: 'nav.progress', href: '/progress' },
        { id: 'family', label: '👨‍👩‍👧 Family', i18nKey: 'nav.family', href: '/family' },
        { id: 'pricing', label: '💰 Pricing', i18nKey: 'nav.pricing', href: '/pricing' },
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
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 16px;
                transition: background 0.2s;
                white-space: nowrap;
                min-height: 44px;
                display: inline-flex;
                align-items: center;
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
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 15px;
                cursor: pointer;
                transition: all 0.2s;
                min-height: 44px;
                display: inline-flex;
                align-items: center;
            }
            #instabio-nav .nav-logout:hover {
                background: rgba(255,255,255,0.15);
                color: white;
            }
            #instabio-nav .nav-lang-select {
                background: rgba(255,255,255,0.15);
                color: white;
                border: 1px solid rgba(255,255,255,0.35);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 15px;
                cursor: pointer;
                min-height: 44px;
                appearance: none;
                -webkit-appearance: none;
                transition: all 0.2s;
            }
            #instabio-nav .nav-lang-select:hover,
            #instabio-nav .nav-lang-select:focus {
                background: rgba(255,255,255,0.25);
            }
            #instabio-nav .nav-lang-select option {
                color: #1A1A1A;
                background: white;
            }
            @media (max-width: 600px) {
                #instabio-nav {
                    padding: 8px 12px;
                    gap: 4px;
                }
                #instabio-nav .nav-brand {
                    font-size: 18px;
                    width: 100%;
                    text-align: center;
                    padding-bottom: 4px;
                }
                #instabio-nav .nav-links {
                    justify-content: center;
                    gap: 2px;
                }
                #instabio-nav .nav-link {
                    padding: 10px 10px;
                    font-size: 13px;
                    min-height: 44px;
                }
                #instabio-nav .nav-logout {
                    padding: 10px 12px;
                    font-size: 13px;
                    min-height: 44px;
                }
                #instabio-nav .nav-lang-select {
                    padding: 8px 10px;
                    font-size: 13px;
                    min-height: 44px;
                }
            }
        </style>
        <a href="/" class="nav-brand">🌿 InstaBio</a>
        <div class="nav-links">
            ${pages.map(p => `<a href="${p.href}" class="nav-link${p.id === activePage ? ' active' : ''}" data-i18n="${p.i18nKey}">${p.label}</a>`).join('')}
            <button class="nav-logout" onclick="instabioLogout()" title="Sign out" data-i18n="nav.signout">Sign Out</button>
            <span id="nav-lang-slot"></span>
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

    // Insert language selector into nav bar (if i18n.js is loaded)
    function insertNavLangSelector() {
        if (window.instabioI18n) {
            const slot = document.getElementById('nav-lang-slot');
            if (slot && !slot.querySelector('select')) {
                const sel = instabioI18n.createLangSelector('');
                sel.classList.add('nav-lang-select');
                // Remove default inline styles from createLangSelector, use nav CSS instead
                sel.style.cssText = '';
                slot.appendChild(sel);
            }
            // Apply translations to newly-inserted nav elements
            if (window.instabioI18n.applyTranslations) {
                instabioI18n.applyTranslations();
            }
        } else {
            setTimeout(insertNavLangSelector, 100);
        }
    }
    insertNavLangSelector();
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
