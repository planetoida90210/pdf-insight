import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { Worker } from 'tesseract.js';
import {
  MAX_OCR_WORKERS,
  MAX_RENDER_PIXELS,
  OCR_ASSETS_DIR,
  OCR_DPI,
  OCR_LANGS,
  OCR_MIN_CHARS,
  OCR_NOISE_CONFIDENCE,
  OCR_SURE_CONFIDENCE,
  SCAN_IMAGE_SHARE,
  SCAN_TEXT_CHARS,
} from './config';
import { openPdf, readPageContent, renderPageImage, type PageContent } from './pdf';

// One entry of the `ocr` part of POST /api/extract.
export type OcrPage = { page: number; text: string; confidence: number };

// Glyphs without a Unicode mapping come out of pdf.js as control characters.
const UNMAPPED = /[\p{Cc}\uFFFD]/gu;
const PDF_UNITS_PER_INCH = 72;

// Too little text, an unreadable text layer, or a scan under a short one: needs_ocr in
// backend/app/ocr.py.
export function needsOcr({ text, imageShare }: PageContent): boolean {
  const chars = text.replace(/\s/g, '');
  const unmapped = chars.match(UNMAPPED)?.length ?? 0;
  return (
    chars.length < OCR_MIN_CHARS ||
    unmapped * 2 > chars.length ||
    (imageShare >= SCAN_IMAGE_SHARE && chars.length < SCAN_TEXT_CHARS)
  );
}

// The percentage of words read at OCR_SURE_CONFIDENCE among those that are not noise, which
// decides whether the backend has vision read the page: page_confidence in backend/app/ocr.py.
export function pageConfidence(confidences: number[]): number {
  const words = confidences.filter((confidence) => confidence >= OCR_NOISE_CONFIDENCE);
  if (words.length === 0) return 0;
  const sure = words.filter((confidence) => confidence >= OCR_SURE_CONFIDENCE);
  return (100 * sure.length) / words.length;
}

// One core stays free for the page.
export function workerCount(cores: number, pages: number): number {
  return Math.min(Math.max(cores - 1, 1), MAX_OCR_WORKERS, pages);
}

// OCR_DPI, lowered for a page so large that its bitmap would pass MAX_RENDER_PIXELS.
export function ocrScale(width: number, height: number): number {
  return Math.min(OCR_DPI / PDF_UNITS_PER_INCH, Math.sqrt(MAX_RENDER_PIXELS / (width * height)));
}

// Starts a tesseract.js worker. Its download and start-up are what a scan waits for before the
// first page is read, so the pipeline starts one as soon as a file is chosen.
export async function startOcrWorker(): Promise<Worker> {
  const { createWorker, OEM } = await import('tesseract.js');
  const assets = `${import.meta.env.BASE_URL}${OCR_ASSETS_DIR}/`;
  return createWorker(OCR_LANGS, OEM.LSTM_ONLY, {
    workerPath: `${assets}worker.min.js`,
    corePath: assets,
    langPath: assets,
    workerBlobURL: false,
    cacheMethod: 'none',
  });
}

// Ends a worker, also one still starting. A worker that failed to start has nothing to end.
export function stopOcrWorker(worker: Promise<Worker>): void {
  void worker.then((started) => started.terminate()).catch(() => {});
}

// Reads the pages that need OCR with tesseract.js workers running in parallel. `first` is a
// worker the caller started early; it is ended here, used or not.
export async function readScannedPages(
  file: File,
  first: Promise<Worker>,
  signal: AbortSignal,
  onProgress: (done: number, total: number) => void,
): Promise<OcrPage[]> {
  const pdf = await openPdf(file);
  try {
    const pages = await pagesToRead(pdf, signal);
    if (pages.length === 0) return [];
    onProgress(0, pages.length);
    const workers = [first];
    const start = () => pageReader(pdf, workers.pop() ?? startOcrWorker());
    const count = workerCount(navigator.hardwareConcurrency, pages.length);
    return await readInParallel(pages, count, start, signal, onProgress);
  } finally {
    stopOcrWorker(first);
    void pdf.loadingTask.destroy();
  }
}

async function pagesToRead(pdf: PDFDocumentProxy, signal: AbortSignal): Promise<number[]> {
  const pages: number[] = [];
  for (let number = 1; number <= pdf.numPages; number += 1) {
    signal.throwIfAborted();
    const page = await pdf.getPage(number);
    if (needsOcr(await readPageContent(page))) pages.push(number);
    page.cleanup();
  }
  return pages;
}

type PageReader<T> = { read: (page: number) => Promise<T>; stop: () => void };

async function pageReader(
  pdf: PDFDocumentProxy,
  ready: Promise<Worker>,
): Promise<PageReader<OcrPage>> {
  const worker = await ready;
  return {
    stop: () => void worker.terminate(),
    read: async (number) => {
      const page = await pdf.getPage(number);
      const { width, height } = page.getViewport({ scale: 1 });
      const canvas = await renderPageImage(page, ocrScale(width, height));
      const { data } = await worker.recognize(canvas, {}, { blocks: true });
      canvas.width = 0;
      page.cleanup();
      const words = (data.blocks ?? []).flatMap((block) =>
        block.paragraphs.flatMap((paragraph) => paragraph.lines.flatMap((line) => line.words)),
      );
      return {
        page: number,
        text: data.text,
        confidence: pageConfidence(words.map((word) => word.confidence)),
      };
    },
  };
}

// Reads the pages with `count` readers in parallel. A reader takes its next page only when it is
// free: rendering every page first would hold all the bitmaps in memory at once. A page that fails
// is read once more, by a new reader, since the failure may have broken the worker. The backend
// reads a page that failed twice and the pages of a reader that could not start.
export async function readInParallel<T>(
  pages: number[],
  count: number,
  start: () => Promise<PageReader<T>>,
  signal: AbortSignal,
  onProgress: (done: number, total: number) => void,
): Promise<T[]> {
  const queue = [...pages];
  const failed = new Set<number>();
  const results: T[] = [];

  async function drain(): Promise<void> {
    const reader = await start();
    signal.addEventListener('abort', reader.stop);
    let page = queue.shift();
    try {
      for (; page !== undefined && !signal.aborted; page = queue.shift()) {
        results.push(await reader.read(page));
        onProgress(results.length, pages.length);
      }
    } catch {
      if (page !== undefined && !failed.has(page)) {
        failed.add(page);
        queue.unshift(page);
      }
    } finally {
      signal.removeEventListener('abort', reader.stop);
      reader.stop();
    }
    if (queue.length > 0 && !signal.aborted) await drain();
  }

  // A terminated worker never settles its job, so a cancel ends the wait here.
  let onAbort = () => {};
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => reject(signal.reason);
  });
  signal.addEventListener('abort', onAbort);
  try {
    signal.throwIfAborted();
    await Promise.race([Promise.allSettled(Array.from({ length: count }, drain)), aborted]);
    return results;
  } finally {
    signal.removeEventListener('abort', onAbort);
  }
}
