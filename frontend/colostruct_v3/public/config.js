// 运行时配置（可选文件）
//
// 这个文件会被原样复制到 dist/ 下。用户在**自己电脑上**部署时，
// 直接改 dist/config.js 即可生效，不需要重新 npm install / npm run build。
//
// 只写需要覆盖的项，其余留空走默认值（默认全部指向本机）。
//
// 例：后端跑在 8000，音频由后端在 /storage 下静态提供
// window.__COLOSTRUCT_CONFIG__ = {
//   apiUrl: 'http://127.0.0.1:8000/api/process',
//   mediaBase: 'http://127.0.0.1:8000',
//   requestTimeoutMs: 900000,
// }
//
// 说明：
//   apiUrl     后端 /api/process 完整地址。留空 = 同源 /api/process
//              （开发时由 vite.config.js 的 proxy 转发到 127.0.0.1:8000）
//   mediaBase  音频地址前缀。留空 = 同源（拼出 /storage/audio/...）
//              也可以填 http://127.0.0.1:8000 直连后端
//   requestTimeoutMs  请求超时毫秒数，留空 = 300000（5 分钟）
//              真实 ASR+LLM 在 CPU 上可能更久，联调时按 smoke_api.py 报的耗时调大
window.__COLOSTRUCT_CONFIG__ = window.__COLOSTRUCT_CONFIG__ || {}
