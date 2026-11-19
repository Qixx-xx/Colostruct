// ============================================================================
// transcript.js —— 纯数据函数（不依赖 Vue，可单独测试）
// 对应：legacy_mvp/ui/common.py 第 76-91 行
//
// 【为什么单独一个文件】
// store.js 里的状态要靠 Vue 的 reactive，跑不了纯 Node；
// 但"数据怎么整形"是纯逻辑，跟界面无关。抽出来之后：
//   1) scripts/selfcheck.mjs 可以直接 import 它做断言，不需要浏览器
//   2) 未来接后端契约测试也能复用
// store.js 会把这些函数原样再导出一次，组件那边不用改 import 路径。
// ============================================================================

// common.py:76-83 hydrate_evidence
// 把后端返回的 clean_segments 变成按时间排序、带 quotes 数组的 segment 列表。
// 注意原版是用 dict 去重（同一个 segment_id 后来的覆盖前面的），这里用 Map 保持同样语义。
export function hydrateEvidence(cleanSegments) {
  const byId = new Map()
  for (const cs of cleanSegments || []) {
    byId.set(cs.segment_id, {
      segment_id: cs.segment_id,
      start: Number(cs.start),
      end: Number(cs.end),
      text: cs.text ?? '',
      quotes: [cs.text ?? ''],
    })
  }
  return [...byId.values()].sort((a, b) => a.start - b.start)
}

// common.py:86-91 build_segment_index
// 反过来：遍历 15 个字段的 evidence，得到 segment_id -> [引用它的字段名]
export function buildSegmentIndex(fields) {
  const idx = {}
  for (const [fname, fd] of Object.entries(fields || {})) {
    for (const ev of fd.evidence || []) {
      if (!idx[ev.segment_id]) idx[ev.segment_id] = []
      idx[ev.segment_id].push(fname)
    }
  }
  return idx
}

// review_panel.py:24-27 —— 哪些模块有可播放的时间轴
export function successTracks(payload) {
  const tracks = []
  if (!payload) return tracks
  if (payload.diagnosis?.status === 'success') tracks.push({ name: 'Diagnosis', data: payload.diagnosis.data })
  if (payload.macro?.status === 'success') tracks.push({ name: 'Macro', data: payload.macro.data })
  if (payload.micro?.status === 'success') tracks.push({ name: 'Micro', data: payload.micro.data })
  return tracks
}

// review_panel.py:107 / export_panel.py —— 任一模模块服务失败就算有错
export function hasServiceError(payload) {
  if (!payload) return false
  return ['diagnosis', 'macro', 'micro'].some((k) => payload[k]?.status === 'failed')
}

// review_panel.py:106-109 —— 导出前的完整校验
// 返回具体原因，让界面能说清"到底哪一条没过"，而不是只给一句 Validation Failed
export function exportBlockers(payload) {
  if (!payload) {
    return { blocked: false, failedModules: [], hasBlock: false, flaggedFields: [], flaggedCount: 0 }
  }

  const failedModules = ['diagnosis', 'macro', 'micro'].filter((k) => payload[k]?.status === 'failed')

  const diag = payload.diagnosis
  const hasBlock = diag?.status === 'success' && !!diag.data?.has_block

  // flagged 只是"需要人工核对"，它本身不拦截导出（legacy 就是这个规则），
  // 列出来是为了让人看懂 has_block 和 flagged 的区别。
  const flaggedFields =
    diag?.status === 'success'
      ? Object.entries(diag.data?.fields || {})
          .filter(([, fd]) => fd.status === 'flagged')
          .map(([name]) => name)
      : []

  return {
    blocked: failedModules.length > 0 || hasBlock,
    failedModules,
    hasBlock,
    flaggedFields,
    flaggedCount: flaggedFields.length,
  }
}

// 只关心"能不能导出"的布尔版本
export function hasBlockingError(payload) {
  return exportBlockers(payload).blocked
}

// review_panel.py:37 —— 时间轴总时长：最晚结束时间，至少 60s，再留 10s 余量
export function timelineDuration(segments) {
  const ends = (segments || []).map((s) => s.end)
  return Math.max(...ends, 60.0) + 10.0
}
