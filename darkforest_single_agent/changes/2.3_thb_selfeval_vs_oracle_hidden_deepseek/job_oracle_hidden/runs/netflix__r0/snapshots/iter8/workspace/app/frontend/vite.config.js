import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxy = {
  '/api': {
    target: process.env.VITE_API_PROXY || 'http://localhost:8000',
    changeOrigin: true,
  },
  '/auth': {
    target: process.env.VITE_API_PROXY || 'http://localhost:8000',
    changeOrigin: true,
  },
  '/health': {
    target: process.env.VITE_API_PROXY || 'http://localhost:8000',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy,
    watch: { ignored: ['**/public/assets/**'] },
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    proxy,
  },
})

