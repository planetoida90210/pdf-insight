import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// GitHub Pages nie pozwala ustawić nagłówków, więc CSP trafia do <meta>. Tylko w buildzie:
// serwer deweloperski Vite wstrzykuje skrypty i style inline, które ta polityka by zablokowała.
function contentSecurityPolicy(apiUrl: string | undefined): Plugin {
  const content = [
    "default-src 'self'",
    `connect-src 'self' ${apiUrl ? new URL(apiUrl).origin : ''}`,
    "img-src 'self' data: blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join('; ');
  return {
    name: 'content-security-policy',
    apply: 'build',
    transformIndexHtml: () => [
      {
        tag: 'meta',
        attrs: { 'http-equiv': 'Content-Security-Policy', content },
        injectTo: 'head-prepend',
      },
    ],
  };
}

// GitHub Pages serwuje aplikację spod https://<user>.github.io/pdf-insight/
export default defineConfig(({ mode }) => ({
  base: '/pdf-insight/',
  plugins: [react(), contentSecurityPolicy(loadEnv(mode, '.').VITE_API_URL)],
}));
