import { createApiClient } from '../../src/api/client';
import { ApiError } from '../../src/api/errors';
import { fakeFetch } from '../../test/fakeFetch';

function client(routes: Parameters<typeof fakeFetch>[0], token: string | null = 'tok-123') {
  const fetch = fakeFetch(routes);
  const onUnauthorized = jest.fn();
  const onPasswordChangeRequired = jest.fn();
  const api = createApiClient({
    baseUrl: 'https://api.test/',
    getToken: () => token,
    onUnauthorized,
    onPasswordChangeRequired,
    fetchImpl: fetch.impl,
  });
  return { api, calls: fetch.calls, onUnauthorized, onPasswordChangeRequired };
}

async function caught(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('expected the request to fail');
}

describe('api client', () => {
  it('sends the bearer token and JSON body, and returns the parsed response', async () => {
    const { api, calls } = client({ 'POST /api/tickets': { body: { ticket_id: 'TCK-1' } } });
    const res = await api.post('/api/tickets', { subject: 'Hi' });
    expect(res).toEqual({ ticket_id: 'TCK-1' });
    expect(calls[0].headers.Authorization).toBe('Bearer tok-123');
    expect(calls[0].headers['Content-Type']).toBe('application/json');
    expect(calls[0].body).toEqual({ subject: 'Hi' });
  });

  it('strips a trailing slash from the base URL', async () => {
    const { api } = client({ 'GET /api/meta': { body: {} } });
    expect(api.baseUrl).toBe('https://api.test');
    await api.get('/api/meta');
  });

  it('leaves the token off when asked (sign-in)', async () => {
    const { api, calls } = client({ 'POST /api/auth/login': { body: {} } });
    await api.post('/api/auth/login', {}, { auth: false });
    expect(calls[0].headers.Authorization).toBeUndefined();
  });

  it('lets fetch set the multipart Content-Type for forms', async () => {
    const { api, calls } = client({ 'POST /api/tickets/T/attachments': { body: [] } });
    const form = new FormData();
    form.append('message_id', 'M');
    await api.postForm('/api/tickets/T/attachments', form);
    expect(calls[0].headers['Content-Type']).toBeUndefined();
    expect(calls[0].body).toBe(form);
  });

  it('ends the session on a 401 when a token was sent', async () => {
    const { api, onUnauthorized } = client({
      'GET /api/tickets/mine': { status: 401, body: { detail: 'Invalid or expired token' } },
    });
    const e = await caught(api.get('/api/tickets/mine'));
    expect(e.kind).toBe('unauthorized');
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('treats a 401 without a token as bad credentials, not an expired session', async () => {
    const { api, onUnauthorized } = client(
      { 'POST /api/auth/login': { status: 401, body: { detail: 'Invalid email or password' } } },
      null,
    );
    const e = await caught(api.post('/api/auth/login', {}));
    expect(e.kind).toBe('bad_credentials');
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('reports a forced password change', async () => {
    const { api, onPasswordChangeRequired } = client({
      'GET /api/chats': { status: 403, body: { detail: 'Password change required' } },
    });
    const e = await caught(api.get('/api/chats'));
    expect(e.kind).toBe('password_change_required');
    expect(onPasswordChangeRequired).toHaveBeenCalled();
  });

  it('carries Retry-After on a 429', async () => {
    const { api } = client({
      'POST /api/chats': { status: 429, body: { detail: 'Too many requests' }, headers: { 'Retry-After': '30' } },
    });
    const e = await caught(api.post('/api/chats', { issue: 'x' }));
    expect(e.kind).toBe('rate_limited');
    expect(e.retryAfterSeconds).toBe(30);
  });

  it('maps a fetch failure to a network error', async () => {
    const api = createApiClient({
      baseUrl: 'https://api.test',
      getToken: () => null,
      fetchImpl: (async () => {
        throw new TypeError('Network request failed');
      }) as unknown as typeof fetch,
    });
    expect((await caught(api.get('/api/meta'))).kind).toBe('network');
  });

  it('gives up after the timeout', async () => {
    jest.useFakeTimers();
    try {
      const api = createApiClient({
        baseUrl: 'https://api.test',
        getToken: () => null,
        timeoutMs: 1000,
        fetchImpl: ((_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
          })) as unknown as typeof fetch,
      });
      const pending = caught(api.get('/api/meta'));
      jest.advanceTimersByTime(1000);
      expect((await pending).kind).toBe('timeout');
    } finally {
      jest.useRealTimers();
    }
  });
});
