/**
 * Utility functions for the project.
 */

/**
 * Format a date as a string.
 * @param {Date} date - The date to format.
 * @returns {string} Formatted date string.
 */
export function formatDate(date) {
    return date.toISOString().split('T')[0];
}

/**
 * Parse a date string.
 */
export function parseDate(str) {
    return new Date(str);
}

/**
 * Helper for logging.
 */
function logInternal(msg) {
    console.log(`[LOG] ${msg}`);
}

export { logInternal as log };

export default {
    formatDate,
    parseDate
};
