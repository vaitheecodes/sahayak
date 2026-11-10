import type { ConfigContext, ExpoConfig } from 'expo/config';
import { checkApiUrl } from './src/config/apiUrl.ts';

// APP_VARIANT is set per EAS build profile (eas.json). Anything other
// than "development" is a build handed to real users: it must talk to the
// API over https, and a missing or http URL fails the config (and so the
// build) instead of shipping.
const variant = process.env.APP_VARIANT ?? 'development';
const requireHttps = variant !== 'development';

// App identity. Bump VERSION for each release users see, and
// BUILD_NUMBER for every build uploaded anywhere (Android versionCode /
// iOS buildNumber must only go up). eas.json uses appVersionSource
// "local", so these are the source of truth.
const VERSION = '1.0.0';
const BUILD_NUMBER = 1;
const BASE_ID = 'com.vaitheeswaran.sahayak';

// Each variant gets its own id, so a development build, the preview APK
// and a store release can sit side by side on one phone.
const IDENTITY: Record<string, { name: string; id: string }> = {
  development: { name: 'Sahayak (dev)', id: `${BASE_ID}.dev` },
  preview: { name: 'Sahayak', id: `${BASE_ID}.preview` },
  production: { name: 'Sahayak', id: BASE_ID },
};

// Paste the id `npx eas-cli@latest init` prints (it can't write to a
// dynamic config itself). Empty until the EAS project exists.
const EAS_PROJECT_ID = '';

export default ({ config }: ConfigContext): ExpoConfig => {
  const check = checkApiUrl(process.env.EXPO_PUBLIC_API_URL, requireHttps);
  if (!check.ok && requireHttps) {
    throw new Error(`[app.config] ${check.reason} (APP_VARIANT=${variant})`);
  }
  const identity = IDENTITY[variant];
  if (!identity) throw new Error(`[app.config] unknown APP_VARIANT "${variant}"`);
  return {
    ...(config as ExpoConfig),
    name: identity.name,
    version: VERSION,
    ios: { ...config.ios, bundleIdentifier: identity.id, buildNumber: String(BUILD_NUMBER) },
    android: { ...config.android, package: identity.id, versionCode: BUILD_NUMBER },
    extra: {
      ...config.extra,
      apiUrl: check.ok ? check.url : '',
      requireHttps,
      variant,
      ...(EAS_PROJECT_ID ? { eas: { projectId: EAS_PROJECT_ID } } : {}),
    },
  };
};
