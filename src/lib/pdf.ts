import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist';
// Import `?url` daje adres workera z hashem i prefiksem `base`, więc działa także pod /pdf-insight/ na GitHub Pages.
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { MAX_FILE_MB } from './config';
import { AppError } from './errors';

export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

const PDF_SIGNATURE = '%PDF-';

type FileInfo = Pick<File, 'name' | 'type' | 'size'>;

// Szybkie sprawdzenie bez czytania pliku. Część systemów nie podaje typu MIME, wtedy decyduje rozszerzenie.
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

// pdf.js (~1 MB) ładujemy dopiero przy pierwszym pliku, żeby nie spowalniać startu strony.
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
    // Każde otwarcie ma własny worker pdf.js; bez destroy() zostaje on w pamięci.
    void task.destroy();
    if (error instanceof pdfjs.PasswordException) throw new AppError('ENCRYPTED_PDF');
    throw new AppError('INVALID_PDF');
  }
}

// Pełna walidacja przed wysyłką: typ, rozmiar, sygnatura `%PDF-` i to, czy pdf.js potrafi plik otworzyć.
export async function validatePdf(file: File): Promise<void> {
  const infoError = checkFileInfo(file);
  if (infoError) throw infoError;
  if (!(await hasPdfSignature(file))) throw new AppError('UNSUPPORTED_TYPE');

  const pdf = await openPdf(file);
  await pdf.loadingTask.destroy();
}

// Zwraca RenderTask, żeby komponent mógł przerwać rysowanie przy odmontowaniu.
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
