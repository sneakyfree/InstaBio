/**
 * InstaBio i18n — Lightweight Client-Side Translation Engine
 * Supports: en, es, zh, hi, ar (RTL)
 *
 * Usage:
 *   Add data-i18n="key" to any element to translate its textContent.
 *   Add data-i18n-placeholder="key" to translate an input's placeholder.
 *   Add data-i18n-html="key" to translate innerHTML (use sparingly).
 *   Call setLanguage('es') to switch languages.
 *   The engine auto-loads the saved language on page load.
 */

(function () {
    'use strict';

    const SUPPORTED_LANGS = ['en', 'es', 'zh', 'hi', 'ar'];
    const RTL_LANGS = ['ar'];
    const STORAGE_KEY = 'instabio_lang';
    const LANG_LABELS = {
        en: '🇺🇸 English',
        es: '🇪🇸 Español',
        zh: '🇨🇳 中文',
        hi: '🇮🇳 हिन्दी',
        ar: '🇸🇦 العربية'
    };

    let _currentLang = 'en';
    let _translations = {};

    /**
     * Get the user's preferred language (saved or browser default).
     */
    function getPreferredLang() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
        // Try browser language
        const browserLang = (navigator.language || '').slice(0, 2).toLowerCase();
        if (SUPPORTED_LANGS.includes(browserLang)) return browserLang;
        return 'en';
    }

    /**
     * Fetch a language JSON file.
     */
    async function loadTranslations(lang) {
        try {
            const resp = await fetch(`/static/lang/${lang}.json`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            return await resp.json();
        } catch (err) {
            console.warn(`[i18n] Failed to load ${lang}:`, err);
            return {};
        }
    }

    /**
     * Apply loaded translations to the DOM.
     */
    function applyTranslations() {
        // textContent
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (_translations[key] !== undefined) {
                el.textContent = _translations[key];
            }
        });
        // placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            if (_translations[key] !== undefined) {
                el.placeholder = _translations[key];
            }
        });
        // innerHTML (use with care)
        document.querySelectorAll('[data-i18n-html]').forEach(el => {
            const key = el.getAttribute('data-i18n-html');
            if (_translations[key] !== undefined) {
                el.innerHTML = _translations[key];
            }
        });

        // Set <html> lang and dir
        document.documentElement.lang = _currentLang;
        if (RTL_LANGS.includes(_currentLang)) {
            document.documentElement.dir = 'rtl';
        } else {
            document.documentElement.dir = 'ltr';
        }

        // Update any language selector dropdowns on the page
        document.querySelectorAll('.instabio-lang-select').forEach(sel => {
            sel.value = _currentLang;
        });
    }

    /**
     * Switch language globally. Fetches the JSON, applies, and saves.
     */
    async function setLanguage(lang) {
        if (!SUPPORTED_LANGS.includes(lang)) lang = 'en';
        _currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        _translations = await loadTranslations(lang);
        applyTranslations();
    }

    /**
     * Get a translated string by key (for use in JS).
     */
    function t(key, fallback) {
        return _translations[key] || fallback || key;
    }

    /**
     * Build and return a language selector <select> element.
     * Caller can append it wherever needed.
     */
    function createLangSelector(extraStyles) {
        const select = document.createElement('select');
        select.className = 'instabio-lang-select';
        select.setAttribute('aria-label', 'Select language');
        select.style.cssText = `
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
            ${extraStyles || ''}
        `;

        SUPPORTED_LANGS.forEach(code => {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = LANG_LABELS[code];
            opt.style.cssText = 'color: #1A1A1A; background: white;';
            if (code === _currentLang) opt.selected = true;
            select.appendChild(opt);
        });

        select.addEventListener('change', (e) => {
            setLanguage(e.target.value);
        });

        return select;
    }

    // ── Expose globally ──
    window.instabioI18n = {
        setLanguage,
        t,
        createLangSelector,
        applyTranslations,
        LANG_LABELS,
        SUPPORTED_LANGS,
        get currentLang() { return _currentLang; }
    };

    // Alias for convenience
    window.setLanguage = setLanguage;

    // ── Auto-init on page load ──
    const preferred = getPreferredLang();
    _currentLang = preferred;

    // Load translations once DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setLanguage(preferred);
        });
    } else {
        setLanguage(preferred);
    }
})();
