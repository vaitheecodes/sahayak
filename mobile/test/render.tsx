import type { ReactElement } from 'react';
import { render } from '@testing-library/react-native';
import { SessionProvider } from '../src/auth/SessionProvider';
import { ThemeProvider } from '../src/theme/ThemeProvider';

export const BASE = 'https://api.test';

export function renderWithSession(ui: ReactElement, fetchImpl: typeof fetch, opts: { timeoutMs?: number } = {}) {
  return render(
    <ThemeProvider>
      <SessionProvider baseUrl={BASE} fetchImpl={fetchImpl} timeoutMs={opts.timeoutMs}>
        {ui}
      </SessionProvider>
    </ThemeProvider>,
  );
}

export async function storeToken(token: string) {
  const SecureStore = jest.requireMock('expo-secure-store');
  await SecureStore.setItemAsync('auth.token', token);
}

export function storedToken(): string | null {
  const secure = jest.requireMock('expo-secure-store') as { __store: Map<string, string> };
  return secure.__store.get('auth.token') ?? null;
}
