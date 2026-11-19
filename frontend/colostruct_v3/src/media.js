// ============================================================================
// media.js —— 把后端给的 audio_url 转成浏览器能播的 URL
//
// 解决的问题（组员反馈第 4 条：macro/micro 音频只有长度、播不出声音）：
//
//   后端 backend/core/pipeline.py:214 返回的是
//       stitched_path = STORAGE_AUDIO_DIR / case_id / "stitched.wav"
//       audio_url = str(stitched_path)
//   也就是文件系统路径，两种形态都可能出现：
//       D:\...\backend\storage\audio\<case_id>\stitched.wav   （STORAGE_DIR 未设置时）
//       storage/audio/<case_id>/stitched.wav                  （STORAGE_DIR=./storage 时，相对路径）
//
//   浏览器把这种字符串当 URL 解析，请求必然 404，<audio> 就只显示时长、放不出声。
//
// 【修法】把路径里 storage/ 之后的部分取出来，拼成同源的 /storage/...，
// 由 Vite 代理（开发）或后端静态挂载（生产）提供文件。
// 这样前端一行都不用改就能播，代价是后端要把 storage 目录挂到 /storage。
// 详见 API_CONTRACT.md「音频文件」一节。
// ============================================================================

import { MEDIA_BASE } from './config.js'

function joinBase(path) {
  return MEDIA_BASE ? `${MEDIA_BASE}/${path}` : `/${path}`
}

/**
 * @param {string|null|undefined} raw 后端返回的 audio_url
 * @returns {string} 可直接放进 <audio src> 的地址；无法解析时返回空串
 */
export function resolveAudioUrl(raw) {
  if (!raw) return ''

  const s = String(raw).trim()
  if (!s) return ''

  // 已经是可用的 URL，原样返回
  if (/^(https?:|blob:|data:)/i.test(s)) return s

  // 统一分隔符，Windows 反斜杠会让 URL 解析出错
  const normalized = s.replace(/\\/g, '/')

  // 主路径：从最后一个 storage/ 开始截取
  // 绝对路径和相对路径都能命中，且与前面多深的目录无关
  const cut = normalized.toLowerCase().lastIndexOf('storage/')
  if (cut >= 0) return joinBase(normalized.slice(cut))

  // 已经是站内相对路径（不以 / 开头、也不是 Windows 盘符）
  const isAbsolute = normalized.startsWith('/') || /^[a-zA-Z]:\//.test(normalized)
  if (!isAbsolute) return joinBase(normalized.replace(/^\/+/, ''))

  // 认不出来的绝对路径：返回空串，宁可让 <audio> 不渲染，
  // 也不要塞一个注定 404 的地址进去（那只会显示一个假的播放器）
  if (typeof console !== 'undefined') {
    console.warn(
      '[colostruct] 无法把 audio_url 转成可播放地址，已跳过播放器：',
      raw,
      '\n后端应当返回 HTTP URL，见 API_CONTRACT.md「音频文件」一节。',
    )
  }
  return ''
}
