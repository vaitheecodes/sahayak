// A fetch stand-in: routes are "METHOD /path" -> handler returning
// {status, body, headers}. Unmatched requests fail the test loudly.

export type FakeReply = { status?: number; body?: unknown; headers?: Record<string, string>; bytes?: Uint8Array };
export type FakeRequest = { method: string; path: string; headers: Record<string, string>; body: unknown };
type Handler = FakeReply | ((req: FakeRequest) => FakeReply | Promise<FakeReply>);

export function fakeFetch(routes: Record<string, Handler>) {
  const calls: FakeRequest[] = [];
  const impl = jest.fn(async (url: string, init: RequestInit = {}) => {
    const path = url.replace(/^https?:\/\/[^/]+/, '');
    const method = (init.method ?? 'GET').toUpperCase();
    const headers = (init.headers ?? {}) as Record<string, string>;
    let body: unknown = init.body;
    if (typeof body === 'string') {
      try {
        body = JSON.parse(body);
      } catch {
        // leave as text
      }
    }
    const req = { method, path, headers, body };
    calls.push(req);
    const handler = routes[`${method} ${path}`];
    if (!handler) throw new Error(`fakeFetch: no route for ${method} ${path}`);
    const reply = typeof handler === 'function' ? await handler(req) : handler;
    const status = reply.status ?? 200;
    const lower = Object.fromEntries(Object.entries(reply.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name: string) => lower[name.toLowerCase()] ?? null },
      text: async () => (reply.body === undefined ? '' : JSON.stringify(reply.body)),
      arrayBuffer: async () => (reply.bytes ?? new Uint8Array()).slice().buffer,
    } as unknown as Response;
  });
  return { impl: impl as unknown as typeof fetch, calls };
}
