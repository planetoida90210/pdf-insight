import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist';
// The `?url` import gives the worker's hashed URL with the `base` prefix, so it also loads
// under /pdf-insight/ on GitHub Pages.
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { MAX_FILE_MB } from './config';
import { AppError } from './errors';

export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

const PDF_SIGNATURE = '%PDF-';

type FileInfo = Pick<File, 'name' | 'type' | 'size'>;

// Quick check without reading the file. Some systems send no MIME type; then the extension decides.
export function checkFileInfo(file: FileInfo): AppError | null {
  const looksLikePdf =
    file.type === 'application/pdf' || (file.type === '' && /\.pdf$/i.test(file.name));
  if (!looksLikePdf) return new AppError('UNSUPPORTED_TYPE');
  if (file.size > MAX_FILE_BYTES) return new AppError('FILE_TOO_LARGE');
  if (file.size === 0) return new AppError('INVALID_PDF');
  return null;
}

export async function hasPdfSignature(file: Blob): Promise<boolean> {
  const head = new Uint8Array(await file.slice(0, PDF_SIGNATURE.length).arrayBuffer());
  return String.fromCharCode(...head) === PDF_SIGNATURE;
}

// pdf.js (~1 MB) loads with the first file, so it does not slow down the page start.
async function loadPdfjs() {
  const pdfjs = await import('pdfjs-dist');
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs;
}

export async function openPdf(file: File): Promise<PDFDocumentProxy> {
  const pdfjs = await loadPdfjs();
  const task = pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) });
  try {
    return await task.promise;
  } catch (error) {
    // Every open has its own pdf.js worker; without destroy() it stays in memory.
    void task.destroy();
    if (error instanceof pdfjs.PasswordException) throw new AppError('ENCRYPTED_PDF');
    throw new AppError('INVALID_PDF');
  }
}

// Full check before upload: type, size, the `%PDF-` signature and whether pdf.js can open it.
export async function validatePdf(file: File): Promise<void> {
  const infoError = checkFileInfo(file);
  if (infoError) throw infoError;
  if (!(await hasPdfSignature(file))) throw new AppError('UNSUPPORTED_TYPE');

  const pdf = await openPdf(file);
  await pdf.loadingTask.destroy();
}

// Returns the RenderTask so the component can cancel the render on unmount.
export function renderPage(
  page: PDFPageProxy,
  canvas: HTMLCanvasElement,
  cssWidth: number,
): RenderTask {
  const base = page.getViewport({ scale: 1 });
  const scale = (cssWidth / base.width) * window.devicePixelRatio;
  const viewport = page.getViewport({ scale });
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  return page.render({ canvas, viewport });
}
