// ============================================================================
// config.js —— 运行时配置
//
// 对应：legacy_mvp/ui/upload_panel.py:108 的
//       os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/process")
//
// 【为什么要单独一层，而不是直接用 import.meta.env】
// 最终形态是"用户把整套东西下载到自己电脑上跑，包括本地大模型，不需要云端"。
// 这种分发场景下，端口和地址很可能要现场改。
// 但 VITE_ 前缀的环境变量是**构建时**写死进 bundle 的 —— 改一次就得
// 重新 npm install && npm run build，对最终用户不现实。
//
// 所以这里支持三级优先级（从左到右覆盖）：
//   1. window.__COLOSTRUCT_CONFIG__   <- 运行时，改 dist/config.js 即刻生效，无需重新构建
//   2. import.meta.env.VITE_*         <- 构建时，开发/CI 用
//   3. 内置默认值                      <- 全本地：127.0.0.1
//
// 全部默认值都指向本机，不含任何云端地址。
// ============================================================================

const env = import.meta.env || {}
const runtime =
  (typeof globalThis !== 'undefined' && globalThis.__COLOSTRUCT_CONFIG__) || {}

/** 去掉末尾斜杠，避免拼出 //storage 这种路径 */
function trimSlash(s) {
  return String(s || '').replace(/\/+$/, '')
}

/**
 * 后端接口地址。
 * 默认 /api/process，由 vite.config.js 的 proxy 转发到 http://127.0.0.1:8000，
 * 这样开发时不会触发跨域。
 */
export const API_URL = runtime.apiUrl || env.VITE_API_URL || '/api/process'

/**
 * 音频文件的服务地址前缀。留空表示同源（拼出来是 /storage/audio/...）。
 *
 * 后端返回的 audio_url 是文件系统路径（见 backend/core/pipeline.py:214），
 * 浏览器无法直接播放，所以要把它映射成一个真正可请求的 URL。
 * 具体规则见 src/media.js。
 */
export const MEDIA_BASE = trimSlash(runtime.mediaBase ?? env.VITE_MEDIA_BASE_URL ?? '')

/**
 * 请求超时（毫秒），默认 300 秒。
 *
 * 真实 ASR + LLM 在 CPU 上处理几分钟音频可能超过这个时间，
 * 一旦超时前端会主动断开并提示"连不上后端"，很容易被误判成后端没启动。
 * 联调时如果 smoke_api.py 报告耗时超过 300 秒，就在这里调大。
 */
export const REQUEST_TIMEOUT_MS = Number(
  runtime.requestTimeoutMs ?? env.VITE_REQUEST_TIMEOUT_MS ?? 300_000,
)
