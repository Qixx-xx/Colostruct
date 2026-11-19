<template>
  <div class="timeline-wrap">
    <!--
      对应 common.py:127 —— <audio id="..." src="..." controls>
      Streamlit 版即使没有音频地址也照渲染（变成一个坏掉的播放器），
      这里没有地址就不渲染，省一个明显的错误控件。
    -->
    <audio v-if="audioUrl" ref="audioEl" :src="audioUrl" controls class="audio" />
    <!--
      没有可播放地址时明确说明，而不是留一个坏掉的播放器让人猜。
      后端返回文件系统路径时会走到这里（见 src/media.js 的说明）。
    -->
    <p v-else class="no-audio">🔇 Audio unavailable for this track (no playable URL from backend).</p>

    <!--
      对应 common.py:128-131 的 timeline 容器 + 133-158 那段 <script>。
      原版用 iframe + 手拼 JS 字符串（还要把 json.dumps 的 "</" 转义掉），
      Vue 里就是下面这个 v-for，30 行搞定，不用转义、不用管 iframe 高度。
    -->
    <div class="timeline" role="list">
      <span class="timeline-label">TIMELINE</span>
      <button
        v-for="seg in segments"
        :key="seg.segment_id"
        class="tl-block"
        :class="{ active: seg.segment_id === activeSegment }"
        :style="blockStyle(seg)"
        :title="seg.quotes.join(' | ')"
        role="listitem"
        @click="seek(seg)"
      >
        {{ seg.segment_id }}
      </button>
    </div>

    <p class="timeline-hint">{{ hint }}</p>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  segments: { type: Array, default: () => [] }, // hydrateEvidence() 的输出
  activeSegment: { type: String, default: null },
  duration: { type: Number, default: 60 }, // review_panel.py:37 算出来的总时长
  hint: { type: String, default: '' },
  audioUrl: { type: String, default: '' },
  // 播放请求 {sid, seq}：seq 每变一次就跳转播放一次
  seekRequest: { type: Object, default: () => ({ sid: null, seq: 0 }) },
})

const audioEl = ref(null)

// common.py:150-151 —— left / width 都按总时长的百分比算
function blockStyle(seg) {
  const left = (seg.start / props.duration) * 100
  // Math.max(..., 0.2)：极短的片段至少占 0.2%，否则肉眼看不见
  const width = Math.max(((seg.end - seg.start) / props.duration) * 100, 0.2)
  return { left: `${left}%`, width: `${width}%` }
}

// common.py:154 —— 点击方块只做"跳转播放"，不改选中状态。
// 选中是靠下面的 segment 按钮触发的，两件事在原版里就是分开的。
function seek(seg) {
  const el = audioEl.value
  if (!el) return
  el.currentTime = seg.start
  // 浏览器可能因为自动播放策略拒绝 play()，这里吞掉异常避免控制台刷红
  el.play()?.catch(() => {})
}

// 【新增】响应播放请求。
// 组员反馈第 2 条：右栏字段下方那些 seg-xxx 红色按钮点了不跳转播放。
// 原版这两个回调（common.py:95-104）只改高亮状态，从来不碰音频，
// 所以"点了没反应"是设计遗漏，不是使用问题。
// 现在无论从哪个按钮选中片段，都会跳到这里 seek + play。
watch(
  () => props.seekRequest.seq,
  () => {
    const sid = props.seekRequest.sid
    if (!sid) return
    const seg = props.segments.find((s) => s.segment_id === sid)
    if (seg) seek(seg)
  },
  // flush: 'sync' 很关键。默认的异步 watcher 会在微任务里执行，
  // 那时已经脱离了点击事件的调用栈，Chrome/Safari 的自动播放策略可能直接
  // 拒绝 play()，表现就是"跳转了但没声音"。同步执行保证仍在用户手势内。
  { flush: 'sync' },
)
</script>

<style scoped>
.audio {
  width: 100%;
  margin-bottom: 12px;
}

.no-audio {
  margin: 0 0 12px;
  padding: 8px 10px;
  background: #f5f5f5;
  border-left: 3px solid #bdbdbd;
  border-radius: 4px;
  font-size: 12px;
  color: #757575;
}

.timeline {
  position: relative;
  height: 84px;
  background: #fafafa;
  border: 1px solid #e6e6e6;
  border-radius: 8px;
  overflow: hidden;
}

.timeline-label {
  position: absolute;
  top: 6px;
  left: 8px;
  font-size: 10px;
  color: #9e9e9e;
  letter-spacing: 0.5px;
}

.tl-block {
  position: absolute;
  top: 24px;
  height: 24px;
  padding: 0 2px;
  border: 1px solid #ffffff;
  border-radius: 4px;
  background: #c8e6c9;
  color: #1b5e20;
  font-size: 10px;
  line-height: 22px;
  font-family: inherit;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.tl-block.active {
  background: #ff7043;
  color: #ffffff;
  box-shadow: 0 0 0 2px #ffab91;
}

.timeline-hint {
  margin: 4px 0 0;
  font-size: 11px;
  color: #999;
}
</style>
