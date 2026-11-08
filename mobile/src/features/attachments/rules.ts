// The server's attachment rules (backend/main.py, upload_attachments):
// at most 5 files per message, 10 MB each, PNG / JPG / PDF / TXT / LOG
// whose contents match the extension. The app checks the same limits
// before uploading; the server still has the final say (it also checks the
// contents, which the app doesn't).

export const MAX_FILES = 5;
export const MAX_BYTES = 10 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ['png', 'jpg', 'jpeg', 'pdf', 'txt', 'log'] as const;

/** A file chosen in the app, not uploaded yet. */
export type PendingFile = {
  key: string;
  uri: string;
  name: string;
  /** Bytes; null when the picker couldn't say. */
  size: number | null;
  mimeType: string | null;
};

export type RejectReason = 'type' | 'size' | 'empty' | 'count';
export type Rejection = { name: string; reason: RejectReason };

const IMAGE_EXTENSION: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/jpg': 'jpg',
  'image/png': 'png',
  'image/heic': 'heic',
  'image/heif': 'heif',
};

export function extensionOf(nameOrUri: string): string {
  const base = nameOrUri.split(/[?#]/)[0].split('/').pop() ?? '';
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

function stem(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

export function isHeic(uri: string, mimeType?: string | null): boolean {
  return ['heic', 'heif'].includes(extensionOf(uri)) || /^image\/hei[cf]$/i.test(mimeType ?? '');
}

/**
 * The name to upload a photo under. The server matches the extension
 * against the bytes, so it comes from the file the picker actually wrote
 * (it may have re-encoded the photo, e.g. "IMG_1234.HEIC" handed back as
 * a .jpg), not from the photo's original name.
 */
export function photoName(asset: { uri: string; fileName?: string | null; mimeType?: string | null }, now = new Date()): string {
  const ext = extensionOf(asset.uri) || IMAGE_EXTENSION[(asset.mimeType ?? '').toLowerCase()] || 'jpg';
  const pad = (n: number) => String(n).padStart(2, '0');
  // Local time, as on the phone's clock: photo-20261107-121530.
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const fallback = `photo-${stamp}`;
  const base = asset.fileName ? stem(asset.fileName.split('/').pop()!) : fallback;
  return `${base || fallback}.${ext === 'jpeg' ? 'jpeg' : ext}`;
}

export function rejectionFor(file: PendingFile): RejectReason | null {
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(extensionOf(file.name))) return 'type';
  if (file.size !== null && file.size > MAX_BYTES) return 'size';
  if (file.size === 0) return 'empty';
  return null;
}

/** Adds picked files to the list: refuses the wrong type, too large,
 *  empty, and anything past the fifth file; skips a file picked twice. */
export function addFiles(current: PendingFile[], picked: PendingFile[]): { files: PendingFile[]; rejected: Rejection[] } {
  const files = [...current];
  const rejected: Rejection[] = [];
  for (const file of picked) {
    if (files.some((f) => f.uri === file.uri || (f.name === file.name && f.size === file.size))) continue;
    const reason = rejectionFor(file) ?? (files.length >= MAX_FILES ? 'count' : null);
    if (reason) rejected.push({ name: file.name, reason });
    else files.push(file);
  }
  return { files, rejected };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** A server filename made safe as a local file name (no folders). */
export function safeFileName(name: string): string {
  const base = name.split(/[/\\]/).pop() ?? '';
  const cleaned = base.replace(/[^\w.\- ()]+/g, '_').replace(/^\.+/, '').slice(-120);
  return cleaned || 'attachment';
}
