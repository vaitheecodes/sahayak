import { checkApiUrl } from '../../src/config/apiUrl';

describe('checkApiUrl', () => {
  it('accepts http in development and trims a trailing slash', () => {
    expect(checkApiUrl('http://192.168.1.10:8000/', false)).toEqual({ ok: true, url: 'http://192.168.1.10:8000' });
  });

  it('refuses http when https is required (preview / release builds)', () => {
    const r = checkApiUrl('http://api.example.com', true);
    expect(r.ok).toBe(false);
    expect(!r.ok && r.reason).toMatch(/must use https/);
  });

  it('accepts https when required', () => {
    expect(checkApiUrl('https://api.example.com', true)).toEqual({ ok: true, url: 'https://api.example.com' });
  });

  it.each([[undefined], [''], ['   ']])('refuses a missing URL (%p)', (value) => {
    expect(checkApiUrl(value, false).ok).toBe(false);
  });

  it.each([['not a url'], ['ftp://api.example.com'], ['https://api.example.com/?x=1']])(
    'refuses %p',
    (value) => {
      expect(checkApiUrl(value, false).ok).toBe(false);
    },
  );
});
