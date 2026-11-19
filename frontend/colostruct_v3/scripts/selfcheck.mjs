/**
 * selfcheck.mjs —— 迁移一致性自检
 *
 * 目的：证明 Vue 版的**数据与导出逻辑**和 Streamlit 版逐字符一致。
 * 编译通过只能说明语法没错，说明不了"导出的 Markdown 有没有多一个空行"。
 *
 * 运行：npm run selfcheck       （或 node scripts/selfcheck.mjs）
 *
 * 覆盖的对照关系：
 *   hydrate_evidence      <- common.py:76-83
 *   build_segment_index   <- common.py:86-91
 *   get_field_val         <- export_panel.py:17-21
 *   buildMarkdown         <- export_panel.py:24-52（含一段黄金用例）
 *   buildPreviewHtml      <- export_panel.py:83-116（含 HTML 转义）
 *   MSG_MAPPING           <- common.py:67-72
 *
 * 这些函数都是纯函数，不依赖 Vue、不需要浏览器，所以能直接在 Node 里跑。
 */

import assert from 'node:assert/strict'

import {
  buildSegmentIndex,
  exportBlockers,
  hasBlockingError,
  hydrateEvidence,
  successTracks,
  timelineDuration,
} from '../src/transcript.js'
import { buildMarkdown, buildPreviewHtml, getFieldValue } from '../src/export.js'
import { resolveAudioUrl } from '../src/media.js'
import { FIELD_LABELS, MSG_MAPPING, displayMessage } from '../src/labels.js'
import demo from '../src/dev/demoPayload.json' with { type: 'json' }

let passed = 0
const failures = []

function check(name, fn) {
  try {
    fn()
    passed += 1
    console.log(`  \u2713 ${name}`)
  } catch (err) {
    failures.push({ name, err })
    console.log(`  \u2717 ${name}`)
    console.log(`      ${err.message.split('\n')[0]}`)
  }
}

// 完整的接口信封 {diagnosis, macro, micro}
// 注意：demo 是"单模块 payload"（audio_url/clean_segments/fields/...），
// 导出函数吃的是外层信封，两者别搞混。
const envelope = {
  diagnosis: { status: 'success', data: demo },
  macro: { status: 'not_uploaded', data: null },
  micro: { status: 'not_uploaded', data: null },
}

console.log('\n[1] hydrate_evidence / build_segment_index  (common.py:76-91)')

const segments = hydrateEvidence(demo.clean_segments)

check('8 个转写片段，且按 start 升序', () => {
  assert.equal(segments.length, 8)
  const starts = segments.map((s) => s.start)
  assert.deepEqual(starts, [...starts].sort((a, b) => a - b))
  assert.equal(segments[0].segment_id, 'seg-001')
})

check('每个片段带上 quotes 数组（时间轴 tooltip 用）', () => {
  assert.deepEqual(segments[0].quotes, [demo.clean_segments[0].text])
})

check('总时长 = max(最晚结束, 60) + 10  (review_panel.py:37)', () => {
  assert.equal(timelineDuration(segments), 70) // 最后一段 24s，被 60 兜底
})

check('segment -> 字段索引正确', () => {
  const idx = buildSegmentIndex(demo.fields)
  assert.deepEqual(idx['seg-001'], ['tumour_site', 'histological_tumour_type'])
  assert.deepEqual(idx['seg-002'], ['tumour_dimension', 'tumour_perforation'])
})

check('15 个字段中 populated=3 / flagged=3 / absent=9', () => {
  const statuses = Object.values(demo.fields).map((f) => f.status)
  assert.equal(statuses.length, 15)
  assert.equal(statuses.filter((s) => s === 'populated').length, 3)
  assert.equal(statuses.filter((s) => s === 'flagged').length, 3)
  assert.equal(statuses.filter((s) => s === 'absent').length, 9)
})

console.log('\n[2] get_field_val  (export_panel.py:17-21)')

check('未编辑时取后端值', () => {
  assert.equal(getFieldValue('tumour_site', demo.fields.tumour_site, {}), 'Rectal')
})

check('后端值为 null 时导出 [Not Mentioned]', () => {
  assert.equal(getFieldValue('operative_procedure', demo.fields.operative_procedure, {}), '[Not Mentioned]')
})

check('编辑后取编辑值，且去掉首尾空格', () => {
  assert.equal(getFieldValue('tumour_site', demo.fields.tumour_site, { tumour_site: '  Rectum  ' }), 'Rectum')
})

check('【遗留行为】清空输入框会回退到后端原值，而不是导出空', () => {
  // 原版是 `if edited is not None and str(edited).strip()`，空串为假 -> 走 fd.value
  assert.equal(getFieldValue('tumour_site', demo.fields.tumour_site, { tumour_site: '' }), 'Rectal')
})

console.log('\n[3] MSG_MAPPING  (common.py:67-72)')

check('后端中文校验信息被翻成英文', () => {
  const zh = '值校验失败：值与引用的否定/肯定极性相反'
  assert.equal(MSG_MAPPING[zh], 'Value validation failed: The polarity (positive/negative) contradicts the quote.')
  assert.equal(displayMessage(zh), MSG_MAPPING[zh])
})

check('未知的中文信息原样保留，不会被吞掉', () => {
  const zh = '某条后端新增的校验信息'
  assert.equal(displayMessage(zh), zh)
})

check('validation_msg 为 {en: "..."} 时取 en', () => {
  assert.equal(displayMessage({ en: 'Value mismatch' }), 'Value mismatch')
})

console.log('\n[4] buildMarkdown  (export_panel.py:24-52)')

check('黄金用例：逐字符比对完整 Markdown 输出', () => {
  const oneFieldPayload = {
    diagnosis: {
      status: 'success',
      data: {
        fields: {
          tumour_site: { value: 'Rectal', evidence: [], status: 'populated', validation_msg: null },
        },
        override_logs: [],
        has_block: false,
      },
    },
    macro: { status: 'success', data: { text: 'MACRO TEXT' } },
    micro: { status: 'not_uploaded', data: null },
  }

  const expected =
    '# Surgical Pathology Report\n' +
    '\n' +
    '## 🩺 Diagnosis\n' +
    '\n' +
    '### Tumour Site\n' +
    'Rectal\n' +
    '\n' +
    '## 🔬 Pathological Section\n' +
    '\n' +
    '### Macro\n' +
    'MACRO TEXT\n' +
    '\n' +
    '### Micro\n' +
    '*[Not Uploaded]*\n' +
    '\n'

  const actual = buildMarkdown(oneFieldPayload, {}, 'MACRO TEXT', '')
  assert.equal(actual, expected)
})

check('15 个字段标签全部出现在导出结果里', () => {
  const md = buildMarkdown(envelope, {}, '', '')
  for (const label of Object.values(FIELD_LABELS)) {
    assert.ok(md.includes(`### ${label}\n`), `缺少字段标签: ${label}`)
  }
})

check('demo 数据里 Macro/Micro 都未上传，导出 [Not Uploaded]', () => {
  const md = buildMarkdown(envelope, {}, '', '')
  assert.ok(md.includes('### Macro\n*[Not Uploaded]*\n\n'))
  assert.ok(md.includes('### Micro\n*[Not Uploaded]*\n\n'))
})

check('服务失败时导出 [Error: ...] 而不是崩掉', () => {
  const failedPayload = {
    diagnosis: { status: 'failed', data: null },
    macro: { status: 'failed', data: null },
    micro: { status: 'failed', data: null },
  }
  const md = buildMarkdown(failedPayload, {}, '', '')
  assert.ok(md.includes('*[Error: AI service temporarily unavailable. Please retry this section.]*'))
  assert.equal(md.match(/\[Error:/g).length, 3)
})

console.log('\n[5] buildPreviewHtml  (export_panel.py:83-116)')

check('生成预览用 HTML，且带 AI 水印容器', () => {
  const html = buildPreviewHtml(envelope, {}, '', '')
  assert.ok(html.startsWith('<div class="watermark-bg">'))
  assert.ok(html.includes('class="md-h1"'))
  assert.ok(html.includes('AI-Assisted Draft') === false) // 水印是 CSS 背景图，不是文本节点
})

check('编辑内容里的 HTML 被转义（防 XSS）', () => {
  const evil = '<img src=x onerror="alert(1)">'
  const html = buildPreviewHtml(envelope, { tumour_site: evil }, '', '')
  assert.ok(!html.includes('<img'), '危险标签没有被转义')
  assert.ok(html.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'))
})

console.log('\n[6] 模块状态判定  (review_panel.py:24-27 / 106-109)')

check('只有成功的模块才出现在时间轴标签页里', () => {
  const tracks = successTracks(envelope)
  assert.equal(tracks.length, 1)
  assert.equal(tracks[0].name, 'Diagnosis')
})

check('demo 的 has_block=false，允许导出', () => {
  assert.equal(hasBlockingError(envelope), false)
})

check('has_block=true 时禁止导出', () => {
  const blocked = structuredClone(envelope)
  blocked.diagnosis.data.has_block = true
  assert.equal(hasBlockingError(blocked), true)
})

check('任一模模块服务失败时禁止导出', () => {
  const failed = structuredClone(envelope)
  failed.macro = { status: 'failed', data: null }
  assert.equal(hasBlockingError(failed), true)
})

check('exportBlockers 能说清到底是哪一条没过', () => {
  // 正常：不拦截，但仍有 3 个 flagged（flagged 本身不拦截）
  const ok = exportBlockers(envelope)
  assert.equal(ok.blocked, false)
  assert.deepEqual(ok.failedModules, [])
  assert.equal(ok.hasBlock, false)
  assert.equal(ok.flaggedCount, 3)

  // 被 has_block 拦
  const blocked = structuredClone(envelope)
  blocked.diagnosis.data.has_block = true
  const b = exportBlockers(blocked)
  assert.equal(b.blocked, true)
  assert.equal(b.hasBlock, true)
  assert.deepEqual(b.failedModules, [])

  // 被模块失败拦，且点名是哪个模块
  const failed = structuredClone(envelope)
  failed.macro = { status: 'failed', data: null }
  failed.micro = { status: 'failed', data: null }
  const f = exportBlockers(failed)
  assert.equal(f.blocked, true)
  assert.deepEqual(f.failedModules, ['macro', 'micro'])
})

console.log('\n[7] resolveAudioUrl  (src/media.js，修组员反馈第 4 条)')

check('Windows 绝对路径 -> 同源 /storage/...', () => {
  assert.equal(
    resolveAudioUrl(
      'D:\\2026-2027\\[TJU]vibecoding\\COLOSTRUCT\\Colostruct v3\\backend\\storage\\audio\\abc123\\stitched.wav',
    ),
    '/storage/audio/abc123/stitched.wav',
  )
})

check('相对路径 storage/... -> /storage/...', () => {
  assert.equal(
    resolveAudioUrl('storage/audio/abc123/stitched.wav'),
    '/storage/audio/abc123/stitched.wav',
  )
})

check('正斜杠绝对路径也能截出 storage 段', () => {
  assert.equal(
    resolveAudioUrl('/home/user/app/storage/audio/case1/stitched.wav'),
    '/storage/audio/case1/stitched.wav',
  )
})

check('已经是 HTTP URL 时原样返回，不重复拼接', () => {
  assert.equal(
    resolveAudioUrl('http://127.0.0.1:8000/api/audio/case1/stitched.wav'),
    'http://127.0.0.1:8000/api/audio/case1/stitched.wav',
  )
})

check('空值返回空串（<audio> 不渲染，而不是塞坏地址）', () => {
  assert.equal(resolveAudioUrl(''), '')
  assert.equal(resolveAudioUrl(null), '')
  assert.equal(resolveAudioUrl(undefined), '')
  assert.equal(resolveAudioUrl('   '), '')
})

check('认不出的绝对路径返回空串，不产出注定 404 的地址', () => {
  // 这个分支会 console.warn，测试里临时静音，避免污染输出
  const originalWarn = console.warn
  console.warn = () => {}
  try {
    // Unix 临时目录，后端没挂载过，无法映射
    assert.equal(resolveAudioUrl('/tmp/xyz/stitched.wav'), '')
  } finally {
    console.warn = originalWarn
  }
})

// ---------------------------------------------------------------------------

console.log('')
if (failures.length > 0) {
  console.log(`\u2717 ${failures.length} 项失败，${passed} 项通过`)
  for (const f of failures) {
    console.log(`\n--- ${f.name} ---`)
    console.log(f.err.stack || f.err.message)
  }
  process.exit(1)
}
console.log(`\u2713 全部 ${passed} 项通过`)
