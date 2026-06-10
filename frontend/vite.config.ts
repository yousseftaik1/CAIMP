import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/v1': { target: 'http://localhost:8002', changeOrigin: true },
      '/auth':   { target: 'http://localhost:8001', changeOrigin: true },
      '/admin':  { target: 'http://localhost:8001', changeOrigin: true },
      '/ws':     { target: 'ws://localhost:8080',   ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
