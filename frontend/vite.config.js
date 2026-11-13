import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.QML_BACKEND || 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // 后端只认回环地址的 Host/Origin，代理时把 Origin 改成目标地址，否则开发服务器的跨端口请求会被 403
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        configure: (proxy) => proxy.on('proxyReq', (req) => req.removeHeader('origin')),
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, assetsInlineLimit: 0 },
})
