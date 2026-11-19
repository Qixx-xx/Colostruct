<template>
  <!-- review_panel.py:9-14 —— 没有数据时不允许停留在这里 -->
  <div v-if="!state.payload" class="review-page">
    <p class="warn-box">{{ L.status_info }}</p>
    <button class="btn" @click="goto('upload')">{{ L.btn_return_upload }}</button>
  </div>

  <div v-else class="review-page">
    <!--
      组员反馈第 3 条：上传了 diagnosis 之后 macro/micro 的预览消失了。
      前端这侧的渲染逻辑没有问题（三个上传框、两个文本框都是无条件渲染的），
      真正的矛盾是：用户明明传了 macro/micro，后端却返回 not_uploaded。
      与其静默显示 [Not Uploaded] 让人以为界面坏了，不如把这个矛盾直接说出来。
    -->
    <div v-if="mismatch.length" class="warn-box">
      {{ L.warn_uploaded_but_not_processed(mismatch.join(', ')) }}
    </div>

    <!-- review_panel.py:18 —— st.columns([4.5, 5.5]) -->
    <div class="review-grid">
      <!-- ==================== 左栏：音频 / 转写 ==================== -->
      <section class="col">
        <h3 class="section-title">{{ L.review_left }}</h3>

        <p v-if="!tracks.length" class="warn-box">No audio timelines available.</p>

        <template v-else>
          <!-- review_panel.py:32 —— st.tabs(["🎧 Diagnosis", ...]) -->
          <div class="tabs">
            <button
              v-for="(t, i) in tracks"
              :key="t.name"
              class="tab"
              :class="{ active: i === activeTab }"
              @click="activeTab = i"
            >
              🎧 {{ t.name }}
            </button>
          </div>

          <div v-if="currentTrack" class="tab-panel">
            <AudioTimeline
              :segments="currentSegments"
              :active-segment="state.activeSegment"
              :duration="currentDuration"
              :hint="L.timeline_hint"
              :audio-url="currentAudioUrl"
              :seek-request="state.seekRequest"
            />

            <!-- review_panel.py:43-48 —— 当前选中的 segment 和它的引文 -->
            <div v-if="activeSeg" class="active-seg">
              <p class="caption">{{ L.active_segment(activeSeg.segment_id, activeSeg.start, activeSeg.end) }}</p>
              <blockquote v-for="(q, i) in activeSeg.quotes" :key="i">{{ q }}</blockquote>
            </div>
            <button v-if="state.activeSegment" class="btn small" @click="clearHighlight">
              {{ L.clear_highlight }}
            </button>

            <!-- review_panel.py:50-58 —— 固定高度 250 的可滚动片段列表 -->
            <div class="seg-list">
              <div v-for="seg in currentSegments" :key="seg.segment_id" class="seg-row">
                <button
                  class="seg-btn"
                  :class="{ primary: seg.segment_id === state.activeSegment }"
                  @click="selectSegment(seg.segment_id)"
                >
                  ⏱ {{ seg.segment_id }}
                </button>
                <div class="seg-meta">
                  <b>{{ seg.start.toFixed(1) }}s – {{ seg.end.toFixed(1) }}s</b>
                  <div class="seg-text">{{ seg.text }}</div>
                </div>
                <span class="seg-count">{{ fieldCount(seg.segment_id) }} f</span>
              </div>
            </div>
          </div>
        </template>

        <!-- review_panel.py:60-61 —— 部分模块失败时提示 -->
        <p v-if="hasServiceError(state.payload)" class="error-box">
          ❌ {{ L.service_failed }} (Partial service failure)
        </p>
      </section>

      <!-- ==================== 右栏：报告草稿 ==================== -->
      <section class="col">
        <h3 class="section-title">{{ L.review_right }}</h3>

        <div class="draft-box">
          <h2 class="module-title">🩺 Diagnosis</h2>

          <p v-if="diagStatus === 'not_uploaded'" class="error-box">{{ L.not_uploaded }}</p>
          <p v-else-if="diagStatus === 'failed'" class="error-box">🚨 {{ L.service_failed }}</p>
          <template v-else>
            <!-- review_panel.py:74-76 —— 15 张字段卡片 -->
            <FieldCard
              v-for="f in diagFields"
              :key="f.name"
              :field-name="f.name"
              :field-data="f.data"
              :active-segment="state.activeSegment"
              :highlighted="state.highlightField === f.name"
              :override-log="overrideMap[f.name] || null"
              @select-evidence="selectEvidence"
            />
          </template>

          <hr class="divider" />

          <h2 class="module-title">🔬 Pathological Section</h2>

          <!-- review_panel.py:81-101 —— Macro / Micro 两个可编辑文本框 -->
          <h4 class="sub-title">Macro</h4>
          <template v-if="macroStatus === 'not_uploaded'">
            <p class="error-box">{{ L.not_uploaded }}</p>
            <textarea class="big-text" :value="L.not_uploaded" disabled rows="5" />
          </template>
          <template v-else-if="macroStatus === 'failed'">
            <p class="error-box">🚨 {{ L.service_failed }}</p>
            <textarea class="big-text" :value="L.service_failed" disabled rows="5" />
          </template>
          <textarea v-else v-model="state.macroText" class="big-text" rows="5" />

          <h4 class="sub-title">Micro</h4>
          <template v-if="microStatus === 'not_uploaded'">
            <p class="error-box">{{ L.not_uploaded }}</p>
            <textarea class="big-text" :value="L.not_uploaded" disabled rows="5" />
          </template>
          <template v-else-if="microStatus === 'failed'">
            <p class="error-box">🚨 {{ L.service_failed }}</p>
            <textarea class="big-text" :value="L.service_failed" disabled rows="5" />
          </template>
          <textarea v-else v-model="state.microText" class="big-text" rows="5" />
        </div>

        <!-- review_panel.py:104-119 —— 确认 + 导出 -->
        <h3 class="section-title">{{ L.confirm_title }}</h3>
        <label class="check-line">
          <input v-model="confirm" type="checkbox" />
          {{ L.chk_confirm }}
        </label>
        <button class="submit-btn" @click="tryExport">{{ L.btn_export }}</button>
        <p v-if="confirmError" class="error-box">{{ confirmError }}</p>

        <!--
          导出被拦截时逐条说明原因。
          legacy 只有一句 "🚨 Validation Failed!"，看不出到底哪一条没过，
          排查时只能猜 —— 这里把判定依据摊开。
        -->
        <div v-if="blockers.blocked" class="blocker-box">
          <p class="blocker-title">{{ L.export_blocked_title }}</p>
          <ul>
            <li v-for="m in blockers.failedModules" :key="m">{{ L.blocker_module_failed(m) }}</li>
            <li v-if="blockers.hasBlock">{{ L.blocker_has_block }}</li>
          </ul>
        </div>
        <p v-if="blockers.flaggedCount > 0" class="caption blocker-note">
          {{ L.flagged_summary(blockers.flaggedCount) }} {{ L.flagged_does_not_block }}
        </p>

        <hr class="divider" />
        <button class="btn" @click="backToUpload">{{ L.btn_return_upload }}</button>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { L } from '../labels.js'
import { resolveAudioUrl } from '../media.js'
import {
  clearHighlight,
  exportBlockers,
  fileSelection,
  goto,
  hasServiceError,
  hydrateEvidence,
  selectEvidence,
  selectSegment,
  state,
  successTracks,
  timelineDuration,
} from '../store.js'
import AudioTimeline from './AudioTimeline.vue'
import FieldCard from './FieldCard.vue'

const activeTab = ref(0)
const confirm = ref(false)
const confirmError = ref('')

// review_panel.py:24-27
const tracks = computed(() => successTracks(state.payload))

// payload 换了（重新生成报告）就回到第一个标签页
watch(tracks, () => {
  activeTab.value = 0
  confirm.value = false
  confirmError.value = ''
})

const currentTrack = computed(() => tracks.value[activeTab.value] || null)

// review_panel.py:36 —— 每个标签页各自 hydrate 自己的 clean_segments
const currentSegments = computed(() =>
  currentTrack.value ? hydrateEvidence(currentTrack.value.data.clean_segments || []) : [],
)

// review_panel.py:37 —— 总时长：最晚的结束时间，至少 60s，再留 10s 余量
const currentDuration = computed(() => timelineDuration(currentSegments.value))

// 组员反馈第 4 条：音频只有长度、播不出声音。
// 后端给的是文件系统路径，必须转换成可请求的 URL，见 src/media.js。
const currentAudioUrl = computed(() =>
  currentTrack.value ? resolveAudioUrl(currentTrack.value.data.audio_url) : '',
)

// 「用户传了，但后端说没传」的模块列表
const mismatch = computed(() => {
  if (!state.payload) return []
  const uploaded = {
    Diagnosis: fileSelection.diag.length > 0,
    Macro: fileSelection.macro.length > 0,
    Micro: fileSelection.micro.length > 0,
  }
  const status = {
    Diagnosis: state.payload.diagnosis?.status,
    Macro: state.payload.macro?.status,
    Micro: state.payload.micro?.status,
  }
  return Object.keys(uploaded).filter((k) => uploaded[k] && status[k] === 'not_uploaded')
})

const activeSeg = computed(
  () => currentSegments.value.find((s) => s.segment_id === state.activeSegment) || null,
)

// review_panel.py:58 —— 这个片段被多少个字段引用
function fieldCount(sid) {
  return (state.segToFields[sid] || []).length
}

// review_panel.py:68-76
const diagStatus = computed(() => state.payload.diagnosis.status)

const diagFields = computed(() => {
  const data = state.payload.diagnosis.data
  if (!data?.fields) return []
  return Object.entries(data.fields).map(([name, fd]) => ({ name, data: fd }))
})

// review_panel.py:74 —— override_logs 转成 {字段名: 日志}
const overrideMap = computed(() => {
  const logs = state.payload.diagnosis.data?.override_logs || []
  const map = {}
  for (const o of logs) map[o.field_name] = o
  return map
})

const macroStatus = computed(() => state.payload.macro.status)
const microStatus = computed(() => state.payload.micro.status)

// review_panel.py:106-109 —— 有服务错误，或者后端说 has_block，都不许导出
const blockers = computed(() => exportBlockers(state.payload))
const hasError = computed(() => blockers.value.blocked)

// review_panel.py:112-119
function tryExport() {
  if (!confirm.value) {
    confirmError.value = L.err_not_confirm
    return
  }
  if (hasError.value) {
    confirmError.value = L.err_validation
    return
  }
  confirmError.value = ''
  goto('export')
}

// review_panel.py:122-125
function backToUpload() {
  goto('upload')
  clearHighlight()
}
</script>

<style scoped>
.review-grid {
  display: grid;
  grid-template-columns: 4.5fr 5.5fr;
  gap: 24px;
  align-items: start;
}

@media (max-width: 1000px) {
  .review-grid {
    grid-template-columns: 1fr;
  }
}

.col {
  min-width: 0;
}

/* ---------- 左栏 ---------- */
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid #e0e0e0;
  margin-bottom: 12px;
}

.tab {
  padding: 8px 14px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #78909c;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
}

.tab.active {
  color: #1e88e5;
  border-bottom-color: #1e88e5;
  font-weight: 600;
}

.active-seg {
  margin: 10px 0;
}

.active-seg blockquote {
  margin: 4px 0;
  padding: 6px 10px;
  border-left: 3px solid #1e88e5;
  background: #f5f9ff;
  color: #37474f;
  font-size: 14px;
}

.seg-list {
  max-height: 250px;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 6px;
  margin-top: 10px;
}

.seg-row {
  display: grid;
  grid-template-columns: 130px 1fr 40px;
  gap: 10px;
  align-items: center;
  padding: 6px 4px;
  border-bottom: 1px solid #f1f1f1;
}

.seg-row:last-child {
  border-bottom: none;
}

.seg-btn {
  padding: 6px 4px;
  background: #ffffff;
  border: 1px solid #cfd8dc;
  border-radius: 6px;
  color: #546e7a;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.seg-btn.primary {
  background: #1e88e5;
  border-color: #1e88e5;
  color: #ffffff;
}

.seg-meta {
  font-size: 12px;
  color: #546e7a;
  min-width: 0;
}

.seg-text {
  color: #78909c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.seg-count {
  font-size: 11px;
  color: #90a4ae;
  text-align: right;
}

/* ---------- 右栏 ---------- */
.draft-box {
  max-height: 650px;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
}

.module-title {
  font-size: 1.15rem;
  margin: 4px 0 8px;
}

.sub-title {
  margin: 12px 0 6px;
  font-size: 14px;
  color: #37474f;
}

.big-text {
  width: 100%;
  padding: 8px 10px;
  border: 2px solid #1e88e5;
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  color: #000000;
  background: #ffffff;
  resize: vertical;
}

.big-text:disabled {
  background: #f5f5f5;
  border-color: #ececec;
  color: #9e9e9e;
}

.check-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  margin-bottom: 12px;
  cursor: pointer;
}

.blocker-box {
  margin-top: 12px;
  padding: 10px 12px;
  background: #fff8e1;
  border: 1px solid #ffe082;
  border-left-width: 4px;
  border-radius: 6px;
}

.blocker-title {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: #e65100;
}

.blocker-box ul {
  margin: 0;
  padding-left: 18px;
}

.blocker-box li {
  font-size: 12.5px;
  color: #795548;
  line-height: 1.6;
}

.blocker-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: #90a4ae;
}

.submit-btn {
  width: 100%;
  padding: 14px;
  background: #ff4b4b;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: bold;
  cursor: pointer;
}

.submit-btn:hover {
  background: #f43b3b;
}
</style>
