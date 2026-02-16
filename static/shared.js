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
