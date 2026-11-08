import { Platform } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { ImageManipulator } from 'expo-image-manipulator';
import { pickDocuments, pickPhotos, takePhoto, uploadParts } from '../../src/features/attachments/pick';

jest.mock('expo-image-picker', () => ({
  launchImageLibraryAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn(),
  UIImagePickerPreferredAssetRepresentationMode: { Compatible: 'compatible' },
}));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));
jest.mock('expo-image-manipulator', () => {
  const saveAsync = jest.fn(async () => ({ uri: 'file:///cache/manipulated/converted.jpg', width: 10, height: 10 }));
  return {
    SaveFormat: { JPEG: 'jpeg' },
    ImageManipulator: { manipulate: jest.fn(() => ({ renderAsync: async () => ({ saveAsync }) })) },
    __saveAsync: saveAsync,
  };
});

const files = () => (jest.requireMock('expo-file-system') as { __files: Map<string, Uint8Array> }).__files;
const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;

describe('pickers', () => {
  it('asks for JPEG over HEIC and limits a multi-pick to the room left', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [{ uri: 'file:///cache/p/1.jpg', fileName: 'IMG_1.HEIC', fileSize: 2048, mimeType: 'image/jpeg', width: 1, height: 1 }],
    } as ImagePicker.ImagePickerResult);
    const outcome = await pickPhotos(3);
    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ selectionLimit: 3, allowsMultipleSelection: true, preferredAssetRepresentationMode: 'compatible' }),
    );
    expect(outcome).toMatchObject({ kind: 'picked', files: [{ name: 'IMG_1.jpg', size: 2048, uri: 'file:///cache/p/1.jpg' }] });
    expect(ImageManipulator.manipulate).not.toHaveBeenCalled();
  });

  it('converts a photo still in HEIC to JPEG before it can be uploaded', async () => {
    files().set('file:///cache/manipulated/converted.jpg', new Uint8Array(500));
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [{ uri: 'file:///cache/p/IMG_2.HEIC', fileName: 'IMG_2.HEIC', fileSize: 9000, mimeType: 'image/heic', width: 1, height: 1 }],
    } as ImagePicker.ImagePickerResult);
    const outcome = await pickPhotos(5);
    expect(ImageManipulator.manipulate).toHaveBeenCalledWith('file:///cache/p/IMG_2.HEIC');
    expect(jest.requireMock('expo-image-manipulator').__saveAsync).toHaveBeenCalledWith({ format: 'jpeg', compress: 0.85 });
    expect(outcome).toMatchObject({
      kind: 'picked',
      files: [{ name: 'IMG_2.jpg', uri: 'file:///cache/manipulated/converted.jpg', size: 500, mimeType: 'image/jpeg' }],
    });
  });

  it('reports a refused camera permission without opening the camera', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue({ granted: false } as ImagePicker.CameraPermissionResponse);
    expect(await takePhoto()).toEqual({ kind: 'denied' });
    expect(picker.launchCameraAsync).not.toHaveBeenCalled();
  });

  it('names a camera photo that has no file name', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue({ granted: true } as ImagePicker.CameraPermissionResponse);
    picker.launchCameraAsync.mockResolvedValue({
      canceled: false,
      assets: [{ uri: 'file:///cache/Camera/abc.jpg', fileName: '3fb28a38-c1ad-434d.jpg', fileSize: 100, mimeType: 'image/jpeg', width: 1, height: 1 }],
    } as ImagePicker.ImagePickerResult);
    const outcome = await takePhoto();
    expect(outcome.kind === 'picked' && outcome.files[0].name).toMatch(/^photo-\d{8}-\d{6}\.jpg$/);
  });

  it('lets the files picker offer any type, so a wrong one gets a reason', async () => {
    (DocumentPicker.getDocumentAsync as jest.Mock).mockResolvedValue({
      canceled: false,
      assets: [{ uri: 'file:///cache/d/session.har', name: 'session.har', size: 42, mimeType: 'application/json', lastModified: 0 }],
    });
    const outcome = await pickDocuments();
    expect(DocumentPicker.getDocumentAsync).toHaveBeenCalledWith({ type: '*/*', multiple: true, copyToCacheDirectory: Platform.OS !== 'android' });
    expect(outcome).toMatchObject({ kind: 'picked', files: [{ name: 'session.har', size: 42 }] });
    expect(await (async () => {
      (DocumentPicker.getDocumentAsync as jest.Mock).mockResolvedValue({ canceled: true, assets: null });
      return pickDocuments();
    })()).toEqual({ kind: 'canceled' });
  });

  it('uploads each file as an expo-file-system File, copied under its shown name when needed', async () => {
    files().set('content://downloads/document%3A22', new Uint8Array([1, 2, 3]));
    const parts = await uploadParts([
      { key: 'k1', uri: 'file:///cache/p/19.png', name: '19.png', size: 1, mimeType: null },
      { key: 'k2', uri: 'content://downloads/document%3A22', name: 'steps.pdf', size: 3, mimeType: null },
    ]);
    const uris = parts.map((p) => (p.blob as unknown as { uri: string }).uri);
    expect(parts.map((p) => p.name)).toEqual(['19.png', 'steps.pdf']);
    // Already named right: sent as is. A provider id: copied as steps.pdf.
    expect(uris).toEqual(['file:///cache/p/19.png', 'file:///cache/uploads/k2/steps.pdf']);
    expect(files().get('file:///cache/uploads/k2/steps.pdf')).toEqual(new Uint8Array([1, 2, 3]));
  });
});
