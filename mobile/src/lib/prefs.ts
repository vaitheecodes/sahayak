import * as SecureStore from 'expo-secure-store';

// Small non-secret preferences. SecureStore is used for these too so the
// app needs one storage dependency, not two; failures fall back to the
// default rather than breaking start-up.

export async function readPref(key: string): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(`pref.${key}`);
  } catch {
    return null;
  }
}

export async function writePref(key: string, value: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(`pref.${key}`, value);
  } catch {
    // Not fatal: the choice just won't survive a restart.
  }
}
