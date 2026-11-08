import {
  addFiles,
  extensionOf,
  formatBytes,
  isHeic,
  MAX_BYTES,
  photoName,
  safeFileName,
  type PendingFile,
} from '../../src/features/attachments/rules';

const file = (name: string, size: number | null = 1000, uri = `file:///cache/${name}`): PendingFile => ({
  key: name,
  uri,
  name,
  size,
  mimeType: null,
});

describe('attachment rules', () => {
  it('reads extensions from names and uris', () => {
    expect(extensionOf('Report.PDF')).toBe('pdf');
    expect(extensionOf('file:///cache/ImagePicker/abc.jpeg?x=1')).toBe('jpeg');
    expect(extensionOf('README')).toBe('');
    expect(extensionOf('.hidden')).toBe('');
  });

  it('names a photo after the file the picker wrote, not the original', () => {
    // iOS: an HEIC photo handed back re-encoded as JPEG.
    expect(photoName({ uri: 'file:///cache/ABC.jpg', fileName: 'IMG_1234.HEIC' })).toBe('IMG_1234.jpg');
    expect(photoName({ uri: 'file:///cache/x.png', fileName: 'shot.png' })).toBe('shot.png');
    // Android camera: no file name, no extension on the uri.
    expect(photoName({ uri: 'content://media/42', fileName: null, mimeType: 'image/jpeg' }, new Date(2026, 10, 7, 9, 5, 3))).toBe(
      'photo-20261107-090503.jpg',
    );
    expect(isHeic('file:///a/IMG.HEIC')).toBe(true);
    expect(isHeic('file:///a/x', 'image/heif')).toBe(true);
    expect(isHeic('file:///a/x.jpg', 'image/jpeg')).toBe(false);
  });

  it('refuses the wrong type, too large, empty and a sixth file, with a reason each', () => {
    const { files, rejected } = addFiles(
      [],
      [
        file('a.png'),
        file('capture.har'),
        file('big.pdf', MAX_BYTES + 1),
        file('empty.txt', 0),
        file('b.jpg'),
        file('c.pdf'),
        file('d.txt'),
        file('e.log'),
        file('f.jpeg'),
      ],
    );
    expect(files.map((f) => f.name)).toEqual(['a.png', 'b.jpg', 'c.pdf', 'd.txt', 'e.log']);
    expect(rejected).toEqual([
      { name: 'capture.har', reason: 'type' },
      { name: 'big.pdf', reason: 'size' },
      { name: 'empty.txt', reason: 'empty' },
      { name: 'f.jpeg', reason: 'count' },
    ]);
  });

  it('accepts a file of exactly 10 MB, or of unknown size, and skips one picked twice', () => {
    const first = addFiles([], [file('max.pdf', MAX_BYTES), file('unknown.txt', null)]);
    expect(first.rejected).toEqual([]);
    const again = addFiles(first.files, [file('max.pdf', MAX_BYTES)]);
    expect(again.files).toHaveLength(2);
    expect(again.rejected).toEqual([]);
  });

  it('makes server file names safe to save', () => {
    expect(safeFileName('../../etc/passwd')).toBe('passwd');
    expect(safeFileName('report: Q3?.pdf')).toBe('report_ Q3_.pdf');
    expect(safeFileName('...')).toBe('attachment');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(3.5 * 1024 * 1024)).toBe('3.5 MB');
  });
});
