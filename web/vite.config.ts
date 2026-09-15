import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API = process.env.SELFCHECK_PORT ?? '7777'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${API}`,
        changeOrigin: true,
        // SSE endpoints must not be buffered by the dev proxy.
        configure: (proxy) => {
          proxy.on('proxyRes', (res) => {
            if (res.headers['content-type']?.includes('text/event-stream')) {
              res.headers['cache-control'] = 'no-cache'
            }
          })
        },
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1200 },
})
