import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist';
import type { PDFOperatorList } from 'pdfjs-dist/types/src/display/api';
// The `?url` import gives the worker's hashed URL with the `base` prefix, so it also loads
// under /pdf-insight/ on GitHub Pages.
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { MAX_FILE_MB, PDF_HEADER_BYTES } from './config';
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
  const head = new Uint8Array(await file.slice(0, PDF_HEADER_BYTES).arrayBuffer());
  return String.fromCharCode(...head).includes(PDF_SIGNATURE);
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

export type PageContent = { text: string; imageShare: number };

// pdf.js operators that paint one raster image.
const IMAGE_OPERATORS = [
  'paintImageXObject',
  'paintInlineImageXObject',
  'paintImageMaskXObject',
] as const;
type OperatorCodes = Record<
  | 'save'
  | 'restore'
  | 'transform'
  | 'paintFormXObjectBegin'
  | 'paintFormXObjectEnd'
  | (typeof IMAGE_OPERATORS)[number],
  number
>;

const determinant = (matrix: unknown): number =>
  Array.isArray(matrix) ? Math.abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) : 1;

// An image fills the unit square of the current transform, so its area is the transform's
// determinant; moves do not change it. Like the backend, overlaps count twice and clips are
// ignored.
export function imageArea(
  { fnArray, argsArray }: Pick<PDFOperatorList, 'fnArray' | 'argsArray'>,
  ops: OperatorCodes,
): number {
  const images = new Set(IMAGE_OPERATORS.map((name) => ops[name]));
  const saved: number[] = [];
  let scale = 1;
  let area = 0;
  fnArray.forEach((fn, index) => {
    const args: unknown = argsArray[index];
    if (fn === ops.save || fn === ops.paintFormXObjectBegin) saved.push(scale);
    if (fn === ops.restore || fn === ops.paintFormXObjectEnd) scale = saved.pop() ?? scale;
    if (fn === ops.transform) scale *= determinant(args);
    if (fn === ops.paintFormXObjectBegin && Array.isArray(args)) scale *= determinant(args[0]);
    if (images.has(fn)) area += scale;
  });
  return area;
}

export async function readPageContent(page: PDFPageProxy): Promise<PageContent> {
  const { OPS } = await loadPdfjs();
  const [content, operators] = await Promise.all([page.getTextContent(), page.getOperatorList()]);
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = page.view;
  return {
    text: content.items.map((item) => ('str' in item ? item.str : '')).join(''),
    imageShare: imageArea(operators, OPS) / ((x1 - x0) * (y1 - y0)),
  };
}

function drawPage(page: PDFPageProxy, canvas: HTMLCanvasElement, scale: number): RenderTask {
  const viewport = page.getViewport({ scale });
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  return page.render({ canvas, viewport });
}

export async function renderPageImage(
  page: PDFPageProxy,
  scale: number,
): Promise<HTMLCanvasElement> {
  const canvas = document.createElement('canvas');
  await drawPage(page, canvas, scale).promise;
  return canvas;
}

// Returns the RenderTask so the component can cancel the render on unmount.
export function renderPage(
  page: PDFPageProxy,
  canvas: HTMLCanvasElement,
  cssWidth: number,
): RenderTask {
  const { width } = page.getViewport({ scale: 1 });
  return drawPage(page, canvas, (cssWidth / width) * window.devicePixelRatio);
}
