# colostruct_v3 — 前端

ColoStruct 临床音频校对工作台的 Vue 3 前端，从 `legacy_mvp/`（Streamlit）迁移而来。

## 快速开始

```bash
npm install
npm run dev          # http://localhost:5173
```

**后端还没就绪也能看完整界面**：上传页勾选
`⚙️ (Dev) Use bundled demo data — no backend needed`，随便选一个音频文件，点生成。

## 常用命令

| 命令 | 作用 |
|---|---|
| `npm run dev` | 开发服务器，热更新 |
| `npm run build` | 生产构建 → `dist/` |
| `npm run preview` | 本地预览构建产物 |
| `npm run selfcheck` | **迁移一致性自检**（29 项，无需浏览器） |

改完涉及数据/导出的代码，请跑 `npm run selfcheck`。它逐字符比对导出的 Markdown、
验证 segment 索引、HTML 转义和音频地址解析 —— 比肉眼点界面可靠得多。

## 文档

全部在 [`introduction/`](./introduction/) 目录下：

| 文件 | 内容 |
|---|---|
| [`FRONTEND_PRIMER.md`](./introduction/FRONTEND_PRIMER.md) | **前端入门说明**：怎么运行、原理、每个文件干什么、**怎么上传 GitHub**。只会 Python 也能看懂 |
| [`GIT_GUIDE.md`](./introduction/GIT_GUIDE.md) | **Git 纯新手说明**：clone / add / commit / push / 冲突 / 出事怎么救 |
| [`MIGRATION_NOTES.md`](./introduction/MIGRATION_NOTES.md) | 迁移说明：文件对应关系、概念对照表、与 legacy 的差异、验收清单 |
| [`API_CONTRACT.md`](./introduction/API_CONTRACT.md) | `/api/process` 接口契约，**给后端（B 组）看** |
| [`TALK_5MIN.md`](./introduction/TALK_5MIN.md) | 五分钟讲稿，用于汇报和组内联调 |

## 目录结构

```
src/
├── App.vue                  # 根组件：标题 + 导航 + 页面切换
├── main.js                  # 入口
├── style.css                # 全局样式 + 导出预览的文档样式
├── config.js                # 运行时配置（接口地址、音频地址前缀）
├── labels.js                # 全部界面文案（对应 common.py 的 L / FIELD_LABELS / MSG_MAPPING）
├── store.js                 # 全局状态（替代 st.session_state）
├── transcript.js            # 纯数据函数：hydrate / segment 索引 / 模块状态判定
├── media.js                 # 把后端的文件路径转成可播放 URL
├── export.js                # Markdown 生成、预览 HTML、下载
├── api.js                   # 唯一的网络出口
├── components/
│   ├── UploadPanel.vue      # 上传页
│   ├── ReviewPanel.vue      # 审校页（双栏）
│   ├── ExportPanel.vue      # 导出页
│   ├── AudioTimeline.vue    # 时间轴（替代原来的 iframe）
│   └── FieldCard.vue        # 单张字段卡片
└── dev/                     # 演示数据，后端联调通过后整个删掉
    ├── demoPayload.json     # 由根目录 demo_payload.json 复制而来
    └── mockApi.js
```

## 接口地址（两种改法）

**改运行时配置（推荐，不用重新构建）** —— 编辑 `dist/config.js`：

```js
window.__COLOSTRUCT_CONFIG__ = {
  apiUrl: 'http://127.0.0.1:8000/api/process',
  mediaBase: 'http://127.0.0.1:8000',
}
```

**改构建时变量** —— 在 `frontend/colostruct_v3/` 下建 `.env.local`：

```ini
VITE_API_URL=http://192.168.1.10:8000/api/process
```

默认值全部指向本机（同源 `/api/process`、`/storage`），
开发时由 `vite.config.js` 的 proxy 转发到 `127.0.0.1:8000`，绕开 CORS。
注意指向别的机器时需要后端自己开启 CORS。详见 [`API_CONTRACT.md`](./API_CONTRACT.md) 第 6 节。

## 技术栈

Vue 3（`<script setup>` 语法）+ Vite。运行时依赖只有 `vue` 一个，
没上路由库和状态管理库 —— 三个页面的切换用一个 `ref` 就够，
全局状态用 `reactive` 就够，引入 Pinia / Vue Router 反而是负担。
