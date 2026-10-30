import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backend = process.env.VITE_PROXY_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  build: { assetsDir: 'static' },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': backend,
      '/auth': backend,
      '/health': backend,
    },
  },
});
