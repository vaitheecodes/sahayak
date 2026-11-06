import '@testing-library/react-native/matchers';
import './src/i18n';

// Icons are decoration here; render nothing instead of loading the ESM build.
jest.mock('lucide-react-native', () => new Proxy({}, { get: () => () => null }));

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);

// In-memory stand-in for the OS keystore.
jest.mock('expo-secure-store', () => {
  const store = new Map<string, string>();
  return {
    __store: store,
    getItemAsync: jest.fn(async (k: string) => store.get(k) ?? null),
    setItemAsync: jest.fn(async (k: string, v: string) => {
      store.set(k, v);
    }),
    deleteItemAsync: jest.fn(async (k: string) => {
      store.delete(k);
    }),
  };
});

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { version: '0.1.0', extra: { apiUrl: 'https://api.test', requireHttps: false } } },
}));

beforeEach(() => {
  const secure = jest.requireMock('expo-secure-store') as { __store: Map<string, string> };
  secure.__store.clear();
});
