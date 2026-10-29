import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// GitHub Pages serwuje aplikację spod https://<user>.github.io/pdf-insight/
export default defineConfig({
  base: '/pdf-insight/',
  plugins: [react()],
});
