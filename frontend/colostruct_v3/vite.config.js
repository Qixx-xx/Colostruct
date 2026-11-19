import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 代理：前端请求 /api/process -> 转发到 http://127.0.0.1:8000/api/process
    //
    // 为什么必须要有这一段：
    // 前端跑在 5173，后端跑在 8000，浏览器会因同源策略拦下跨域请求。
    // 走这个代理，请求看起来是同源（都发到 5173），由 Vite 在服务端转发，
    // 就绕开了 CORS。B 组的 FastAPI 那边也就不必额外配 CORS 中间件。
    //
    // 只有 `npm run dev` 走这里；`npm run build` 产出的静态文件需要
    // 由 Nginx / 后端自己托管，届时要么同源部署，要么后端加 CORS 头。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 音频文件。
      // 后端返回的 audio_url 是文件系统路径，前端把它映射成 /storage/...
      // （见 src/media.js），这里转发给后端。
      // 对应后端需要做的：把 storage 目录挂到 /storage 静态目录，
      // 例如 FastAPI 的 app.mount("/storage", StaticFiles(directory="storage"))。
      '/storage': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
