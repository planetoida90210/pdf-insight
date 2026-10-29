import { describe, expect, it } from 'vitest';
import { MAX_OCR_WORKERS, MAX_RENDER_PIXELS, OCR_DPI } from './config';
import { needsOcr, ocrScale, workerCount } from './ocr';

const TEXT = 'Umowa ramowa nr 14/2026 zawarta 12 marca 2026 r. ';
const page = (text: string, imageShare = 0) => ({ text, imageShare });

describe('needsOcr', () => {
  it('reads pages with too little text', () => {
    expect(needsOcr(page(''))).toBe(true);
    expect(needsOcr(page('Strona 1 z 12'))).toBe(true);
    expect(needsOcr(page(TEXT))).toBe(false);
  });

  it('reads a text layer made mostly of unmapped glyphs', () => {
    expect(needsOcr(page('\u0001\u0002\u0003\u0004'.repeat(10) + TEXT.slice(0, 20)))).toBe(true);
    expect(needsOcr(page('\uFFFD'.repeat(30)))).toBe(true);
  });

  it('reads scans under a short text layer', () => {
    expect(needsOcr(page('BATES-000123 '.repeat(4), 0.9))).toBe(true);
    expect(needsOcr(page('BATES-000123 '.repeat(4), 0.05))).toBe(false);
    expect(needsOcr(page(TEXT.repeat(10), 1))).toBe(false);
  });
});

describe('workerCount', () => {
  it('leaves one core free, stays within the cap and the page count', () => {
    expect(workerCount(8, 30)).toBe(Math.min(7, MAX_OCR_WORKERS));
    expect(workerCount(1, 30)).toBe(1);
    expect(workerCount(16, 2)).toBe(2);
  });
});

describe('ocrScale', () => {
  it('renders A4 at the OCR resolution and caps huge pages', () => {
    expect(ocrScale(595, 842)).toBe(OCR_DPI / 72);
    const scale = ocrScale(14400, 14400);
    expect((14400 * scale) ** 2).toBeCloseTo(MAX_RENDER_PIXELS);
  });
});
