/**
 * Main entry point.
 */

import React from 'react';
import { formatDate, log } from './utils';
import api, { fetchUser, UserApiClient } from './api';

// Re-export utilities for external use
export { formatDate, log } from './utils';
export { fetchUser } from './api';

// Re-export with alias
export { UserApiClient as Client } from './api';

// Re-export default with alias
export { default as apiClient } from './api';

/**
 * Main application class.
 */
export default class App {
    constructor() {
        this.api = new UserApiClient('https://api.example.com');
    }

    async start() {
        log('Starting application...');
        const user = await fetchUser(1);
        console.log('User:', user);
    }
}
