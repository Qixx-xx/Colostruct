<template>
  <div v-if="!state.payload" class="export-page">
    <p class="warn-box">{{ L.status_info }}</p>
    <button class="btn" @click="goto('upload')">{{ L.btn_return_upload }}</button>
  </div>

  <div v-else class="export-page">
    <!-- export_panel.py:23 —— st.columns([3, 7]) -->
    <div class="export-grid">
      <!-- 左栏：确认信息 + 下载 -->
      <section class="card export-left">
        <h3>{{ L.export_left }}</h3>
        <p class="success-box">{{ L.export_ready }}</p>
        <p class="success-box">{{ L.export_confirmed }}</p>
        <!-- L.export_fmt 原文是 Markdown 的 "**Export Format:** Markdown" -->
        <p class="caption"><b>Export Format:</b> Markdown</p>

        <button class="submit-btn" @click="download">{{ L.btn_download }}</button>
        <button class="btn" @click="goto('review')">{{ L.btn_return_edit }}</button>
      </section>

      <!-- 右栏：文档预览 -->
      <section class="card export-right">
        <h3>{{ L.export_right }}</h3>
        <!--
          export_panel.py:81-116 —— v-html 等价于 st.markdown(unsafe_allow_html=True)。
          注意：v-html 注入的内容拿不到 scoped 样式，所以 .md-h1 / .md-p / .watermark-bg
          这些类写在 src/style.css 的全局样式里。
        -->
        <div class="doc-preview" v-html="previewHtml" />
      </section>
    </div>

    <p class="info-box">{{ L.export_note }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { L } from '../labels.js'
import { goto, state } from '../store.js'
import { buildMarkdown, buildPreviewHtml, downloadMarkdown } from '../export.js'

const markdown = computed(() =>
  state.payload ? buildMarkdown(state.payload, state.editedFields, state.macroText, state.microText) : '',
)

const previewHtml = computed(() =>
  state.payload
    ? buildPreviewHtml(state.payload, state.editedFields, state.macroText, state.microText)
    : '',
)

// export_panel.py:61 —— st.download_button(data=md_content, file_name="clinical_report.md")
function download() {
  downloadMarkdown(markdown.value, 'clinical_report.md')
}
</script>

<style scoped>
.export-grid {
  display: grid;
  grid-template-columns: 3fr 7fr;
  gap: 24px;
  align-items: start;
}

@media (max-width: 900px) {
  .export-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 20px;
  background: #fafafa;
}

.card h3 {
  margin-top: 0;
}

.export-left .submit-btn {
  width: 100%;
  margin-top: 12px;
  padding: 14px;
  background: #ff4b4b;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: bold;
  cursor: pointer;
}

.export-left .submit-btn:hover {
  background: #f43b3b;
}

.doc-preview {
  max-height: 620px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #eeeeee;
  border-radius: 6px;
}
</style>
