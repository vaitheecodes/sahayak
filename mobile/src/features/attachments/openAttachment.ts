import { Platform } from 'react-native';
import { Directory, File, Paths } from 'expo-file-system';
import * as IntentLauncher from 'expo-intent-launcher';
import * as Sharing from 'expo-sharing';
import type { ApiClient } from '../../api/client';
import { ticketsApi } from '../../api/tickets';
import type { Attachment } from '../../api/types';
import { safeFileName } from './rules';

// Attachments are only served to a signed-in user (no public links), so the
// app downloads the bytes with its token through the API client (same error
// handling as every other call), keeps them in the cache folder (the OS may
// clear it) and hands the file to another app to show.

const FLAG_GRANT_READ_URI_PERMISSION = 1;

export class NoViewerError extends Error {
  constructor() {
    super('no app can open this file');
    this.name = 'NoViewerError';
  }
}

/** Downloads once per attachment; a cached copy of the right size is reused. */
export async function downloadAttachment(api: ApiClient, ticketId: string, attachment: Attachment): Promise<File> {
  const dir = new Directory(Paths.cache, 'attachments', safeFileName(attachment.attachment_id));
  const file = new File(dir, safeFileName(attachment.filename));
  if (file.exists && file.size === attachment.size_bytes) return file;

  const bytes = await ticketsApi.downloadAttachment(api, ticketId, attachment.attachment_id);
  dir.create({ intermediates: true, idempotent: true });
  if (file.exists) file.delete();
  file.create();
  await file.write(new Uint8Array(bytes));
  return file;
}

/** Android: open in a viewer app (falls back to the share sheet).
 *  iOS: the share sheet, which previews the file and offers "Save to Files". */
export async function showFile(file: File, mimeType: string): Promise<void> {
  if (Platform.OS === 'android') {
    try {
      await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
        data: file.contentUri,
        type: mimeType,
        flags: FLAG_GRANT_READ_URI_PERMISSION,
      });
      return;
    } catch {
      // No app for this type: offer the share sheet instead.
    }
  }
  if (!(await Sharing.isAvailableAsync())) throw new NoViewerError();
  await Sharing.shareAsync(file.uri, { mimeType, dialogTitle: file.name });
}

export async function openAttachment(api: ApiClient, ticketId: string, attachment: Attachment): Promise<void> {
  const file = await downloadAttachment(api, ticketId, attachment);
  await showFile(file, attachment.content_type);
}
