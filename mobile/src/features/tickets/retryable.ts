import { isApiError } from '../../api/errors';

/** Worth offering "Try again": the request may well work a moment later. */
export function isRetryable(error: unknown): boolean {
  return isApiError(error) && ['network', 'timeout', 'unavailable', 'server'].includes(error.kind);
}
