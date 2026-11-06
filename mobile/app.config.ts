import type { ConfigContext, ExpoConfig } from 'expo/config';
import { checkApiUrl } from './src/config/apiUrl.ts';

// APP_VARIANT is set per EAS build profile (eas.json). Anything other
// than "development" is a build handed to real users: it must talk to the
// API over https, and a missing or http URL fails the config (and so the
// build) instead of shipping.
const variant = process.env.APP_VARIANT ?? 'development';
const requireHttps = variant !== 'development';

export default ({ config }: ConfigContext): ExpoConfig => {
  const check = checkApiUrl(process.env.EXPO_PUBLIC_API_URL, requireHttps);
  if (!check.ok && requireHttps) {
    throw new Error(`[app.config] ${check.reason} (APP_VARIANT=${variant})`);
  }
  return {
    ...(config as ExpoConfig),
    extra: {
      ...config.extra,
      apiUrl: check.ok ? check.url : '',
      requireHttps,
      variant,
    },
  };
};
