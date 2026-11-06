import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isApiError } from '../api/errors';
import { errorMessage } from './errorMessage';

/**
 * Holds the last request error for a screen. A 429 starts a countdown
 * from Retry-After: `message` ticks down and `coolingDown` stays true
 * until it ends, so the screen can disable its submit button.
 */
export function useApiError() {
  const { t } = useTranslation();
  const [error, setError] = useState<unknown>(null);
  const [remaining, setRemaining] = useState(0);

  const show = useCallback((e: unknown) => {
    setError(e);
    setRemaining(isApiError(e) && e.kind === 'rate_limited' ? e.retryAfterSeconds ?? 0 : 0);
  }, []);

  const clear = useCallback(() => {
    setError(null);
    setRemaining(0);
  }, []);

  useEffect(() => {
    if (remaining <= 0) return;
    const id = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(id);
  }, [remaining]);

  const rateLimited = isApiError(error) && error.kind === 'rate_limited';
  return {
    error,
    show,
    clear,
    message: error ? errorMessage(t, error, rateLimited ? remaining : undefined) : null,
    coolingDown: rateLimited && remaining > 0,
    tone: rateLimited && remaining <= 0 ? ('info' as const) : ('negative' as const),
  };
}
