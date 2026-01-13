/**
 * TypeScript type definitions.
 */

export interface User {
    id: string;
    name: string;
    email: string;
    createdAt: Date;
}

export interface ApiResponse<T> {
    data: T;
    status: number;
    message: string;
}

export type UserId = string | number;

export type UserRole = 'admin' | 'user' | 'guest';

export enum Status {
    Active = 'active',
    Inactive = 'inactive',
    Pending = 'pending'
}

/**
 * User service class.
 */
export class UserService {
    private users: User[] = [];

    async getUser(id: UserId): Promise<User | null> {
        return this.users.find(u => u.id === id) ?? null;
    }

    async createUser(data: Partial<User>): Promise<User> {
        const user: User = {
            id: String(Date.now()),
            name: data.name || '',
            email: data.email || '',
            createdAt: new Date()
        };
        this.users.push(user);
        return user;
    }
}

export default UserService;
