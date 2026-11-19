// ============================================================================
// labels.js —— 全部界面文案
// 对应：legacy_mvp/ui/common.py 第 9-72 行（L / FIELD_LABELS / MSG_MAPPING）
//
// 迁移说明：文案一个字都没改，保证 Vue 版和 Streamlit 版显示完全一致。
// 唯一的变化是原来用 str.format 的几条（"{}"，"{:.1f}"）改成了箭头函数，
// 因为 JS 没有 .format() 这种写法。
// ============================================================================

export const L = {
  title: 'Clinical Audio Proofreading Workstation',

  // 顶部导航（common.py:115-121）
  nav_upload: 'Upload',
  nav_review: 'Review',
  nav_export: 'Export',

  // 上传页
  upload_sub: 'Create New Report',
  upload_cap: 'Upload required audio files. You can upload multiple files per category.',
  btn_submit: '🚀 Generate Combined Report',

  // 处理状态区
  status_title: 'Processing Status',
  status_waiting: 'Waiting for file upload...',
  status_info: 'Please click the [Generate Combined Report] button to start.',
  steps: ['ASR transcription...', 'Extracting fields...', 'Formatting text...', 'Verifying...'],
  status_success: '✅ Report generated successfully!',
  btn_proceed_review: '👉 Proceed to Review',

  // 审校页
  review_left: 'Original Transcript / Audio Tracks',
  review_right: 'Final Report Draft',
  confirm_title: 'Confirmation',
  chk_confirm: '✅ I have reviewed and confirmed this draft.',
  btn_export: '👉 Confirm and Proceed to Export',
  btn_return_upload: '🔙 Return to Upload',
  err_not_confirm: '⛔ Please check the confirmation box first.',
  err_validation: '🚨 Validation Failed! Block-level issues or service errors remain.',

  // 导出被拦截时逐条列出原因（新增，legacy 只有上面那句笼统提示）
  export_blocked_title: 'Export is blocked because:',
  blocker_module_failed: (m) => `Module "${m}" returned a service failure.`,
  blocker_has_block:
    'Backend set has_block = true: no value-bearing field passed evidence validation.',
  flagged_does_not_block: 'Flagged fields do not block export by themselves.',

  // 上传了但后端没返回该模块（组员反馈第 3 条）
  warn_uploaded_but_not_processed: (list) =>
    `You uploaded audio for ${list}, but the backend returned status "not_uploaded" for ` +
    `that module — so its transcript and timeline are missing. This is a backend issue: ` +
    `/api/process must run each uploaded module separately and return per-module results.`,

  // 导出页
  export_left: 'Confirm Export',
  export_ready: '✔ Document reviewed',
  export_confirmed: '✔ Doctor confirmed',
  export_fmt: '**Export Format:** Markdown',
  btn_download: '⬇️ Export Markdown',
  btn_return_edit: 'Return to Edit',
  export_right: 'Final Document Preview',
  export_note: '💡 Note: This document is an AI-assisted draft and is **not** directly written into the EHR.',

  // 文档
  doc_title: 'Surgical Pathology Report',
  watermark: 'AI-Assisted Draft',

  // 占位符
  ph_not_mentioned: '[Not Mentioned]',
  not_uploaded: '[Not Uploaded]',
  service_failed: 'AI service temporarily unavailable. Please retry this section.',
  ph_to_verify: '[To Be Verified]',

  // 时间轴
  timeline_hint: 'Click a timeline block to seek audio. Click segment buttons to highlight fields.',
  // common.py:44 —— 原来是 "Active segment: `{}` · {:.1f}s – {:.1f}s"
  active_segment: (sid, start, end) =>
    `Active segment: \`${sid}\` · ${start.toFixed(1)}s – ${end.toFixed(1)}s`,
  clear_highlight: 'Clear highlight',

  // 字段卡片
  override_log: 'View override log',
  source_old: (sid, quote) => `Old evidence (${sid}): ${quote}`,
  source_new: (sid, quote) => `New evidence (${sid}): ${quote}`,
  badge_absent: 'Not Mentioned',
  badge_ok: 'Populated',
  badge_flagged: '⚠ Verify',
  override_badge: '🔄 Overridden',
  flagged_summary: (n) => `${n} field(s) are flagged for verification.`,
  load_error: (e) => `Load failed: ${e}`,
}

// common.py:55-65 —— 15 个病理字段的显示名
export const FIELD_LABELS = {
  tumour_site: 'Tumour Site',
  operative_procedure: 'Operative Procedure',
  tumour_dimension: 'Tumour Dimension',
  tumour_perforation: 'Tumour Perforation',
  relation_to_anterior_peritoneal_reflection: 'Relation to Anterior Peritoneal Reflection',
  plane_of_mesorectal_excision: 'Plane of Mesorectal Excision',
  histological_tumour_type: 'Histological Tumour Type',
  histological_tumour_grade: 'Histological Tumour Grade',
  extent_of_invasion: 'Extent of Invasion',
  lymphatic_and_venous_invasion: 'Lymphatic and Venous Invasion',
  perineural_invasion: 'Perineural Invasion',
  lymph_node_status: 'Lymph Node Status',
  tumour_deposits: 'Tumour Deposits',
  proximal_and_distal_margins: 'Proximal and Distal Margins',
  circumferential_margin: 'Circumferential Margin',
}

// common.py:67-72 —— 后端返回的中文校验信息 -> 英文
export const MSG_MAPPING = {
  '值校验失败：引用未支持值中的核心词':
    'Value validation failed: The quote does not support the core word of the value.',
  '值校验失败：值中的数字与引用不一致':
    'Value validation failed: The number in the value does not match the quote.',
  '证据缺失：字段有值但未提供任何证据':
    'Evidence missing: Value provided but no evidence attached.',
  '值校验失败：值与引用的否定/肯定极性相反':
    'Value validation failed: The polarity (positive/negative) contradicts the quote.',
}

// common.py:210 —— validation_msg 可能是字符串，也可能是 {en: "..."}
export function displayMessage(vm) {
  if (vm == null) return ''
  if (typeof vm === 'string') return MSG_MAPPING[vm] || vm
  return vm.en || ''
}
