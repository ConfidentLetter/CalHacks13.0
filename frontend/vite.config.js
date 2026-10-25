import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Same-origin hosting (e.g. behind a Cloudflare Tunnel): the page and the backend share one
// public hostname, and these paths are forwarded to the local FastAPI bridge on :8000.
const BACKEND = process.env.STUDBUD_BACKEND || 'http://127.0.0.1:8000'
const proxy = {
  '/api': { target: BACKEND, changeOrigin: true },
  '/files': { target: BACKEND, changeOrigin: true },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy, allowedHosts: true },
})
