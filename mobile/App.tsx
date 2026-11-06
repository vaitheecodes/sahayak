// Stage 0 upload spike: which multipart upload path gets past the
// server's Content-Length check (411) on a real Android phone?
// Replaced by the real app in Stage 1.
import { useState } from 'react';
import {
  Button,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as ImagePicker from 'expo-image-picker';
import { File, UploadType } from 'expo-file-system';
import * as LegacyFS from 'expo-file-system/legacy';

type Picked = { uri: string; name: string; mimeType: string; size?: number };
type Result = { method: string; status: string; body: string };

const DEFAULT_API = (Constants.expoConfig?.extra?.apiUrl as string | undefined) ?? '';

export default function App() {
  const [api, setApi] = useState(DEFAULT_API);
  const [email, setEmail] = useState('spike@example.com');
  const [password, setPassword] = useState('spike-pass-123');
  const [token, setToken] = useState<string | null>(null);
  const [ticket, setTicket] = useState<{ ticket_id: string; message_id: string } | null>(null);
  const [photo, setPhoto] = useState<Picked | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [log, setLog] = useState('');

  const base = api.replace(/\/+$/, '');
  const record = (r: Result) => setResults((prev) => [r, ...prev]);

  async function json(path: string, body: unknown, auth?: string) {
    const res = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth ? { Authorization: `Bearer ${auth}` } : {}),
      },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`${path} ${res.status}: ${text}`);
    return JSON.parse(text);
  }

  async function setup() {
    setLog('Signing in…');
    try {
      let session;
      try {
        session = await json('/api/auth/login', { email, password });
      } catch {
        // Dev only: the spike account is created through the public
        // customer sign-up the first time.
        session = await json('/api/auth/customer/signup', {
          name: 'Upload Spike',
          email,
          password,
        });
      }
      setToken(session.token);
      const t = await json(
        '/api/tickets',
        {
          subject: 'Upload spike',
          description: 'Attachment upload test from the mobile spike.',
          priority: 'low',
        },
        session.token,
      );
      setTicket({ ticket_id: t.ticket_id, message_id: t.message_id });
      setLog(`Ready: ${t.ticket_id} / ${t.message_id}`);
    } catch (e) {
      setLog(String(e));
    }
  }

  async function pick(fromCamera: boolean) {
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.8 };
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return setLog('Camera permission denied');
    }
    const res = fromCamera
      ? await ImagePicker.launchCameraAsync(opts)
      : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled) return;
    const a = res.assets[0];
    const ext = a.mimeType === 'image/png' ? 'png' : 'jpg';
    setPhoto({
      uri: a.uri,
      name: a.fileName ?? `photo.${ext}`,
      mimeType: a.mimeType ?? 'image/jpeg',
      size: a.fileSize,
    });
  }

  const url = () => `${base}/api/tickets/${ticket!.ticket_id}/attachments`;

  async function viaFetch() {
    const form = new FormData();
    form.append('message_id', ticket!.message_id);
    // React Native's FormData file part: {uri, name, type}.
    form.append('files', { uri: photo!.uri, name: photo!.name, type: photo!.mimeType } as any);
    try {
      const res = await fetch(url(), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      record({ method: 'fetch + FormData', status: String(res.status), body: await res.text() });
    } catch (e) {
      record({ method: 'fetch + FormData', status: 'error', body: String(e) });
    }
  }

  async function viaFetchBlob() {
    // Expo's File implements Blob, so it can go into FormData directly.
    const form = new FormData();
    form.append('message_id', ticket!.message_id);
    form.append('files', new File(photo!.uri) as unknown as Blob, photo!.name);
    try {
      const res = await fetch(url(), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      record({ method: 'fetch + FormData (File blob)', status: String(res.status), body: await res.text() });
    } catch (e) {
      record({ method: 'fetch + FormData (File blob)', status: 'error', body: String(e) });
    }
  }

  async function viaFileUpload() {
    try {
      const res = await new File(photo!.uri).upload(url(), {
        uploadType: UploadType.MULTIPART,
        fieldName: 'files',
        mimeType: photo!.mimeType,
        parameters: { message_id: ticket!.message_id },
        headers: { Authorization: `Bearer ${token}` },
      });
      record({ method: 'File.upload (new API)', status: String(res.status), body: res.body });
    } catch (e) {
      record({ method: 'File.upload (new API)', status: 'error', body: String(e) });
    }
  }

  async function viaLegacyUpload() {
    try {
      const res = await LegacyFS.uploadAsync(url(), photo!.uri, {
        httpMethod: 'POST',
        uploadType: LegacyFS.FileSystemUploadType.MULTIPART,
        fieldName: 'files',
        mimeType: photo!.mimeType,
        parameters: { message_id: ticket!.message_id },
        headers: { Authorization: `Bearer ${token}` },
      });
      record({ method: 'legacy uploadAsync', status: String(res.status), body: res.body });
    } catch (e) {
      record({ method: 'legacy uploadAsync', status: 'error', body: String(e) });
    }
  }

  const ready = !!(token && ticket && photo);

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <StatusBar style="dark" />
      <Text style={styles.h1}>Upload spike</Text>
      <Text style={styles.label}>API base URL</Text>
      <TextInput style={styles.input} value={api} onChangeText={setApi} autoCapitalize="none" />
      <Text style={styles.label}>Email / password (dev account)</Text>
      <TextInput style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" />
      <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry />
      <Button title="1. Sign in + create test ticket" onPress={setup} />
      <Text style={styles.log}>{log}</Text>

      <View style={styles.row}>
        <Button title="2a. Gallery" onPress={() => pick(false)} />
        <Button title="2b. Camera" onPress={() => pick(true)} />
      </View>
      {photo && (
        <Text style={styles.log}>
          {photo.name} · {photo.mimeType} · {photo.size ?? '?'} bytes
        </Text>
      )}

      <View style={styles.stack}>
        <Button title="3a. Upload with fetch + FormData" onPress={viaFetch} disabled={!ready} />
        <Button title="3d. Upload with fetch + File blob" onPress={viaFetchBlob} disabled={!ready} />
        <Button title="3b. Upload with File.upload" onPress={viaFileUpload} disabled={!ready} />
        <Button title="3c. Upload with legacy uploadAsync" onPress={viaLegacyUpload} disabled={!ready} />
      </View>

      {results.map((r, i) => (
        <View key={i} style={styles.result}>
          <Text style={styles.resultHead}>
            {r.method}: {r.status}
          </Text>
          <Text selectable style={styles.mono}>
            {r.body}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, paddingTop: 56, gap: 8 },
  h1: { fontSize: 22, fontWeight: '600' },
  label: { fontSize: 13, color: '#555', marginTop: 8 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 10 },
  row: { flexDirection: 'row', gap: 12, marginTop: 8 },
  stack: { gap: 8, marginTop: 8 },
  log: { fontSize: 13, color: '#333' },
  result: { borderWidth: 1, borderColor: '#ddd', borderRadius: 6, padding: 10 },
  resultHead: { fontWeight: '600' },
  mono: { fontFamily: 'monospace', fontSize: 12 },
});
