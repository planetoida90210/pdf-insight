import { describe, expect, it } from 'vitest';
import { checkFileInfo, hasPdfSignature, MAX_FILE_BYTES } from './pdf';

describe('checkFileInfo', () => {
  it('przyjmuje PDF do 10 MB', () => {
    expect(
      checkFileInfo({ name: 'umowa.pdf', type: 'application/pdf', size: MAX_FILE_BYTES }),
    ).toBeNull();
  });

  it('przyjmuje plik .pdf bez typu MIME', () => {
    expect(checkFileInfo({ name: 'UMOWA.PDF', type: '', size: 1000 })).toBeNull();
  });

  it('odrzuca inne typy plików', () => {
    expect(checkFileInfo({ name: 'zdjecie.png', type: 'image/png', size: 1000 })?.code).toBe(
      'UNSUPPORTED_TYPE',
    );
    expect(checkFileInfo({ name: 'notatka.txt', type: '', size: 1000 })?.code).toBe(
      'UNSUPPORTED_TYPE',
    );
  });

  it('odrzuca plik większy niż 10 MB', () => {
    const error = checkFileInfo({
      name: 'duzy.pdf',
      type: 'application/pdf',
      size: MAX_FILE_BYTES + 1,
    });
    expect(error?.code).toBe('FILE_TOO_LARGE');
    expect(error?.retryable).toBe(false);
  });

  it('odrzuca pusty plik', () => {
    expect(checkFileInfo({ name: 'pusty.pdf', type: 'application/pdf', size: 0 })?.code).toBe(
      'INVALID_PDF',
    );
  });
});

describe('hasPdfSignature', () => {
  it('rozpoznaje nagłówek %PDF-', async () => {
    expect(await hasPdfSignature(new Blob(['%PDF-1.7\n...']))).toBe(true);
  });

  it('odrzuca plik z rozszerzeniem .pdf, który nie jest PDF-em', async () => {
    expect(await hasPdfSignature(new Blob(['<html>to nie PDF</html>']))).toBe(false);
    expect(await hasPdfSignature(new Blob(['%PD']))).toBe(false);
  });
});
