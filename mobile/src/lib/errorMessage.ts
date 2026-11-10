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

// The server's 400/409/413 details are mostly written for the customer
// ("At most 5 attachments per message", "photo.jpg is larger than 10 MB"),
// but a few are developer text ("message cannot be empty", "Customer role
// required", "Content-Length required for uploads"). Only a detail that
// reads as a sentence for a person is shown; anything else gets the app's
// own wording for that kind of error. A sentence may start with a file
// name ("photo.jpg is larger than 10 MB").
const TECHNICAL = /token|bearer|role required|content-length|header|traceback|exception|null|undefined|sql|json|[{}<>[\]]/i;

export function customerDetail(detail: string | null): string | null {
  const text = detail?.trim();
  if (!text || text.length > 200 || !/^([A-Z0-9"']|\S+\.\w+ )/.test(text) || TECHNICAL.test(text)) return null;
  return text;
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
        : customerDetail(error.detail) ?? t('errors.validation');
    case 'too_large':
      return customerDetail(error.detail) ?? t('errors.tooLarge');
    case 'unavailable':
      return t('errors.unavailable');
    case 'server':
      return t('errors.server');
    // "Ticket not found", "Not your chat": the app's own sentence reads better.
    case 'not_found':
      return t('errors.notFound');
    case 'forbidden':
      return error.detail === 'This account has been deactivated' ? t('errors.deactivated') : t('errors.forbidden');
    case 'password_change_required':
      return t('errors.passwordChangeRequired');
    case 'bad_request':
    case 'conflict':
      return customerDetail(error.detail) ?? t('errors.unknown');
  }
}
