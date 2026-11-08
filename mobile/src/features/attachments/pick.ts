import { Platform } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { Directory, File, Paths } from 'expo-file-system';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import type { UploadPart } from '../../api/tickets';
import { isHeic, photoName, safeFileName, type PendingFile } from './rules';

// The native pickers, each returning PendingFiles (or why nothing came
// back). Checking the files against the server's rules happens afterwards,
// in rules.addFiles, the same way for every source.

export type PickOutcome = { kind: 'picked'; files: PendingFile[] } | { kind: 'canceled' } | { kind: 'denied' };

let counter = 0;
const nextKey = () => `f${Date.now()}-${counter++}`;

/** The file's real size. A picker's own figure can be the photo before it
 *  was compressed, so it's only the fallback. */
function sizeOf(uri: string, reported?: number | null): number | null {
  try {
    const file = new File(uri);
    if (file.exists && file.size > 0) return file.size;
  } catch {
    // Not readable here: use what the picker said.
  }
  return typeof reported === 'number' && reported >= 0 ? reported : null;
}

/** iPhone photos are often HEIC, which the server doesn't take. The picker
 *  usually hands back a JPEG ('compatible' mode); if it doesn't, convert. */
async function asUploadablePhoto(asset: ImagePicker.ImagePickerAsset): Promise<PendingFile> {
  let { uri } = asset;
  let size = asset.fileSize ?? null;
  let mimeType = asset.mimeType ?? null;
  if (isHeic(uri, mimeType)) {
    const rendered = await ImageManipulator.manipulate(uri).renderAsync();
    const saved = await rendered.saveAsync({ format: SaveFormat.JPEG, compress: 0.85 });
    uri = saved.uri;
    size = null;
    mimeType = 'image/jpeg';
  }
  return {
    key: nextKey(),
    uri,
    name: photoName({ uri, fileName: asset.fileName, mimeType }),
    size: sizeOf(uri, size),
    mimeType,
  };
}

const PHOTO_OPTIONS: ImagePicker.ImagePickerOptions = {
  mediaTypes: ['images'],
  quality: 0.85,
  // iOS: hand back a JPEG rather than the original HEIC where it can.
  preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
};

export async function pickPhotos(limit: number): Promise<PickOutcome> {
  const result = await ImagePicker.launchImageLibraryAsync({
    ...PHOTO_OPTIONS,
    allowsMultipleSelection: limit > 1,
    selectionLimit: limit,
  });
  if (result.canceled) return { kind: 'canceled' };
  return { kind: 'picked', files: await Promise.all(result.assets.map(asUploadablePhoto)) };
}

export async function takePhoto(): Promise<PickOutcome> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) return { kind: 'denied' };
  const result = await ImagePicker.launchCameraAsync(PHOTO_OPTIONS);
  if (result.canceled) return { kind: 'canceled' };
  // A new shot's "name" is a random cache file name: call it photo-<time>.
  return {
    kind: 'picked',
    files: await Promise.all(result.assets.map((a) => asUploadablePhoto({ ...a, fileName: null }))),
  };
}

/** Any file: the type is checked afterwards so a wrong one gets a clear
 *  message instead of being greyed out in the picker. On Android the file
 *  is read through the picker's content:// URI: a copy in the cache folder
 *  can't be read back in Expo Go ("Missing 'READ' permission"), which only
 *  lets an app into its own sandbox. */
export async function pickDocuments(): Promise<PickOutcome> {
  const result = await DocumentPicker.getDocumentAsync({
    type: '*/*',
    multiple: true,
    copyToCacheDirectory: Platform.OS !== 'android',
  });
  if (result.canceled) return { kind: 'canceled' };
  return {
    kind: 'picked',
    files: result.assets.map((a) => ({
      key: nextKey(),
      uri: a.uri,
      name: a.name,
      size: sizeOf(a.uri, a.size),
      mimeType: a.mimeType ?? null,
    })),
  };
}

/**
 * What to upload. Expo's File implements Blob, so fetch sends it with a
 * Content-Length (Stage 0 spike, method 3D). FormData takes the part's
 * file name from the File itself, not from append()'s third argument, and
 * a picked file's own name can be a provider id ("document:22") or a random
 * cache name: so each file whose name differs is first copied, under the
 * name the customer sees, into the app's cache.
 */
export async function uploadParts(files: PendingFile[]): Promise<UploadPart[]> {
  return Promise.all(
    files.map(async (f) => {
      const source = new File(f.uri);
      const name = safeFileName(f.name);
      if (source.name === name) return { name, blob: source as unknown as Blob };
      const folder = new Directory(Paths.cache, 'uploads', f.key);
      folder.create({ intermediates: true, idempotent: true });
      const staged = new File(folder, name);
      await source.copy(staged, { overwrite: true });
      return { name, blob: staged as unknown as Blob };
    }),
  );
}
