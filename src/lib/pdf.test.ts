import { describe, expect, it } from 'vitest';
import { checkFileInfo, hasPdfSignature, imageArea, MAX_FILE_BYTES } from './pdf';

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

describe('imageArea', () => {
  const ops = {
    save: 1,
    restore: 2,
    transform: 3,
    paintFormXObjectBegin: 4,
    paintFormXObjectEnd: 5,
    paintImageXObject: 6,
    paintInlineImageXObject: 7,
    paintImageMaskXObject: 8,
  };

  it('sizes each image by the transforms around it', () => {
    const scan = [
      [1, []],
      [3, [595, 0, 0, 842, 0, 0]],
      [6, ['scan']],
      [2, []],
    ];
    const logo = [
      [1, []],
      [3, [50, 0, 0, 20, 400, 780]],
      [7, []],
      [2, []],
    ];
    const inForm = [
      [4, [[2, 0, 0, 2, 0, 0], null]],
      [8, ['mask']],
      [5, []],
    ];
    const operators = [...scan, ...logo, ...inForm, [6, ['unscaled']]];
    const list = {
      fnArray: operators.map(([fn]) => fn as number),
      argsArray: operators.map(([, args]) => args as unknown[]),
    };
    expect(imageArea(list, ops)).toBe(595 * 842 + 50 * 20 + 4 + 1);
  });
});
