// Every failed request becomes an ApiError with a `kind` the UI can
// branch on, plus whatever the server said. The server uses FastAPI's
// {"detail": ...} shape: a readable string for most errors, a list of
// field problems for 422 (docs/API.md).

export type ApiErrorKind =
  | 'network' // no response at all
  | 'timeout'
  | 'bad_credentials' // 401 on a request sent without a token (sign-in)
  | 'unauthorized' // 401 with a token: expired or revoked session
  | 'password_change_required' // 403 until the temporary password is changed
  | 'forbidden' // other 403s (deactivated, not yours)
  | 'not_found'
  | 'conflict'
  | 'bad_request' // 400: detail is a readable sentence
  | 'too_large' // 411/413 on uploads
  | 'validation' // 422
  | 'rate_limited' // 429 with Retry-After
  | 'unavailable' // 503: AI provider or database busy
  | 'server'; // other 5xx

export type FieldError = {
  field: string; // last element of the pydantic `loc`, e.g. "description"
  type: string; // pydantic error type, e.g. "string_too_long"
  max?: number;
  min?: number;
  message: string; // the server's own message
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly detail: string | null;
  readonly retryAfterSeconds: number | null;
  readonly fieldErrors: FieldError[];

  constructor(
    kind: ApiErrorKind,
    opts: {
      status?: number | null;
      detail?: string | null;
      retryAfterSeconds?: number | null;
      fieldErrors?: FieldError[];
    } = {},
  ) {
    super(opts.detail ?? kind);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = opts.status ?? null;
    this.detail = opts.detail ?? null;
    this.retryAfterSeconds = opts.retryAfterSeconds ?? null;
    this.fieldErrors = opts.fieldErrors ?? [];
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

const PASSWORD_CHANGE_DETAIL = 'Password change required';

/** Retry-After is either delta-seconds or an HTTP date. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Math.max(1, parseInt(trimmed, 10));
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(1, Math.ceil((at - now) / 1000));
}

function parseFieldErrors(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return [];
  return detail
    .filter((d): d is Record<string, unknown> => !!d && typeof d === 'object')
    .map((d) => {
      const loc = Array.isArray(d.loc) ? d.loc : [];
      const ctx = (d.ctx && typeof d.ctx === 'object' ? d.ctx : {}) as Record<string, unknown>;
      return {
        field: String(loc[loc.length - 1] ?? ''),
        type: String(d.type ?? ''),
        max: typeof ctx.max_length === 'number' ? ctx.max_length : undefined,
        min: typeof ctx.min_length === 'number' ? ctx.min_length : undefined,
        message: String(d.msg ?? ''),
      };
    });
}

/** Builds the ApiError for a non-2xx response. */
export function errorFromResponse(
  status: number,
  body: unknown,
  headers: { get(name: string): string | null },
  tokenSent: boolean,
): ApiError {
  const raw = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined;
  const detail = typeof raw === 'string' ? raw : null;
  const retryAfterSeconds = parseRetryAfter(headers.get('retry-after'));
  const base = { status, detail, retryAfterSeconds };

  if (status === 401) return new ApiError(tokenSent ? 'unauthorized' : 'bad_credentials', base);
  if (status === 403) {
    return new ApiError(detail === PASSWORD_CHANGE_DETAIL ? 'password_change_required' : 'forbidden', base);
  }
  if (status === 404) return new ApiError('not_found', base);
  if (status === 409) return new ApiError('conflict', base);
  if (status === 411 || status === 413) return new ApiError('too_large', base);
  if (status === 422) return new ApiError('validation', { ...base, fieldErrors: parseFieldErrors(raw) });
  if (status === 429) return new ApiError('rate_limited', base);
  if (status === 503) return new ApiError('unavailable', base);
  if (status >= 500) return new ApiError('server', base);
  return new ApiError('bad_request', base);
}
