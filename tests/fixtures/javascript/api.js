/**
 * API client module.
 */

import { formatDate, parseDate } from './utils';
import * as lodash from 'lodash';
import axios from 'axios';

const fs = require('fs');
const { promisify } = require('util');

/**
 * Fetch user data from the API.
 */
export async function fetchUser(id) {
    const response = await axios.get(`/api/users/${id}`);
    return response.data;
}

/**
 * Fetch all users.
 */
export async function fetchAllUsers() {
    const response = await axios.get('/api/users');
    return lodash.sortBy(response.data, 'name');
}

/**
 * User API client class.
 */
export class UserApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    async getUser(id) {
        return fetchUser(id);
    }

    formatUserDate(user) {
        return formatDate(user.createdAt);
    }
}

export default UserApiClient;
