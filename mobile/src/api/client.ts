import { ApiError, errorFromResponse } from './errors';

export type ApiClientOptions = {
  baseUrl: string;
  getToken: () => string | null;
  /** A request sent with a token got 401: the session is over. */
  onUnauthorized?: () => void;
  /** The account still has to replace its temporary password. */
  onPasswordChangeRequired?: () => void;
  fetchImpl?: typeof fetch;
  /** AI turns can take a while (the server allows the model 90 s). */
  timeoutMs?: number;
};

type RequestOptions = {
  json?: unknown;
  form?: FormData;
  auth?: boolean; // default true
  signal?: AbortSignal;
  /** Return the body as bytes (downloads) instead of parsing JSON. */
  bytes?: boolean;
};

export type ApiClient = {
  baseUrl: string;
  get<T>(path: string, opts?: Omit<RequestOptions, 'json' | 'form'>): Promise<T>;
  post<T>(path: string, json?: unknown, opts?: Omit<RequestOptions, 'json' | 'form'>): Promise<T>;
  postForm<T>(path: string, form: FormData, opts?: Omit<RequestOptions, 'json' | 'form'>): Promise<T>;
  /** GET a file. Errors are mapped like any other request. */
  getBytes(path: string, opts?: Omit<RequestOptions, 'json' | 'form' | 'bytes'>): Promise<ArrayBuffer>;
};

export function createApiClient(options: ApiClientOptions): ApiClient {
  const {
    baseUrl,
    getToken,
    onUnauthorized,
    onPasswordChangeRequired,
    fetchImpl = fetch,
    timeoutMs = 120_000,
  } = options;
  const root = baseUrl.replace(/\/+$/, '');

  async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const token = opts.auth === false ? null : getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    let body: BodyInit | undefined;
    if (opts.form) {
      // No Content-Type: fetch adds the multipart boundary itself.
      body = opts.form;
    } else if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.json);
    }

    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const onOuterAbort = () => controller.abort();
    opts.signal?.addEventListener('abort', onOuterAbort);

    let res: Response;
    try {
      res = await fetchImpl(`${root}${path}`, { method, headers, body, signal: controller.signal });
    } catch {
      throw new ApiError(timedOut ? 'timeout' : 'network');
    } finally {
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onOuterAbort);
    }

    if (res.ok && opts.bytes) {
      try {
        return (await res.arrayBuffer()) as T;
      } catch {
        // The connection dropped mid-body.
        throw new ApiError('network');
      }
    }

    const text = await res.text().catch(() => '');
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }

    if (!res.ok) {
      const error = errorFromResponse(res.status, data, res.headers, Boolean(token));
      if (error.kind === 'unauthorized') onUnauthorized?.();
      if (error.kind === 'password_change_required') onPasswordChangeRequired?.();
      throw error;
    }
    return data as T;
  }

  return {
    baseUrl: root,
    get: (path, opts) => request('GET', path, opts),
    post: (path, json, opts) => request('POST', path, { ...opts, json: json ?? {} }),
    postForm: (path, form, opts) => request('POST', path, { ...opts, form }),
    getBytes: (path, opts) => request('GET', path, { ...opts, bytes: true }),
  };
}
