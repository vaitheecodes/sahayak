// Validates the API base URL the app is built with. Used both by
// app.config.ts (so a release build with a bad URL fails at config time)
// and at runtime (src/config/index.ts). No React Native imports here:
// app.config.ts runs in Node.

export type ApiUrlCheck =
  | { ok: true; url: string }
  | { ok: false; reason: string };

export function checkApiUrl(raw: string | undefined, requireHttps: boolean): ApiUrlCheck {
  const value = (raw ?? '').trim().replace(/\/+$/, '');
  if (!value) {
    return { ok: false, reason: 'EXPO_PUBLIC_API_URL is not set' };
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return { ok: false, reason: `EXPO_PUBLIC_API_URL is not a valid URL: ${value}` };
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    return { ok: false, reason: `EXPO_PUBLIC_API_URL must use http or https: ${value}` };
  }
  if (requireHttps && parsed.protocol !== 'https:') {
    return {
      ok: false,
      reason: `EXPO_PUBLIC_API_URL must use https for this build (got ${value}); plain http is for development only`,
    };
  }
  if (parsed.search || parsed.hash) {
    return { ok: false, reason: `EXPO_PUBLIC_API_URL must not have a query or fragment: ${value}` };
  }
  return { ok: true, url: value };
}
