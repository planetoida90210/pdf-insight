import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { OCR_ASSETS_DIR } from './src/lib/config.ts';

// tesseract.js loads its worker, WASM core and language data at run time. The app serves them
// itself, so no request goes to a CDN: the LSTM-only cores (tesseract.js picks one by the
// browser's SIMD support) and the language models. The models are tessdata_fast, byte for byte
// the files the backend image installs (tesseract-ocr-pol, tesseract-ocr-eng). On the test scans
// they read a page a third faster than the integer tessdata_best models, and as accurately.
const TESSERACT_FILES = [
  'tesseract.js/dist/worker.min.js',
  'tesseract.js-core/tesseract-core-lstm.wasm.js',
  'tesseract.js-core/tesseract-core-simd-lstm.wasm.js',
  'tesseract.js-core/tesseract-core-relaxedsimd-lstm.wasm.js',
  './src/assets/tessdata/pol.traineddata.gz',
  './src/assets/tessdata/eng.traineddata.gz',
];

function tesseractAssets(): Plugin {
  return {
    name: 'tesseract-assets',
    apply: 'build',
    async generateBundle() {
      for (const file of TESSERACT_FILES) {
        const resolved = await this.resolve(file);
        if (!resolved) throw new Error(`Cannot find ${file}`);
        this.emitFile({
          type: 'asset',
          fileName: `${OCR_ASSETS_DIR}/${file.split('/').pop()}`,
          source: await this.fs.readFile(resolved.id),
        });
      }
    },
  };
}

// GitHub Pages cannot set response headers, so the CSP goes into a <meta> tag. Build only:
// the Vite dev server injects inline scripts and styles that this policy would block.
function contentSecurityPolicy(apiUrl: string | undefined): Plugin {
  return {
    name: 'content-security-policy',
    apply: 'build',
    transformIndexHtml() {
      // Without the API address the app cannot send a single request, so the build stops.
      if (!apiUrl) throw new Error('VITE_API_URL is required for the build');
      const content = [
        "default-src 'self'",
        `connect-src ${new URL(apiUrl).origin}`,
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
      ].join('; ');
      return [
        {
          tag: 'meta',
          attrs: { 'http-equiv': 'Content-Security-Policy', content },
          injectTo: 'head-prepend',
        },
      ];
    },
  };
}

// GitHub Pages serves the app from https://<user>.github.io/pdf-insight/
export default defineConfig(({ mode }) => ({
  base: '/pdf-insight/',
  plugins: [react(), contentSecurityPolicy(loadEnv(mode, '.').VITE_API_URL), tesseractAssets()],
}));
