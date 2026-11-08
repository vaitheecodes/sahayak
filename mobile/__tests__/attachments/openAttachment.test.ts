import { Platform } from 'react-native';
import * as IntentLauncher from 'expo-intent-launcher';
import * as Sharing from 'expo-sharing';
import { createApiClient } from '../../src/api/client';
import { ticketsApi } from '../../src/api/tickets';
import { NoViewerError, openAttachment } from '../../src/features/attachments/openAttachment';
import { fakeFetch } from '../../test/fakeFetch';

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31]);
const ATT = { attachment_id: 'ATT-1', filename: 'invoice.pdf', content_type: 'application/pdf', size_bytes: PDF.length };
const PATH = '/api/tickets/TCK-1/attachments/ATT-1';

function client(routes: Parameters<typeof fakeFetch>[0]) {
  const fake = fakeFetch(routes);
  const api = createApiClient({ baseUrl: 'https://api.test', getToken: () => 'tok', fetchImpl: fake.impl });
  return { api, calls: fake.calls };
}
const files = () => (jest.requireMock('expo-file-system') as { __files: Map<string, Uint8Array> }).__files;

function onPlatform(os: 'ios' | 'android') {
  Object.defineProperty(Platform, 'OS', { value: os, configurable: true });
}

describe('attachment upload and download', () => {
  const original = Platform.OS;
  afterEach(() => onPlatform(original as 'ios' | 'android'));

  it('uploads files with the message id as multipart', async () => {
    const { api, calls } = client({
      'POST /api/tickets/TCK-1/attachments': { body: [{ ...ATT }] },
    });
    const { File } = jest.requireMock('expo-file-system') as { File: new (uri: string) => Blob };
    const created = await ticketsApi.uploadAttachments(api, 'TCK-1', 'MSG-9', [
      { name: 'a.pdf', blob: new File('file:///cache/a.pdf') },
      { name: 'b.png', blob: new File('file:///cache/b.png') },
    ]);
    expect(created[0].attachment_id).toBe('ATT-1');
    const form = calls[0].body as FormData;
    expect(form.get('message_id')).toBe('MSG-9');
    expect((form.getAll('files') as globalThis.File[]).map((f) => f.name)).toEqual(['a.pdf', 'b.png']);
    // No JSON content type: fetch writes the multipart boundary itself.
    expect(calls[0].headers['Content-Type']).toBeUndefined();
    expect(calls[0].headers.Authorization).toBe('Bearer tok');
  });

  it('on Android downloads with the token, saves to the cache and opens a viewer', async () => {
    onPlatform('android');
    const { api, calls } = client({ [`GET ${PATH}`]: { bytes: PDF, headers: { 'Content-Type': 'application/pdf' } } });
    await openAttachment(api, 'TCK-1', ATT);
    expect(calls[0].headers.Authorization).toBe('Bearer tok');
    expect(files().get('file:///cache/attachments/ATT-1/invoice.pdf')).toEqual(PDF);
    expect(IntentLauncher.startActivityAsync).toHaveBeenCalledWith('android.intent.action.VIEW', {
      data: 'content:///cache/attachments/ATT-1/invoice.pdf',
      type: 'application/pdf',
      flags: 1,
    });

    // A second open reuses the saved copy.
    await openAttachment(api, 'TCK-1', ATT);
    expect(calls).toHaveLength(1);
  });

  it('falls back to the share sheet when no Android app can open the file', async () => {
    onPlatform('android');
    (IntentLauncher.startActivityAsync as jest.Mock).mockRejectedValueOnce(new Error('No Activity found'));
    const { api } = client({ [`GET ${PATH}`]: { bytes: PDF } });
    await openAttachment(api, 'TCK-1', ATT);
    expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/attachments/ATT-1/invoice.pdf', {
      mimeType: 'application/pdf',
      dialogTitle: 'invoice.pdf',
    });
  });

  it('on iOS opens the share sheet (preview, Save to Files)', async () => {
    onPlatform('ios');
    const { api } = client({ [`GET ${PATH}`]: { bytes: PDF } });
    await openAttachment(api, 'TCK-1', ATT);
    expect(IntentLauncher.startActivityAsync).not.toHaveBeenCalled();
    expect(Sharing.shareAsync).toHaveBeenCalled();
  });

  it('says so when nothing can show the file', async () => {
    onPlatform('ios');
    (Sharing.isAvailableAsync as jest.Mock).mockResolvedValueOnce(false);
    const { api } = client({ [`GET ${PATH}`]: { bytes: PDF } });
    await expect(openAttachment(api, 'TCK-1', ATT)).rejects.toBeInstanceOf(NoViewerError);
  });

  it('maps a missing file to a not-found error and saves nothing', async () => {
    const { api } = client({ [`GET ${PATH}`]: { status: 404, body: { detail: 'Attachment not found' } } });
    await expect(openAttachment(api, 'TCK-1', ATT)).rejects.toMatchObject({ kind: 'not_found' });
    expect(files().size).toBe(0);
  });
});
