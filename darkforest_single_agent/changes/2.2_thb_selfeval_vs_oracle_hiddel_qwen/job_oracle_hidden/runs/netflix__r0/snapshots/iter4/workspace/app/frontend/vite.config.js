import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://127.0.0.1:8010',
      '/auth': 'http://127.0.0.1:8010',
      '/health': 'http://127.0.0.1:8010',
      '/media': 'http://127.0.0.1:8010',
    },
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1200 },
})
