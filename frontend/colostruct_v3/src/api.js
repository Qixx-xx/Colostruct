// ============================================================================
// api.js —— 前端唯一的网络出口
// 对应：legacy_mvp/ui/upload_panel.py 第 104-169 行（requests.post 那一段）
//
// 【接口地址怎么配】
// 默认走 /api/process，由 vite.config.js 的 proxy 转发到 http://127.0.0.1:8000。
// 这样做是为了绕过浏览器跨域（CORS）：前端跑在 5173，后端跑在 8000，
// 直接 fetch 完整地址会被浏览器拦下来。
//
// 想改成别的地址，在 frontend/colostruct_v3 下新建 .env.local：
//     VITE_API_URL=http://192.168.1.10:8000/api/process
//
// 【契约以 legacy_mvp 为准】
// B 组的后端只要满足 /api/process 这个契约，前端一行都不用改。
// 详情见同目录 API_CONTRACT.md。
// ============================================================================

// 接口地址来自 config.js（运行时可覆盖，见该文件说明）
import { API_URL } from './config.js'

export { API_URL }

/** 统一的接口异常，message 直接就是可以显示给医生看的英文提示 */
export class ApiError extends Error {}

/**
 * 上传音频，拿回整份报告数据。
 *
 * 对应 upload_panel.py:110-122 —— 表单字段名必须和 Streamlit 版完全一致，
 * 否则 B 组的后端收不到文件：
 *     diag_audio / macro_audio / micro_audio
 *
 * @param {{diag?: File, macro?: File, micro?: File}} files
 * @returns {Promise<{diagnosis: object, macro: object, micro: object}>}
 */
export async function processAudio({ diag, macro, micro } = {}) {
  const form = new FormData()
  if (diag) form.append('diag_audio', diag, diag.name)
  if (macro) form.append('macro_audio', macro, macro.name)
  if (micro) form.append('micro_audio', micro, micro.name)

  let res
  try {
    // upload_panel.py:122 —— 原来设了 timeout=300，这里用 AbortController 等价实现
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 300_000)
    try {
      res = await fetch(API_URL, { method: 'POST', body: form, signal: controller.signal })
    } finally {
      clearTimeout(timer)
    }
  } catch (e) {
    // upload_panel.py:163-166 的 ConnectionError 分支
    throw new ApiError(
      `❌ Cannot connect to backend service (${API_URL}). ` +
        `Please ensure B group's backend is running and the IP address is correct.`,
    )
  }

  // upload_panel.py:159-161
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError(`Server error: ${res.status} - ${text}`)
  }

  let payload
  try {
    payload = await res.json()
  } catch {
    throw new ApiError('Invalid response from backend: the body is not valid JSON.')
  }

  // upload_panel.py:129-133 安全校验：格式不对时别让前端崩掉
  if (!payload || typeof payload !== 'object' || !('diagnosis' in payload)) {
    throw new ApiError(
      "Invalid response format from backend: missing 'diagnosis' field. " +
        "Please check A/B group's code.\n" + JSON.stringify(payload, null, 2),
    )
  }

  return payload
}
