import type { TFunction } from 'i18next';
import { isApiError, type FieldError } from '../api/errors';

function fieldLabel(t: TFunction, field: string): string {
  return t(`fields.${field}`, { defaultValue: field });
}

export function fieldErrorMessage(t: TFunction, e: FieldError): string {
  const field = fieldLabel(t, e.field);
  if (e.type === 'string_too_long' && e.max != null) return t('errors.fieldTooLong', { field, max: e.max });
  if (e.type === 'string_too_short' && e.min != null) return t('errors.fieldTooShort', { field, min: e.min });
  if (e.type === 'missing') return t('errors.fieldRequired', { field });
  return t('errors.fieldInvalid', { field });
}

/**
 * The sentence to show for a failed request. `remainingSeconds` overrides
 * Retry-After for a live countdown on 429.
 */
export function errorMessage(t: TFunction, error: unknown, remainingSeconds?: number): string {
  if (!isApiError(error)) return t('errors.unknown');
  switch (error.kind) {
    case 'network':
      return t('errors.network');
    case 'timeout':
      return t('errors.timeout');
    case 'bad_credentials':
      return t('errors.badCredentials');
    case 'unauthorized':
      return t('auth.sessionExpired');
    case 'rate_limited': {
      const left = remainingSeconds ?? error.retryAfterSeconds ?? 0;
      return left > 0 ? t('errors.rateLimited', { count: left }) : t('errors.rateLimitedDone');
    }
    case 'validation':
      return error.fieldErrors.length
        ? error.fieldErrors.map((f) => fieldErrorMessage(t, f)).join('\n')
        : error.detail ?? t('errors.validation');
    case 'too_large':
      return error.detail ?? t('errors.tooLarge');
    case 'unavailable':
      return t('errors.unavailable');
    case 'server':
      return t('errors.server');
    case 'not_found':
      return error.detail ?? t('errors.notFound');
    case 'forbidden':
      return error.detail ?? t('errors.forbidden');
    // The server's 400/409 details are already written for the customer
    // ("At most 5 attachments per message", "Current password is incorrect").
    case 'bad_request':
    case 'conflict':
    case 'password_change_required':
      return error.detail ?? t('errors.unknown');
  }
}
