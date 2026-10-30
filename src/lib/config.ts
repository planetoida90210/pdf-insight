// Size limit from the brief (F-01); the backend checks the same limit.
export const MAX_FILE_MB = 10;
// PDF readers accept the `%PDF-` signature anywhere in the first 1024 bytes, and so does the
// backend (HEADER_WINDOW in backend/app/upload.py).
export const PDF_HEADER_BYTES = 1024;

// The browser OCRs the pages the backend would, by the values in backend/app/ocr.py and its
// settings. The backend reads any of them the browser did not send.
export const OCR_MIN_CHARS = 25; // setting OCR_MIN_CHARS
export const SCAN_TEXT_CHARS = 200; // SCAN_TEXT_CHARS
export const SCAN_IMAGE_SHARE = 0.5; // SCAN_IMAGE_SHARE
export const OCR_LANGS = 'pol+eng'; // setting OCR_LANG
export const OCR_DPI = 200; // OCR_SCALE
export const MAX_RENDER_PIXELS = 9_000_000; // MAX_RENDER_PIXELS
export const OCR_NOISE_CONFIDENCE = 50; // NOISE_CONFIDENCE
export const OCR_SURE_CONFIDENCE = 90; // SURE_CONFIDENCE

// Each tesseract.js worker holds a WASM heap of about 100 MB.
export const MAX_OCR_WORKERS = 6;
// The build copies tesseract.js's worker, core and language data here (vite.config.ts).
export const OCR_ASSETS_DIR = 'tesseract';
