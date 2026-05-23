import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:4999',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'static',
    // decrypt.js is a deferred Emscripten artifact; keep warnings focused on chunks larger than it.
    chunkSizeWarningLimit: 5200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, '/')
          if (!normalized.includes('/node_modules/')) return undefined
          if (
            normalized.includes('/vue/') ||
            normalized.includes('/vue-router/') ||
            normalized.includes('/pinia/') ||
            normalized.includes('/vue-i18n/')
          ) {
            return 'vendor-vue'
          }
          if (normalized.includes('/@vicons/')) {
            return 'vendor-icons'
          }
          if (normalized.includes('/video.js/')) {
            return 'vendor-media-video'
          }
          if (normalized.includes('/flv.js/')) {
            return 'vendor-media-flv'
          }
          if (normalized.includes('/axios/')) {
            return 'vendor-http'
          }
          return undefined
        }
      }
    }
  }
})
