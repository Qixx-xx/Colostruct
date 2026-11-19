<template>
  <div class="app-container">
    <!--
      对应 common.py:112-122 的 render_header()
      原版每个面板都调一次 render_header，Vue 里放在根组件即可，
      因为页面切换时根组件不会重建。
    -->
    <h1 class="app-title">{{ L.title }}</h1>

    <!--
      common.py:116-121 —— "🔵 **Upload** ➔ ⚪ Review ➔ ⚪ Export"
      原版是拼一段 markdown 字符串，这里用 v-for 生成同样的结构。
      导航条只用来显示进度，不能点击，和原版一致。
    -->
    <nav class="nav-bar">
      <template v-for="(p, i) in PAGES" :key="p.key">
        <span class="nav-item" :class="{ active: state.page === p.key }">
          {{ state.page === p.key ? '🔵' : '⚪' }}
          <b v-if="state.page === p.key">{{ p.label }}</b>
          <span v-else>{{ p.label }}</span>
        </span>
        <span v-if="i < PAGES.length - 1" class="nav-arrow">➔</span>
      </template>
    </nav>

    <hr class="divider" />

    <!--
      对应 app.py:19-24 的路由分发。
      Streamlit 是 "if page == ...: upload_panel.render()"，
      Vue 是 "<UploadPanel v-if=... />" —— v-if 就是"这个条件成立才渲染"。
    -->
    <UploadPanel v-if="state.page === 'upload'" />
    <ReviewPanel v-else-if="state.page === 'review'" />
    <ExportPanel v-else-if="state.page === 'export'" />
  </div>
</template>

<script setup>
// 对比一下：原 app.py 有 24 行，其中 13 行是 session_state 初始化和路由。
// 那些状态现在全部搬进了 store.js，App.vue 只剩下"长什么样"。
import { L } from './labels.js'
import { state } from './store.js'
import UploadPanel from './components/UploadPanel.vue'
import ReviewPanel from './components/ReviewPanel.vue'
import ExportPanel from './components/ExportPanel.vue'

const PAGES = [
  { key: 'upload', label: L.nav_upload },
  { key: 'review', label: L.nav_review },
  { key: 'export', label: L.nav_export },
]
</script>

<style scoped>
.app-container {
  max-width: 1180px;
  margin: 0 auto;
}

.app-title {
  font-size: 2rem;
  margin: 0 0 10px;
  font-weight: 700;
  color: #263238;
}

.nav-bar {
  font-size: 1.05rem;
  font-weight: bold;
  color: #9e9e9e;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.nav-item.active {
  color: #1e88e5;
}

.nav-arrow {
  color: #b0bec5;
}
</style>
