import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server and `vite preview` forward /api to FastAPI, so the browser sees one
// origin: the HttpOnly refresh cookie (SameSite=Strict, Path=/api/v1/auth) just works.
const api = { '/api': { target: process.env.NETRIBEAT_API || 'http://127.0.0.1:8000', changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: api },
  preview: { port: 4173, strictPort: true, proxy: api },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.js'],
    globals: true,
  },
});
