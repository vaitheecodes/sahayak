import Constants from 'expo-constants';
import { checkApiUrl, type ApiUrlCheck } from './apiUrl';

type Extra = { apiUrl?: string; requireHttps?: boolean; variant?: string };

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

// A release JS bundle never accepts http, even if the config step was
// skipped somehow.
const requireHttps = Boolean(extra.requireHttps) || !__DEV__;

export const apiConfig: ApiUrlCheck = checkApiUrl(extra.apiUrl, requireHttps);

export const appVariant = extra.variant ?? 'development';
export const appVersion = Constants.expoConfig?.version ?? '0.0.0';
