import { describe, expect, it } from 'vitest';
import { checkFileInfo, hasPdfSignature, MAX_FILE_BYTES } from './pdf';

describe('checkFileInfo', () => {
  it('accepts a PDF up to 10 MB', () => {
    expect(
      checkFileInfo({ name: 'umowa.pdf', type: 'application/pdf', size: MAX_FILE_BYTES }),
    ).toBeNull();
  });

  it('accepts a .pdf file without a MIME type', () => {
    expect(checkFileInfo({ name: 'UMOWA.PDF', type: '', size: 1000 })).toBeNull();
  });

  it('rejects other file types', () => {
    expect(checkFileInfo({ name: 'photo.png', type: 'image/png', size: 1000 })?.code).toBe(
      'UNSUPPORTED_TYPE',
    );
    expect(checkFileInfo({ name: 'note.txt', type: '', size: 1000 })?.code).toBe(
      'UNSUPPORTED_TYPE',
    );
  });

  it('rejects a file over 10 MB', () => {
    const error = checkFileInfo({
      name: 'large.pdf',
      type: 'application/pdf',
      size: MAX_FILE_BYTES + 1,
    });
    expect(error?.code).toBe('FILE_TOO_LARGE');
    expect(error?.retryable).toBe(false);
  });

  it('rejects an empty file', () => {
    expect(checkFileInfo({ name: 'empty.pdf', type: 'application/pdf', size: 0 })?.code).toBe(
      'INVALID_PDF',
    );
  });
});

describe('hasPdfSignature', () => {
  it('recognises the %PDF- header', async () => {
    expect(await hasPdfSignature(new Blob(['%PDF-1.7\n...']))).toBe(true);
  });

  it('rejects a .pdf file that is not a PDF', async () => {
    expect(await hasPdfSignature(new Blob(['<html>not a PDF</html>']))).toBe(false);
    expect(await hasPdfSignature(new Blob(['%PD']))).toBe(false);
  });
});
