import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxyTarget = process.env.VITE_API_PROXY || 'http://backend:8000'
const proxyConfig = {
  '/api': { target: proxyTarget, changeOrigin: true },
  '/auth': { target: proxyTarget, changeOrigin: true },
  '/health': { target: proxyTarget, changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: proxyConfig,
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: proxyConfig,
  },
})
