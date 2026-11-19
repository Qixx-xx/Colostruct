<template>
  <div class="field-card">
    <!--
      对应 common.py:199-206 的 st.markdown(卡片头部)。
      原版用 f-string 拼 HTML + unsafe_allow_html，这里用模板绑定 + :style，
      好处是 html.escape 那一套完全不需要了 —— Vue 默认就会转义。
    -->
    <div class="fc-head" :style="{ background: palette.bg, borderColor: border, borderLeftColor: accent }">
      <span class="fc-label">
        <span v-if="highlighted">📍 </span>{{ label }}
        <span v-if="overrideLog" class="fc-override">{{ L.override_badge }}</span>
      </span>
      <span class="fc-badge" :style="{ color: palette.badgeColor }">{{ palette.badge }}</span>
    </div>

    <!-- common.py:209-213 —— 只在 flagged 且后端给了校验信息时显示 -->
    <div v-if="flagged && displayMsg" class="fc-warn" :style="{ background: palette.bg, borderColor: border }">
      ⚠ {{ displayMsg }}
    </div>

    <!--
      对应 common.py:215-241：原来的 st.text_area(key=f"input_{fname}")。
      v-model 直接读写 store.js 里的 editedFields，医生改了值，
      导出页拿到的就是改后的值 —— 这就是 session_state 在 Vue 里的等价物。
    -->
    <textarea v-model="edited" class="fc-input" :placeholder="placeholder" rows="2" />

    <!-- common.py:244-250 —— 证据按钮，选中时变蓝 -->
    <div v-if="evidence.length" class="fc-evidence" :style="{ gridTemplateColumns: gridCols }">
      <button
        v-for="ev in evidence"
        :key="ev.segment_id"
        class="ev-btn"
        :class="{ primary: ev.segment_id === activeSegment }"
        @click="$emit('select-evidence', fieldName, ev.segment_id)"
      >
        ▶ {{ ev.segment_id }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FIELD_LABELS, L, displayMessage } from '../labels.js'
import { state } from '../store.js'

const props = defineProps({
  fieldName: { type: String, required: true },
  fieldData: { type: Object, required: true }, // 后端的字段对象 {value, evidence, status, validation_msg}
  activeSegment: { type: String, default: null },
  highlighted: { type: Boolean, default: false }, // 是不是当前 📍 高亮的卡片
  overrideLog: { type: Object, default: null },
})

defineEmits(['select-evidence'])

const label = computed(() => FIELD_LABELS[props.fieldName] || props.fieldName)
const evidence = computed(() => props.fieldData.evidence || [])

// common.py:182-183 —— 注意 absent 的条件包含 "value 为 null"，
// 不只是 status === 'absent'。原版就是这个逻辑。
const absent = computed(() => props.fieldData.status === 'absent' || props.fieldData.value == null)
const flagged = computed(() => props.fieldData.status === 'flagged' && !absent.value)

// common.py:186-193 —— 三种状态三套配色
const palette = computed(() => {
  if (absent.value) {
    return { bg: '#f7f7f7', border: '#ececec', accent: '#bdbdbd', badge: L.badge_absent, badgeColor: '#9e9e9e' }
  }
  if (flagged.value) {
    return { bg: '#fff8e1', border: '#ffe082', accent: '#f9a825', badge: L.badge_flagged, badgeColor: '#e65100' }
  }
  return { bg: '#f4f9f4', border: '#dbe9db', accent: '#43a047', badge: L.badge_ok, badgeColor: '#2e7d32' }
})

// common.py:193 —— 被高亮时边框和左侧色条都变成主题蓝
const border = computed(() => (props.highlighted ? '#1e88e5' : palette.value.border))
const accent = computed(() => (props.highlighted ? '#1e88e5' : palette.value.accent))

const displayMsg = computed(() => displayMessage(props.fieldData.validation_msg))

// common.py:239
const placeholder = computed(() => (absent.value ? '✏️ CLICK HERE TO EDIT...' : '✏️ Edit here...'))

// 双向绑定到全局 store，替代 st.session_state["input_<字段名>"]
const edited = computed({
  get: () => state.editedFields[props.fieldName] ?? '',
  set: (v) => {
    state.editedFields[props.fieldName] = v
  },
})

// common.py:245 —— st.columns(min(len(evidence), 3))
const gridCols = computed(() => `repeat(${Math.min(evidence.value.length, 3)}, minmax(0, 1fr))`)
</script>

<style scoped>
.field-card {
  margin-top: 10px;
}

.fc-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 4px 14px;
  border: 1px solid;
  border-left-width: 4px;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
}

.fc-label {
  font-weight: 600;
  font-size: 13px;
  color: #37474f;
}

.fc-override {
  font-size: 11px;
  color: #6a1b9a;
  margin-left: 6px;
}

.fc-badge {
  font-size: 11px;
  white-space: nowrap;
}

.fc-warn {
  padding: 0 14px 6px 14px;
  border-left: 1px solid;
  border-right: 1px solid;
  font-size: 12px;
  color: #e65100;
}

/*
  common.py:216-227 原来是一段强制注入的 CSS，把 Streamlit 的 textarea
  刷成"白底蓝框"。在 Vue 里我们自己的 DOM 自己说了算，直接写样式就行。
*/
.fc-input {
  display: block;
  width: 100%;
  padding: 8px 10px;
  background: #ffffff;
  border: 2px solid #1e88e5;
  border-radius: 0 0 8px 8px;
  color: #000000;
  font-family: inherit;
  font-size: 15px;
  font-weight: 500;
  resize: vertical;
}

.fc-input::placeholder {
  font-weight: 400;
  color: #90a4ae;
}

.fc-input:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(30, 136, 229, 0.18);
}

.fc-evidence {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.ev-btn {
  padding: 6px 8px;
  background: #ffffff;
  color: #1e88e5;
  border: 1px solid #1e88e5;
  border-radius: 6px;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ev-btn.primary {
  background: #1e88e5;
  color: #ffffff;
}

.ev-btn:hover {
  background: #e3f2fd;
  color: #1565c0;
}

.ev-btn.primary:hover {
  background: #1565c0;
  color: #ffffff;
}
</style>
