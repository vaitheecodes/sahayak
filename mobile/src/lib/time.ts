import type { TFunction } from 'i18next';

// The server writes datetime.now(timezone.utc).isoformat(); some SQLite
// paths drop the offset, so treat a bare timestamp as UTC (as the web does).
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function relativeTime(t: TFunction, iso: string | null | undefined, now: number = Date.now()): string {
  const date = parseUtc(iso);
  if (!date) return '';
  const seconds = Math.round((now - date.getTime()) / 1000);
  if (seconds < 45) return t('time.justNow');
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return t('time.minutes', { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t('time.hours', { count: hours });
  const days = Math.round(hours / 24);
  if (days === 1) return t('time.yesterday');
  if (days < 7) return t('time.days', { count: days });
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) });
}

export function absoluteTime(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  return date
    ? date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : '';
}
