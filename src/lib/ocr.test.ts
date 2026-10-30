import { describe, expect, it, vi } from 'vitest';
import { MAX_OCR_WORKERS, MAX_RENDER_PIXELS, OCR_DPI } from './config';
import { needsOcr, ocrScale, pageConfidence, readInParallel, workerCount } from './ocr';

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

describe('pageConfidence', () => {
  it('is the share of sure words among those that are not noise', () => {
    expect(pageConfidence([96, 95, 93, 86, 40, 12, 0])).toBe(75);
    expect(pageConfidence([96, 95, 93, 91])).toBe(100);
    expect(pageConfidence([30, 12])).toBe(0);
    expect(pageConfidence([])).toBe(0);
  });
});

describe('readInParallel', () => {
  // Readers numbered from 1 in start order; `read` gets the page and the reader's number.
  const readers = (read: (page: number, reader: number) => Promise<number>) => {
    const stopped: number[] = [];
    let started = 0;
    const start = async () => {
      const reader = (started += 1);
      return { read: (page: number) => read(page, reader), stop: () => stopped.push(reader) };
    };
    return { start, stopped, started: () => started };
  };
  const signal = new AbortController().signal;
  const fail = () => Promise.reject(new Error('RuntimeError: Aborted(OOM)'));

  it('reads every page, reports progress and ends every worker', async () => {
    const { start, stopped } = readers(async (page) => page);
    const progress: number[] = [];
    const pages = await readInParallel([1, 2, 3, 4], 2, start, signal, (done) =>
      progress.push(done),
    );
    expect(pages.sort()).toEqual([1, 2, 3, 4]);
    expect(progress).toEqual([1, 2, 3, 4]);
    expect(stopped.sort()).toEqual([1, 2]);
  });

  it('reads a failed page once more with a new worker', async () => {
    const { start, stopped } = readers(async (page, reader) =>
      page === 2 && reader === 1 ? fail() : page,
    );
    await expect(readInParallel([1, 2, 3], 1, start, signal, () => {})).resolves.toEqual([1, 2, 3]);
    expect(stopped).toEqual([1, 2]);
  });

  it('leaves a page that fails twice to the backend and reads the rest', async () => {
    const { start, started } = readers(async (page) => (page === 2 ? fail() : page));
    await expect(readInParallel([1, 2, 3], 1, start, signal, () => {})).resolves.toEqual([1, 3]);
    expect(started()).toBe(3);
  });

  it('leaves the pages to the other workers when one cannot start', async () => {
    const { start } = readers(async (page) => page);
    const flaky = vi.fn(start).mockRejectedValueOnce(new Error('NetworkError'));
    const pages = await readInParallel([1, 2, 3], 2, flaky, signal, () => {});
    expect(pages).toEqual([1, 2, 3]);
  });

  it('ends the wait and the workers at once on a cancel', async () => {
    const controller = new AbortController();
    let reading = 0;
    const { start, stopped } = readers(() => {
      reading += 1;
      return new Promise(() => {});
    });
    const pages = readInParallel([1, 2, 3], 2, start, controller.signal, () => {});
    await vi.waitFor(() => expect(reading).toBe(2));
    controller.abort(new Error('cancelled'));
    await expect(pages).rejects.toThrow('cancelled');
    expect(stopped.sort()).toEqual([1, 2]);
  });
});
