import type { ApiClient } from './client';
import type { LoginResponse, Me } from './types';

export const authApi = {
  login: (api: ApiClient, email: string, password: string) =>
    api.post<LoginResponse>('/api/auth/login', { email, password }, { auth: false }),
  me: (api: ApiClient) => api.get<Me>('/api/auth/me'),
  changePassword: (api: ApiClient, currentPassword: string, newPassword: string) =>
    api.post<{ ok: true }>('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
};
