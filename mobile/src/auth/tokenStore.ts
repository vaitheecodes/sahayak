import * as SecureStore from 'expo-secure-store';

// The JWT lives only in the OS keystore (Android Keystore / iOS
// Keychain), never in plain storage or logs.
const KEY = 'auth.token';

export const tokenStore = {
  get: () => SecureStore.getItemAsync(KEY),
  set: (token: string) => SecureStore.setItemAsync(KEY, token),
  clear: () => SecureStore.deleteItemAsync(KEY),
};
