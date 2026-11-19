// ============================================================================
// mockApi.js —— 本地演示数据，替代对 /api/process 的调用
//
// 对应：legacy_mvp/ui/upload_panel.py 第 15-45 行那个被注释掉的
//       load_mock_payload()（原作者的"万一断网了还可以切回来看 UI 效果"方案）。
//
// 【为什么需要它】
// 后端 /api/process 由 B 组负责，目前还没就绪。没有它前端点一下就报
// Cannot connect to backend，你没法验收界面。这个文件让你在没有后端的
// 情况下也能走完 上传 -> 审校 -> 导出 全流程。
//
// 【什么时候该删掉】
// B 组接口联调通过后，把 UploadPanel.vue 里那个 "Use bundled demo data"
// 的开发选项去掉即可，这个文件和 demoPayload.json 可以一起删。
// ============================================================================

import demoModulePayload from './demoPayload.json'

export const DEMO_STEP_DELAY_MS = 300

/**
 * 把单模块 payload 包成和真实接口一致的 {diagnosis, macro, micro} 信封。
 *
 * @param {{simulateFail?: boolean}} options
 */
export function buildMockPayload({ simulateFail = false } = {}) {
  let data = null
  if (!simulateFail) {
    data = structuredClone(demoModulePayload)
    // 演示数据里的 audio_url 是 "storage/audio/demo_rectal_case.wav"，
    // 但这个文件不在仓库里（storage/ 被 .gitignore 忽略）。
    // 保留它会让前端去请求 /storage/...，连不上后端时终端刷
    //   [vite] http proxy error: ... ECONNREFUSED
    // 而浏览器里只得到一个坏掉的播放器。
    // 演示模式下本来就没有音频可播，置空让界面显示
    // "🔇 Audio unavailable for this track"，既诚实又不吵。
    data.audio_url = ''
  }

  return {
    diagnosis: simulateFail
      ? { status: 'failed', data: null }
      : { status: 'success', data },
    macro: { status: 'not_uploaded', data: null },
    micro: { status: 'not_uploaded', data: null },
  }
}

/** 模拟一次网络往返，让进度条的节奏和真实调用接近 */
export function mockProcessAudio(options = {}) {
  return new Promise((resolve) => {
    setTimeout(() => resolve(buildMockPayload(options)), 400)
  })
}
