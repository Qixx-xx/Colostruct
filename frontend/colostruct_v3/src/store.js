// ============================================================================
// store.js —— 全局状态，替代 Streamlit 的 st.session_state
// 对应：legacy_mvp/app.py 第 6-13 行 + legacy_mvp/ui/common.py 第 94-108 行
//
// 【为什么需要这个文件】
// Streamlit 每次交互都把整个 app.py 从头跑一遍，所以 upload_panel 和
// review_panel 天然共享 st.session_state。Vue 里三个面板是三个独立组件，
// 组件之间没有共享作用域，所以把共享数据集中放在这个 reactive 对象里。
//
// 【关键差异：不需要 st.rerun()】
// 只要数据放在 reactive 里，改了它，用到它的界面会自动重新渲染。
// 原代码里 11 次 st.rerun() 在 Vue 版中全部消失 —— 这不是漏写，是设计。
//
// 【分工】
// 纯数据函数放在 transcript.js（不依赖 Vue，可单测）；
// 这里只放"状态"和"改状态的动作"。
// ============================================================================

import { reactive, shallowReactive } from 'vue'
import { buildSegmentIndex } from './transcript.js'

// 把纯函数再导出一次，组件统一从 store 取，少记一个路径
export {
  buildSegmentIndex,
  exportBlockers,
  hasBlockingError,
  hasServiceError,
  hydrateEvidence,
  successTracks,
  timelineDuration,
} from './transcript.js'

export const state = reactive({
  page: 'upload',       // app.py:7   当前页面：'upload' | 'review' | 'export'
  highlightField: null, // app.py:8   被高亮的字段名（决定哪张卡片是 📍 蓝框）
  activeSegment: null,  // app.py:9   被选中的 segment_id
  processed: false,     // app.py:10  是否已经成功生成过报告
  payload: null,        // app.py:11  后端返回的完整数据（diagnosis/macro/micro 三块）

  // app.py:13  segment_id -> [字段名]，由 buildSegmentIndex 生成
  segToFields: {},

  // 替代 session_state["input_<字段名>"]：医生改过的字段文本
  editedFields: {},
  // 替代 session_state["input_macro_text"] / ["input_micro_text"]
  macroText: '',
  microText: '',

  // 播放请求。
  // 每次点击「⏱ seg-xxx」或字段下方的「▶ seg-xxx」证据按钮都递增 seq，
  // AudioTimeline 监听 seq 变化，跳到对应片段并播放。
  //
  // 【为什么用递增计数，而不是直接监听 activeSegment】
  // 重复点击同一个片段时 activeSegment 的值没变，光看它不会触发 watch，
  // 用户会觉得"第一次能播，第二次点了没反应"。
  seekRequest: { sid: null, seq: 0 },
})

// 发一次播放请求（组员反馈第 2 条：证据按钮点了不跳转播放）
function requestSeek(sid) {
  if (!sid) return
  state.seekRequest.sid = sid
  state.seekRequest.seq += 1
}

// ---------------------------------------------------------------------------
// 用户选中的音频文件
//
// 【为什么用 shallowReactive 而不是 reactive】
// File 是浏览器内置对象。如果放进 reactive()，Vue 会把它包成 Proxy，
// 而 Proxy 不具备 File 的内部槽位，之后 FormData.append() 会直接抛
// TypeError: Failed to execute 'append' on 'FormData'。
// shallowReactive 只代理最外层对象，数组里的 File 保持原样。
// 这是手写 Vue 时最常见的坑之一。
// ---------------------------------------------------------------------------
export const fileSelection = shallowReactive({
  diag: [], // <= File[]
  macro: [],
  micro: [],
})

// ---------------------------------------------------------------------------
// 联动回调（common.py:95-108）
// 这三个函数就是原来的 st.button(on_click=...)，只不过现在是普通函数调用
// ---------------------------------------------------------------------------

// common.py:95-98 点击 segment 按钮：再点一次取消选中
export function selectSegment(sid) {
  const next = state.activeSegment === sid ? null : sid
  state.activeSegment = next
  const fields = state.segToFields[sid] || []
  state.highlightField = fields.length > 0 && next ? fields[0] : null
  // 选中（而不是取消选中）时跳转播放。
  // 原版只改高亮、不碰音频，所以点了没反应 —— 这里补上。
  if (next) requestSeek(sid)
}

// common.py:101-104 点击某字段的证据按钮：同时选中 segment 和字段
export function selectEvidence(fname, sid) {
  state.activeSegment = sid
  state.highlightField = fname
  // 原版这两个回调都只改状态、不驱动播放，是组员反馈的第 2 条问题
  requestSeek(sid)
}

// common.py:106-108 清除高亮
export function clearHighlight() {
  state.activeSegment = null
  state.highlightField = null
}

// ---------------------------------------------------------------------------
// 接后端数据（upload_panel.py:135-158 那一段）
// ---------------------------------------------------------------------------

// 把刚拿到的 payload 灌进全局状态，并初始化医生可编辑的文本框
export function applyPayload(payload) {
  state.payload = payload

  // upload_panel.py:138-145 —— 只有 diagnosis 成功时才有时间轴和字段索引
  if (payload.diagnosis?.status === 'success') {
    state.segToFields = buildSegmentIndex(payload.diagnosis.data.fields)
  } else {
    state.segToFields = {}
  }

  // upload_panel.py:147-148
  state.activeSegment = null
  state.highlightField = null

  // upload_panel.py:149
  state.processed = true

  // upload_panel.py:151-153 清理输入缓存，准备全新的一轮编辑
  resetEdits(payload)
}

// 对应 common.py:230-234 / review_panel.py:89-101：
// 输入框的初始值 = 后端给的值，值为 null 时给空串（实际显示的是 placeholder）
function resetEdits(payload) {
  const edited = {}
  const diag = payload.diagnosis
  if (diag?.status === 'success') {
    for (const [fname, fd] of Object.entries(diag.data.fields || {})) {
      edited[fname] = fd.value == null ? '' : String(fd.value)
    }
  }
  state.editedFields = edited

  state.macroText = payload.macro?.status === 'success' ? (payload.macro.data?.text ?? '') : ''
  state.microText = payload.micro?.status === 'success' ? (payload.micro.data?.text ?? '') : ''
}

// ---------------------------------------------------------------------------
// 页面跳转（替代 st.session_state.page = "xxx" + st.rerun()）
// ---------------------------------------------------------------------------
export function goto(page) {
  state.page = page
}
