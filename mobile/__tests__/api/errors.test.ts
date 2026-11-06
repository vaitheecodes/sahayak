import { errorFromResponse, parseRetryAfter } from '../../src/api/errors';

const headers = (h: Record<string, string> = {}) => ({ get: (n: string) => h[n.toLowerCase()] ?? null });

describe('parseRetryAfter', () => {
  it('reads delta-seconds', () => {
    expect(parseRetryAfter('42')).toBe(42);
  });

  it('reads an HTTP date relative to now', () => {
    const now = Date.parse('2026-11-06T10:00:00Z');
    expect(parseRetryAfter('Fri, 06 Nov 2026 10:00:30 GMT', now)).toBe(30);
  });

  it('never returns less than one second', () => {
    expect(parseRetryAfter('0')).toBe(1);
  });

  it('ignores missing or garbage values', () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter('soon')).toBeNull();
  });
});

describe('errorFromResponse', () => {
  it.each([
    [404, 'not_found'],
    [409, 'conflict'],
    [400, 'bad_request'],
    [411, 'too_large'],
    [413, 'too_large'],
    [503, 'unavailable'],
    [500, 'server'],
    [502, 'server'],
  ])('maps %i to %s', (status, kind) => {
    expect(errorFromResponse(status, { detail: 'x' }, headers(), true).kind).toBe(kind);
  });

  it('tells an expired session from bad sign-in details', () => {
    expect(errorFromResponse(401, { detail: 'Invalid or expired token' }, headers(), true).kind).toBe('unauthorized');
    expect(errorFromResponse(401, { detail: 'Invalid email or password' }, headers(), false).kind).toBe(
      'bad_credentials',
    );
  });

  it('spots the forced password change among 403s', () => {
    expect(errorFromResponse(403, { detail: 'Password change required' }, headers(), true).kind).toBe(
      'password_change_required',
    );
    const deactivated = errorFromResponse(403, { detail: 'This account has been deactivated' }, headers(), true);
    expect(deactivated.kind).toBe('forbidden');
    expect(deactivated.detail).toBe('This account has been deactivated');
  });

  it('keeps Retry-After on a 429', () => {
    const e = errorFromResponse(429, { detail: 'Too many requests' }, headers({ 'retry-after': '17' }), true);
    expect(e.kind).toBe('rate_limited');
    expect(e.retryAfterSeconds).toBe(17);
  });

  it('turns a FastAPI 422 list into field errors', () => {
    const body = {
      detail: [
        {
          type: 'string_too_long',
          loc: ['body', 'description'],
          msg: 'String should have at most 8000 characters',
          ctx: { max_length: 8000 },
        },
        { type: 'missing', loc: ['body', 'subject'], msg: 'Field required' },
      ],
    };
    const e = errorFromResponse(422, body, headers(), true);
    expect(e.kind).toBe('validation');
    expect(e.detail).toBeNull();
    expect(e.fieldErrors).toEqual([
      { field: 'description', type: 'string_too_long', max: 8000, min: undefined, message: body.detail[0].msg },
      { field: 'subject', type: 'missing', max: undefined, min: undefined, message: 'Field required' },
    ]);
  });

  it('copes with a body that is not JSON', () => {
    const e = errorFromResponse(502, null, headers(), true);
    expect(e.kind).toBe('server');
    expect(e.detail).toBeNull();
  });
});
