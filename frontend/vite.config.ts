/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In development the Django API runs on :8000; proxying keeps the browser on one origin.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: {
    sourcemap: true,
    // MapLibre alone is ~1.1 MB minified (300 KB gzip); it's lazy-loaded in its own chunk.
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Keep the large map library in its own long-cacheable chunk.
        manualChunks: (id) => (id.includes('maplibre-gl') ? 'maplibre' : undefined),
      },
    },
  },
  worker: { format: 'es' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
