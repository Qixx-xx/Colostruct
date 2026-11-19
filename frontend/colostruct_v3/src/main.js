import { createApp } from 'vue'
import App from './App.vue'

// 全局样式（页面基础排版 + 导出预览的文档样式）
// 对应 Streamlit 自动提供的那部分基础样式
import './style.css'

createApp(App).mount('#app')
