import type { ConfigContext, ExpoConfig } from 'expo/config';

// The API base URL comes from the environment (EXPO_PUBLIC_API_URL,
// e.g. in mobile/.env.local), never from the source.
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...(config as ExpoConfig),
  extra: {
    ...config.extra,
    apiUrl: process.env.EXPO_PUBLIC_API_URL ?? '',
  },
});
