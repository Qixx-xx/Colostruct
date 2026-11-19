<template>
  <div class="upload-page">
    <h2 class="page-sub">{{ L.upload_sub }}</h2>
    <p class="caption">{{ L.upload_cap }}</p>

    <!-- common.py:60-88 —— st.columns(2) + 两个 st.container(border=True) -->
    <div class="upload-grid">
      <div class="card">
        <h3>🩺 Diagnosis</h3>
        <p class="caption">Extracts 15 structured fields from audio.</p>
        <!--
          common.py:66  st.file_uploader("Upload Diagnosis Audio(s)", type=["mp3","wma"],
                                        accept_multiple_files=True)
          Vue 里就是原生 <input type="file">。原版虽然允许多选，
          但 upload_panel.py:113 只取了 [0]，这里保持一致（见 MIGRATION_NOTES）。
        -->
        <input ref="diagInput" type="file" multiple :accept="ACCEPT" @change="onPick('diag', $event)" />
        <div v-if="fileSelection.diag.length" class="file-status">
          ✅ Selected: {{ names('diag') }}
        </div>
      </div>

      <div class="card">
        <h3>🔬 Pathological Section</h3>
        <p class="caption">Converts audio to plain text directly.</p>

        <div class="sub-upload">
          <label>Macro Audio</label>
          <input type="file" multiple :accept="ACCEPT" @change="onPick('macro', $event)" />
          <div v-if="fileSelection.macro.length" class="file-status">✅ Selected: {{ names('macro') }}</div>
        </div>

        <div class="sub-upload">
          <label>Micro Audio</label>
          <input type="file" multiple :accept="ACCEPT" @change="onPick('micro', $event)" />
          <div v-if="fileSelection.micro.length" class="file-status">✅ Selected: {{ names('micro') }}</div>
        </div>
      </div>
    </div>

    <hr class="divider" />

    <!-- common.py:93 —— 原版就有的 Dev 开关，保留 -->
    <label class="dev-option">
      <input v-model="simulateFail" type="checkbox" />
      ⚙️ (Dev) Simulate AI Service Failure for Diagnosis
    </label>

    <!--
      新增的 Dev 开关（原版没有）：B 组的 /api/process 还没就绪，
      勾上它就用 src/dev/demoPayload.json 走完整流程，不需要后端。
      接口连通后把这个 <label> 和 useDemoData 一起删掉即可。
    -->
    <label class="dev-option">
      <input v-model="useDemoData" type="checkbox" />
      ⚙️ (Dev) Use bundled demo data — no backend needed
    </label>

    <!-- common.py:95-96：没选文件时不显示按钮，改为一句提示 -->
    <button v-if="hasAnyFile" class="submit-btn" :disabled="processing" @click="generate">
      {{ processing ? 'Processing...' : L.btn_submit }}
    </button>
    <p v-else class="info-box">Please upload at least one file to generate the report.</p>

    <!-- 对应 common.py:97-102 的 st.progress + st.empty -->
    <div v-if="processing" class="progress-area">
      <p class="status-line">Current status: <b>{{ progressStep }}</b></p>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progress + '%' }" />
      </div>
    </div>

    <!-- upload_panel.py:159-169 的三种错误分支 -->
    <pre v-if="error" class="error-box">{{ error }}</pre>
    <p v-if="successNote" class="success-box">{{ successNote }}</p>

    <!-- common.py:174-183 处理状态区 -->
    <h3 class="section-title">{{ L.status_title }}</h3>
    <div class="card">
      <p v-if="!hasAnyFile" class="muted">{{ L.status_waiting }}</p>
      <p v-else-if="!state.processed" class="info-box">{{ L.status_info }}</p>
      <template v-else>
        <p class="success-box">{{ L.status_success }}</p>
        <button class="submit-btn" @click="goto('review')">{{ L.btn_proceed_review }}</button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { L } from '../labels.js'
import { applyPayload, fileSelection, goto, state } from '../store.js'
import { processAudio } from '../api.js'
import { mockProcessAudio } from '../dev/mockApi.js'

// legacy_mvp 里是 type=["mp3","wma"]；这里额外放开 .wav，
// 因为后端 pydub 本来就吃 wav，而 demo 音频就是 wav 格式。
const ACCEPT = '.mp3,.wma,.wav'

const simulateFail = ref(false)
const useDemoData = ref(false)

const processing = ref(false)
const progress = ref(0)
const progressStep = ref('')
const error = ref('')
const successNote = ref('')

const hasAnyFile = computed(
  () => fileSelection.diag.length > 0 || fileSelection.macro.length > 0 || fileSelection.micro.length > 0,
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function onPick(kind, event) {
  // 转成普通数组存进 store；File 对象本身保持原样（shallowReactive 不代理它）
  fileSelection[kind] = Array.from(event.target.files || [])
}

function names(kind) {
  return fileSelection[kind].map((f) => f.name).join(', ')
}

// upload_panel.py:96-158 的整段流程
async function generate() {
  error.value = ''
  successNote.value = ''
  processing.value = true
  progress.value = 0

  // upload_panel.py:99-102 —— 四步进度，每步 0.3s
  for (let i = 0; i < L.steps.length; i++) {
    progressStep.value = L.steps[i]
    await sleep(300)
    progress.value = ((i + 1) / L.steps.length) * 100
  }

  try {
    let payload
    if (useDemoData.value) {
      progressStep.value = 'Sending audio to local demo dataset...'
      payload = await mockProcessAudio({ simulateFail: simulateFail.value })
    } else {
      progressStep.value = 'Sending audio to AI backend, please wait...'
      payload = await processAudio({
        // upload_panel.py:112-117 —— 每类只发第一个文件
        diag: fileSelection.diag[0],
        macro: fileSelection.macro[0],
        micro: fileSelection.micro[0],
      })
    }

    // 灌进全局状态（内部会做 hydrate / build_segment_index / 清空编辑缓存）
    applyPayload(payload)

    // upload_panel.py:155-158
    successNote.value = '✅ Processing complete! Redirecting...'
    await sleep(500)
    goto('review')
  } catch (e) {
    // upload_panel.py:163-169
    error.value = e?.message || `Unknown error occurred: ${e}`
  } finally {
    processing.value = false
    progressStep.value = ''
  }
}
</script>

<style scoped>
.upload-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-top: 20px;
}

@media (max-width: 860px) {
  .upload-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fafafa;
  padding: 20px;
}

.card h3 {
  margin-top: 0;
}

.sub-upload {
  margin-bottom: 15px;
}

.sub-upload label {
  display: block;
  font-weight: bold;
  margin-bottom: 5px;
  font-size: 14px;
}

.file-status {
  margin-top: 5px;
  color: #2e7d32;
  font-size: 13px;
  word-break: break-all;
}

.dev-option {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
  font-size: 14px;
  color: #546e7a;
  cursor: pointer;
}

.submit-btn {
  width: 100%;
  margin-top: 18px;
  padding: 15px;
  background: #ff4b4b;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 1.05rem;
  font-weight: bold;
  cursor: pointer;
}

.submit-btn:disabled {
  background: #ffb3b3;
  cursor: not-allowed;
}

.progress-area {
  margin-top: 16px;
}

.status-line {
  margin: 0 0 6px;
  font-size: 14px;
}

.progress-track {
  height: 8px;
  background: #eceff1;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #1e88e5;
  transition: width 0.3s ease;
}

.muted {
  color: #90a4ae;
}
</style>
