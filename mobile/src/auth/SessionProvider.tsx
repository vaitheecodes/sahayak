import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AppState } from 'react-native';
import { createApiClient, type ApiClient } from '../api/client';
import { authApi } from '../api/auth';
import { isApiError } from '../api/errors';
import type { Me } from '../api/types';
import { tokenStore } from './tokenStore';

export type SessionStatus =
  | 'loading' // reading the stored token
  | 'signedOut'
  | 'signedIn'
  | 'unreachable'; // have a token, but the server couldn't be reached to check it

/** Why the user is looking at the sign-in screen, if there's a reason to say. */
export type SignedOutNotice = 'expired' | 'staff' | 'signedOut' | null;

export class StaffAccountError extends Error {
  constructor() {
    super('staff account');
    this.name = 'StaffAccountError';
  }
}

type SessionValue = {
  status: SessionStatus;
  user: Me | null;
  notice: SignedOutNotice;
  /** The email of the session that just expired, to fill in on sign-in. */
  lastEmail: string;
  api: ApiClient;
  signIn: (email: string, password: string) => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  signOut: () => Promise<void>;
  retry: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

type Props = {
  baseUrl: string;
  children: ReactNode;
  fetchImpl?: typeof fetch;
  /** Request timeout; tests shorten it. */
  timeoutMs?: number;
};

export function SessionProvider({ baseUrl, children, fetchImpl, timeoutMs }: Props) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<Me | null>(null);
  const [notice, setNotice] = useState<SignedOutNotice>(null);
  const [lastEmail, setLastEmail] = useState('');
  const tokenRef = useRef<string | null>(null);
  const emailRef = useRef('');

  const endSession = useCallback(async (why: SignedOutNotice) => {
    tokenRef.current = null;
    await tokenStore.clear().catch(() => undefined);
    setLastEmail(why === 'expired' ? emailRef.current : '');
    setUser(null);
    setNotice(why);
    setStatus('signedOut');
  }, []);

  // tokenRef is read when a request is sent, never while rendering.
  /* eslint-disable react-hooks/refs */
  const api = useMemo(
    () =>
      createApiClient({
        baseUrl,
        fetchImpl,
        timeoutMs,
        getToken: () => tokenRef.current,
        onUnauthorized: () => {
          if (tokenRef.current) endSession('expired');
        },
        onPasswordChangeRequired: () =>
          setUser((u) => (u ? { ...u, must_change_password: true } : u)),
      }),
    [baseUrl, fetchImpl, timeoutMs, endSession],
  );
  /* eslint-enable react-hooks/refs */

  /** Confirms the stored token with /auth/me. */
  const restore = useCallback(async () => {
    const token = await tokenStore.get().catch(() => null);
    if (!token) {
      setStatus('signedOut');
      return;
    }
    tokenRef.current = token;
    try {
      const me = await authApi.me(api);
      if (me.role !== 'customer') {
        await endSession('staff');
        return;
      }
      emailRef.current = me.email;
      setUser(me);
      setStatus('signedIn');
    } catch (e) {
      if (isApiError(e) && (e.kind === 'unauthorized' || e.kind === 'forbidden')) {
        // 401 already ended the session through onUnauthorized; a 403
        // here means the account was deactivated.
        await endSession('expired');
      } else {
        setStatus('unreachable');
      }
    }
  }, [api, endSession]);

  useEffect(() => {
    // The request is async: state is only set after it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    restore();
  }, [restore]);

  // Coming back to the app re-checks the session, so an expired or
  // deactivated account lands on sign-in instead of failing later.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active' || !tokenRef.current) return;
      authApi
        .me(api)
        .then((me) => setUser(me))
        .catch(() => undefined);
    });
    return () => sub.remove();
  }, [api]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const res = await authApi.login(api, email.trim(), password);
      if (res.role !== 'customer') throw new StaffAccountError();
      tokenRef.current = res.token;
      emailRef.current = email.trim();
      await tokenStore.set(res.token);
      setUser({
        user_id: res.user_id,
        role: res.role,
        name: res.name,
        email: email.trim(),
        must_change_password: res.must_change_password,
      });
      setNotice(null);
      setStatus('signedIn');
    },
    [api],
  );

  const changePassword = useCallback(
    async (current: string, next: string) => {
      await authApi.changePassword(api, current, next);
      setUser((u) => (u ? { ...u, must_change_password: false } : u));
    },
    [api],
  );

  const signOut = useCallback(() => endSession('signedOut'), [endSession]);

  const retry = useCallback(async () => {
    setStatus('loading');
    await restore();
  }, [restore]);

  const value = useMemo<SessionValue>(
    () => ({ status, user, notice, lastEmail, api, signIn, changePassword, signOut, retry }),
    [status, user, notice, lastEmail, api, signIn, changePassword, signOut, retry],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession outside SessionProvider');
  return value;
}

export function useApi(): ApiClient {
  return useSession().api;
}
