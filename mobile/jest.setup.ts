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
  jest.clearAllMocks();
  (jest.requireMock('expo-file-system') as { __files: Map<string, Uint8Array> }).__files.clear();
});

// expo-file-system's File/Directory, kept in memory: `__files` maps a uri
// to its bytes so tests can seed picked files and check downloads.
jest.mock('expo-file-system', () => {
  const files = new Map<string, Uint8Array>();
  const join = (parts: unknown[]) =>
    parts
      .map((p) => (typeof p === 'string' ? p : (p as { uri: string }).uri))
      .map((p, i) => (i === 0 ? p.replace(/\/+$/, '') : p.replace(/^\/+|\/+$/g, '')))
      .join('/');
  // A real Blob, as Expo's File is, so FormData takes it.
  class File extends Blob {
    uri: string;
    constructor(...parts: unknown[]) {
      super([]);
      this.uri = join(parts);
    }
    get name() {
      return this.uri.split('/').pop() ?? '';
    }
    get exists() {
      return files.has(this.uri);
    }
    get size() {
      return files.get(this.uri)?.length ?? 0;
    }
    get contentUri() {
      return this.uri.replace('file://', 'content://');
    }
    create() {
      files.set(this.uri, new Uint8Array());
    }
    delete() {
      files.delete(this.uri);
    }
    async write(content: Uint8Array) {
      files.set(this.uri, content);
    }
    async copy(to: { uri: string }) {
      files.set(to.uri, files.get(this.uri) ?? new Uint8Array());
    }
  }
  class Directory {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = join(parts);
    }
    create() {}
  }
  return { __files: files, File, Directory, Paths: { cache: 'file:///cache', document: 'file:///docs' } };
});

jest.mock('expo-intent-launcher', () => ({ startActivityAsync: jest.fn(async () => ({ resultCode: 0 })) }));

jest.mock('expo-sharing', () => ({
  isAvailableAsync: jest.fn(async () => true),
  shareAsync: jest.fn(async () => undefined),
}));

// expo-network: online unless a test calls __setConnected(false).
jest.mock('expo-network', () => {
  const { useEffect, useState } = jest.requireActual('react');
  let connected = true;
  const listeners = new Set<React.Dispatch<boolean>>();
  return {
    useNetworkState: () => {
      const [isConnected, set] = useState(connected);
      useEffect(() => {
        listeners.add(set);
        return () => {
          listeners.delete(set);
        };
      }, []);
      return { isConnected, isInternetReachable: isConnected, type: isConnected ? 'WIFI' : 'NONE' };
    },
    __setConnected: (next: boolean) => {
      connected = next;
      listeners.forEach((l) => l(next));
    },
  };
});
