import type { PDFDocumentProxy } from 'pdfjs-dist';
import {
  MAX_OCR_WORKERS,
  MAX_RENDER_PIXELS,
  OCR_ASSETS_DIR,
  OCR_DPI,
  OCR_LANGS,
  OCR_MIN_CHARS,
  SCAN_IMAGE_SHARE,
  SCAN_TEXT_CHARS,
} from './config';
import { openPdf, readPageContent, renderPageImage, type PageContent } from './pdf';

// One entry of the `ocr` part of POST /api/extract.
export type OcrPage = { page: number; text: string; confidence: number };

// Glyphs without a Unicode mapping come out of pdf.js as control characters.
const UNMAPPED = /[\p{Cc}\uFFFD]/gu;
const PDF_UNITS_PER_INCH = 72;

// The backend's rule: too little text, an unreadable text layer, or a scan under a short one.
export function needsOcr({ text, imageShare }: PageContent): boolean {
  const chars = text.replace(/\s/g, '');
  const unmapped = chars.match(UNMAPPED)?.length ?? 0;
  return (
    chars.length < OCR_MIN_CHARS ||
    unmapped * 2 > chars.length ||
    (imageShare >= SCAN_IMAGE_SHARE && chars.length < SCAN_TEXT_CHARS)
  );
}

// One core stays free for the page.
export function workerCount(cores: number, pages: number): number {
  return Math.min(Math.max(cores - 1, 1), MAX_OCR_WORKERS, pages);
}

// OCR_DPI, lowered for a page so large that its bitmap would pass MAX_RENDER_PIXELS.
export function ocrScale(width: number, height: number): number {
  return Math.min(OCR_DPI / PDF_UNITS_PER_INCH, Math.sqrt(MAX_RENDER_PIXELS / (width * height)));
}

// Reads the pages that need OCR with tesseract.js workers running in parallel.
export async function readScannedPages(
  file: File,
  signal: AbortSignal,
  onProgress: (done: number, total: number) => void,
): Promise<OcrPage[]> {
  const pdf = await openPdf(file);
  try {
    const pages = await pagesToRead(pdf, signal);
    if (pages.length === 0) return [];
    onProgress(0, pages.length);
    return await recognize(pdf, pages, signal, onProgress);
  } finally {
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

// Each worker renders its next page only when it is free: rendering every page first would hold
// all the bitmaps in memory at once. A worker that fails drops out; the backend reads the pages
// it did not finish.
async function recognize(
  pdf: PDFDocumentProxy,
  pages: number[],
  signal: AbortSignal,
  onProgress: (done: number, total: number) => void,
): Promise<OcrPage[]> {
  const { createWorker, OEM } = await import('tesseract.js');
  const assets = `${import.meta.env.BASE_URL}${OCR_ASSETS_DIR}/`;
  const queue = [...pages];
  const results: OcrPage[] = [];

  async function drain() {
    const worker = await createWorker(OCR_LANGS, OEM.LSTM_ONLY, {
      workerPath: `${assets}worker.min.js`,
      corePath: assets,
      langPath: assets,
      workerBlobURL: false,
      cacheMethod: 'none',
    });
    const stop = () => void worker.terminate();
    signal.addEventListener('abort', stop);
    try {
      let number = queue.shift();
      for (; number !== undefined && !signal.aborted; number = queue.shift()) {
        const page = await pdf.getPage(number);
        const { width, height } = page.getViewport({ scale: 1 });
        const canvas = await renderPageImage(page, ocrScale(width, height));
        const { data } = await worker.recognize(canvas);
        canvas.width = 0;
        page.cleanup();
        results.push({ page: number, text: data.text, confidence: data.confidence });
        onProgress(results.length, pages.length);
      }
    } finally {
      signal.removeEventListener('abort', stop);
      stop();
    }
  }

  // A terminated worker never settles its job, so a cancel ends the wait here.
  let onAbort = () => {};
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => reject(signal.reason);
  });
  signal.addEventListener('abort', onAbort);
  try {
    signal.throwIfAborted();
    const count = workerCount(navigator.hardwareConcurrency, pages.length);
    await Promise.race([Promise.allSettled(Array.from({ length: count }, drain)), aborted]);
    return results;
  } finally {
    signal.removeEventListener('abort', onAbort);
  }
}
