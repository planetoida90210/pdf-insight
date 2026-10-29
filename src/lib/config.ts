// Size limit from the brief (F-01); the backend checks the same limit.
export const MAX_FILE_MB = 10;

// The backend decides which pages need OCR (needs_ocr in backend/app/extraction.py) and reads
// them itself when the browser did not. The browser reads them first, by the same values:
export const OCR_MIN_CHARS = 25; // setting OCR_MIN_CHARS
export const SCAN_TEXT_CHARS = 200; // SCAN_TEXT_CHARS
export const OCR_LANGS = 'pol+eng'; // setting OCR_LANG
export const OCR_DPI = 200; // OCR_SCALE in backend/app/ocr.py
export const MAX_RENDER_PIXELS = 9_000_000; // MAX_RENDER_PIXELS in backend/app/ocr.py

// Each tesseract.js worker holds a WASM heap of about 100 MB.
export const MAX_OCR_WORKERS = 6;
// The build copies tesseract.js's worker, core and language data here (vite.config.ts).
export const OCR_ASSETS_DIR = 'tesseract';
