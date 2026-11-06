import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { getLocales } from 'expo-localization';
import en from './locales/en.json';

// Every visible string lives in a locale file under a stable key. To add
// Tamil or Hindi later: add locales/ta.json or hi.json with the same keys
// and list it here; the device language picks it automatically.
export const resources = {
  en: { translation: en },
} as const;

export const supportedLanguages = Object.keys(resources) as (keyof typeof resources)[];

function deviceLanguage(): string {
  try {
    const code = getLocales()[0]?.languageCode ?? 'en';
    return (supportedLanguages as string[]).includes(code) ? code : 'en';
  } catch {
    return 'en';
  }
}

if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    resources,
    lng: deviceLanguage(),
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    returnNull: false,
  });
}

export default i18n;
