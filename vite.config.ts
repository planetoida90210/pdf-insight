import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

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
  plugins: [react(), contentSecurityPolicy(loadEnv(mode, '.').VITE_API_URL)],
}));
