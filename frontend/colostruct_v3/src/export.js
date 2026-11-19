// ============================================================================
// export.js —— 生成 Markdown 文本和预览用的 HTML
// 对应：legacy_mvp/ui/export_panel.py 第 17-116 行
//
// 迁移说明：这里刻意保持"纯函数"，不碰任何界面。好处是导出的 Markdown
// 和 Streamlit 版逐字符一致，你可以直接把两边导出的 .md 拿去 diff 验证。
// ============================================================================

import { L, FIELD_LABELS } from './labels.js'

// export_panel.py:17-21
// 优先级：医生改过的值 > 后端给的值 > [Not Mentioned]
// 注意这里有个 legacy 行为被原样保留了：医生把输入框清空后，
// 导出会回退到后端原值，而不是导出空。见 MIGRATION_NOTES.md「已知遗留行为」。
export function getFieldValue(fname, fd, editedFields) {
  const edited = editedFields?.[fname]
  if (edited != null && String(edited).trim()) return String(edited).trim()
  if (fd?.value != null) return String(fd.value)
  return L.ph_not_mentioned
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// export_panel.py:24-52
export function buildMarkdown(payload, editedFields, macroText, microText) {
  let md = `# ${L.doc_title}\n\n`

  md += '## 🩺 Diagnosis\n\n'
  const diag = payload.diagnosis
  if (diag.status === 'not_uploaded') {
    md += `*${L.not_uploaded}*\n\n`
  } else if (diag.status === 'failed') {
    md += `*[Error: ${L.service_failed}]*\n\n`
  } else {
    for (const [fname, fd] of Object.entries(diag.data.fields || {})) {
      const label = FIELD_LABELS[fname] || fname
      md += `### ${label}\n${getFieldValue(fname, fd, editedFields)}\n\n`
    }
  }

  md += '## 🔬 Pathological Section\n\n'

  md += '### Macro\n'
  if (payload.macro.status === 'not_uploaded') {
    md += `*${L.not_uploaded}*\n\n`
  } else if (payload.macro.status === 'failed') {
    md += `*[Error: ${L.service_failed}]*\n\n`
  } else {
    md += `${macroText}\n\n`
  }

  md += '### Micro\n'
  if (payload.micro.status === 'not_uploaded') {
    md += `*${L.not_uploaded}*\n\n`
  } else if (payload.micro.status === 'failed') {
    md += `*[Error: ${L.service_failed}]*\n\n`
  } else {
    md += `${microText}\n\n`
  }

  return md
}

// export_panel.py:83-116
// 注意：Streamlit 版是逐段拼 HTML 字符串再 st.markdown(unsafe_allow_html=True)，
// Vue 里用 v-html 渲染，所以所有用户可控文本都必须转义。
export function buildPreviewHtml(payload, editedFields, macroText, microText) {
  let html = '<div class="watermark-bg">'
  html += `<h1 class="md-h1">${escapeHtml(L.doc_title)}</h1>`

  html += '<h2 class="md-h2">🩺 Diagnosis</h2>'
  const diag = payload.diagnosis
  if (diag.status === 'not_uploaded') {
    html += `<p class="md-p" style="color:red;">${L.not_uploaded}</p>`
  } else if (diag.status === 'failed') {
    html += `<p class="md-p" style="color:red;">[Error: ${L.service_failed}]</p>`
  } else {
    for (const [fname, fd] of Object.entries(diag.data.fields || {})) {
      const label = FIELD_LABELS[fname] || fname
      html += `<h3 class="md-h3">${escapeHtml(label)}</h3>`
      html += `<p class="md-p">${escapeHtml(getFieldValue(fname, fd, editedFields))}</p>`
    }
  }

  html += '<h2 class="md-h2">🔬 Pathological Section</h2>'

  html += '<h3 class="md-h3">Macro</h3>'
  if (payload.macro.status === 'not_uploaded') {
    html += `<p class="md-p" style="color:red;">${L.not_uploaded}</p>`
  } else if (payload.macro.status === 'failed') {
    html += `<p class="md-p" style="color:red;">[Error: ${L.service_failed}]</p>`
  } else {
    html += `<p class="md-p">${escapeHtml(macroText)}</p>`
  }

  html += '<h3 class="md-h3">Micro</h3>'
  if (payload.micro.status === 'not_uploaded') {
    html += `<p class="md-p" style="color:red;">${L.not_uploaded}</p>`
  } else if (payload.micro.status === 'failed') {
    html += `<p class="md-p" style="color:red;">[Error: ${L.service_failed}]</p>`
  } else {
    html += `<p class="md-p">${escapeHtml(microText)}</p>`
  }

  html += '</div>'
  return html
}

// export_panel.py:61 —— 替代 st.download_button
export function downloadMarkdown(content, filename = 'clinical_report.md') {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 等待 1 秒再释放。如果紧跟着 click 就 revoke，部分浏览器会来不及接管
  // 这个 Blob，表现为"点了下载没反应"或下到一个空文件。
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
