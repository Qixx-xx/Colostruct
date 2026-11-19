# 前端说明（写给只会 Python 的人）

这份文档假设你：会写 Python，知道 `pip install` 和 `python xxx.py` 大概在干什么，
但没碰过前端。读完你应该能**独立把它跑起来**、**知道出问题时该看哪里**、
**大致看懂每个文件在干什么**。

---

## 0. 每次运行，就这三步（忘了只看这里）

```powershell
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\Colostruct v3\frontend\colostruct_v3'
npm install      # 第一次跑才需要；拉别人代码后也要重跑
npm run dev      # 每次都要跑，跑完别关这个窗口
```

> ⚠️ 为什么是 `Set-Location -LiteralPath` 而不是 `cd`？
> 你的路径里有 `[TJU]`，PowerShell 会把方括号当通配符，**加引号也没用**，
> `cd` 会报"路径不存在"（明明存在）。`-LiteralPath` 才能按字面路径处理。
> 详见 [`GIT_GUIDE.md`](./GIT_GUIDE.md) 第 2.1 节。

然后在浏览器打开 **http://localhost:5173**。

停止：在那个窗口按 `Ctrl + C`。

> **`npm install` 什么时候需要重跑？**
> 只在你刚 `git pull` 下来、或者 `package.json` 变了的时候。
> 判断方法：如果目录里没有 `node_modules` 文件夹，就必须装。
> 这个文件夹 70 MB，**不会上传到 GitHub**，所以每次换电脑/重新拉代码都要重装一遍。
> 这是新手最常踩的坑——"我代码拉下来跑不起来"，八成就是忘了 `npm install`。

不想开浏览器也能检查代码有没有被我改坏：

```powershell
npm run selfcheck     # 10 秒，29 项检查，不碰网络
```

---

## 1. 先把新名词翻译成 Python 世界的对应物

前端生态的名词看着吓人，其实大部分你已经在 Python 里见过：

| 前端的东西 | Python 世界里的对应物 | 一句话解释 |
|---|---|---|
| **Node.js** | `python.exe` | 一个"解释器"，只不过它跑的是 JavaScript 不是 Python |
| **JavaScript** | Python | 另一种语言，语法更像 C，但现在你先不用写它 |
| **npm** | `pip` | 装包的工具 |
| **`package.json`** | `requirements.txt` + 启动脚本 | 记录"我依赖哪些包"和"怎么启动" |
| **`package-lock.json`** | `pip freeze` 的输出 | 把版本锁死，保证每台电脑装出来一模一样 |
| **`node_modules/`** | `.venv/Lib/site-packages` | 装下来的包本体。70 MB，不进 git |
| **Vite** | `streamlit run` | 起一个本地服务器，把源码"翻译"给浏览器，并自动刷新 |
| **`.vue` 文件** | 一个 `.py` 文件 | 一个文件里同时装界面、逻辑、样式 |
| **组件（component）** | 一个函数 | 给输入，返回一段界面；可以反复复用 |

**端口（port）** 顺带说一下，因为它到处出现：一台电脑上可以同时跑很多服务，
端口就是它们的"门牌号"。这个项目里：

- `5173` → 前端（你 `npm run dev` 起来的）
- `8000` → 后端 API（B 组负责的部分，现在**还没有**）
- `8501` → 老 Streamlit 版（`streamlit run app.py` 默认端口）

---

## 2. 它和 Streamlit 最大的区别：谁在"重跑"

**这是唯一必须理解的概念，其他都是细节。**

### Streamlit 的做法：每次都重跑整个脚本

你点一下按钮，Streamlit 会把 `app.py` **从头到尾重新执行一遍**，
重新画出整个页面。所以它必须用 `st.session_state` 把数据存起来，
不然一重跑变量就没了。也所以你需要到处写 `st.rerun()`。

### Vue 的做法：状态常驻，只改变了的那一小块

页面一旦画出来就一直活着。你点按钮时，代码只是**改了一个变量**，
Vue 发现"用到这个变量的地方变了"，就只更新那一小块 DOM。

对比一下同一件事：

```python
# Streamlit（旧版 ui/review_panel.py）
if st.button("👉 Confirm and Proceed to Export"):   # 点击 -> 整个脚本重跑
    st.session_state.page = "export"
    st.rerun()                                       # 手动要求重画
```

```javascript
// Vue（新版 components/ReviewPanel.vue）
function tryExport() {
  goto('export')     // 只是把 state.page 改成 'export'
}                    // 没有 rerun，App.vue 里的 v-if 自己就换页了
```

### 三条直接后果

| Streamlit | Vue | 说明 |
|---|---|---|
| `st.session_state.xxx` | `store.js` 里的 `state.xxx` | 数据集中放一个地方 |
| `st.rerun()` | **删掉** | 改了数据自动生效，原项目 11 处 `rerun` 全部消失 |
| `if page == "upload": xxx.render()` | `<UploadPanel v-if="page === 'upload'" />` | `v-if` 就是"条件成立才渲染" |

一句话记住：**Streamlit 是"整页重画"，Vue 是"哪里变了改哪里"。**

另外两条和你 Python 习惯有关的：

- **`ref(0)`** —— 一个"被监视的变量"。普通 `let x = 0` 改了界面不知道；`ref` 改了界面会知道。
- **`computed(...)`** —— 等同于 `@property`：从别的状态算出来，依赖不变就不重算。

---

## 3. 运行原理：一张图看懂谁负责什么

### 3.1 启动的时候发生了什么

```
你在终端敲 npm run dev
        │
        ▼
   Vite 启动，监听 5173 端口
        │
        ▼
浏览器访问 http://localhost:5173
        │
        ▼  index.html   （不到 20 行，是个空壳）
        │   ├── <script src="/config.js">      ← 先加载运行时配置
        │   └── <script src="/src/main.js">    ← 再加载入口
        ▼
   main.js
        │   把 App.vue 挂到 <div id="app"> 上
        ▼
   App.vue 画出标题、导航条，再根据 state.page 决定显示哪个面板
        │
        ├── state.page === 'upload'  →  UploadPanel.vue
        ├── state.page === 'review'  →  ReviewPanel.vue
        └── state.page === 'export'  →  ExportPanel.vue
```

`index.html` 基本是空的，真正的东西都在 `src/` 里。
这一点和 Streamlit 不同：Streamlit 是 Python 直接吐 HTML 给你，
Vue 是浏览器下载 JavaScript，**在用户的浏览器里**把界面搭出来。

### 3.2 点「🚀 Generate Combined Report」时，代码是这样跑的

按顺序，每一步对应一个文件。**这条链走通，你就懂这个前端了。**

| 步骤 | 发生什么 | 在哪个文件 |
|---|---|---|
| 1 | 按钮被点击，执行 `generate()` | `UploadPanel.vue` |
| 2 | 跑 4 步进度条，每步停 0.3 秒 | `UploadPanel.vue` |
| 3 | 勾了 demo？走本地假数据；否则走真实请求 | `dev/mockApi.js` / `api.js` |
| 4 | 把音频文件塞进 `FormData`，`fetch()` 发给后端 | `api.js` |
| 5 | **Vite 把 `/api/process` 转发给 `127.0.0.1:8000`** | `vite.config.js` 的 proxy |
| 6 | 后端返回 JSON：`{diagnosis, macro, micro}` | 后端（B 组） |
| 7 | 检查返回格式对不对，缺 `diagnosis` 就报错 | `api.js` |
| 8 | 把数据塞进全局状态，初始化 15 个输入框的初值 | `store.js` 的 `applyPayload()` |
| 9 | `goto('review')` —— 只是把 `state.page` 改成 `'review'` | `store.js` |
| 10 | `App.vue` 发现 `page` 变了，换掉面板 | `App.vue` |
| 11 | 把 payload 拆成"标签页列表""15 个字段""时间轴片段" | `ReviewPanel.vue` 的 computed |
| 12 | `v-for` 渲染出 15 张字段卡片 | `FieldCard.vue` |

### 3.3 点右栏「▶ seg-002」时

| 步骤 | 发生什么 | 在哪个文件 |
|---|---|---|
| 1 | 执行 `selectEvidence('字段名', 'seg-002')` | `store.js` |
| 2 | 改 `activeSegment` / `highlightField` → 卡片变蓝框、按钮变蓝 | 自动重画 |
| 3 | 同时 `seekRequest.seq += 1` | `store.js` |
| 4 | `AudioTimeline.vue` 监听到 seq 变了 | `AudioTimeline.vue` |
| 5 | `audio.currentTime = 3.0` 然后 `play()` | `AudioTimeline.vue` |

> 步骤 3 为什么要一个计数器而不是直接看 `activeSegment`？
> 因为重复点同一个片段时 `activeSegment` 没变，监听它就不会触发，
> 表现成"第一次能播、第二次点了没反应"。

### 3.4 前端的边界：它不干什么

说清楚边界，你排查问题会快很多：

- **不算 AI、不转写音频、不抽字段。** 这些全在后端（Python）。
- **不存任何文件到磁盘。** 状态都在内存里，**刷新浏览器就全没了**。
  这和 Streamlit 的 `session_state` 一样，也是刷新即丢。
- **不连数据库。** 没有任何数据库驱动。
- 它只做四件事：**收文件、发请求、画界面、生成 Markdown 文本**。

---

## 4. 每个文件负责什么

按"你大概会打开看"的频率排序：

| 文件 | 职责 | 打开频率 |
|---|---|---|
| `src/components/UploadPanel.vue` | 上传页：三个文件选择框、进度条、发请求 | 高 |
| `src/components/ReviewPanel.vue` | 审校页：左栏音频、右栏 15 个字段 | 高 |
| `src/store.js` | **全局状态**：当前页面、选中的片段、改了哪些字段 | 高 |
| `src/labels.js` | 所有界面文案。改文字只改这里 | 高 |
| `src/api.js` | 唯一发网络请求的地方 | 中 |
| `src/components/FieldCard.vue` | 单张字段卡片（最值得读的入门文件） | 中 |
| `src/components/AudioTimeline.vue` | 时间轴 + 播放控制 | 中 |
| `src/components/ExportPanel.vue` | 导出页：预览 + 下载 | 中 |
| `src/export.js` | 生成 Markdown 文本和预览 HTML | 中 |
| `src/transcript.js` | 纯数据整形函数（不依赖 Vue，可单测） | 低 |
| `src/media.js` | 把后端的文件路径转成能播的 URL | 低 |
| `src/config.js` | 接口地址、音频地址前缀 | 低 |
| `src/App.vue` | 根组件：标题 + 导航 + 三个面板互相切换 | 低 |
| `src/main.js` | 入口，不到 10 行，不用管 | 几乎不用 |
| `src/style.css` | 全局样式 | 低 |
| `src/dev/` | 演示假数据。接上后端后整个删掉 | 低 |
| `scripts/selfcheck.mjs` | `npm run selfcheck` 跑的就是它 | 低 |

**建议的阅读顺序**：`FieldCard.vue` → `App.vue` → `store.js` → `UploadPanel.vue`。
`FieldCard.vue` 约 190 行，但 `ref` / `computed` / `v-if` / `v-for` / `v-model` / `@click`
六个概念它全用到了，是性价比最高的入口。

每个文件顶部我写了注释，标明"这段对应老 Streamlit 的哪个文件第几行"，
你可以两边对着看。

---

## 5. 两种运行模式：dev 和 build

这是新手最容易混淆的地方。**同一个前端有两种完全不同的跑法。**

| | `npm run dev` | `npm run build` |
|---|---|---|
| 用途 | 自己开发、改代码、看效果 | 做一份能交给别人用的成品 |
| 产物 | 没有产物，现算现给 | 生成 `dist/` 文件夹（3 个文件，约 100 KB） |
| 速度 | 慢（每次现翻译） | 页面加载快（打包压缩过） |
| 改代码 | 自动刷新 | 改完要重新 build |
| 谁能用 | 只有你这台电脑 | 任何装了浏览器的人 |

### 5.1 为什么需要 Vite 这个中间人

两个原因：

**① 浏览器看不懂 `.vue` 文件。** 里面是 `<template>` / `<script>` / `<style>` 三段，
浏览器只认 HTML/CSS/JS。Vite 负责把 `.vue` 翻译成浏览器能执行的东西。

**② 绕开跨域限制（CORS）。** 浏览器有安全规定：`5173` 页面里的代码
**不允许**直接请求 `8000`。Vite 作为中间人帮你转发：

```
浏览器 →  http://localhost:5173/api/process   （看起来是同源，浏览器放行）
              │
              ▼  Vite 在后台转发
           http://127.0.0.1:8000/api/process   （真正干活的后端）
```

这就是 `vite.config.js` 里 `proxy` 那一段的作用。音频文件也是同理，
`/storage` 也被转发出去了。

### 5.2 `dist/` 是什么

`npm run build` 之后 `dist/` 里是**纯静态文件**：

```
dist/
├── index.html
├── config.js          ← 运行时配置，可以直接用记事本改
└── assets/
    ├── index-xxxx.css
    └── index-xxxx.js
```

这东西不需要 Node、不需要 npm，扔给任何一个 Web 服务器（或者后端）就能用。
按你们"用户本地下载整套东西"的最终设想，**分发出去的就是这个 `dist/`**。

用户如果后端端口不一样，改 `dist/config.js` 里两行就行，**不用重新构建**：

```js
window.__COLOSTRUCT_CONFIG__ = {
  apiUrl: 'http://127.0.0.1:8000/api/process',
  mediaBase: 'http://127.0.0.1:8000',
}
```

> ⚠️ 直接双击打开 `dist/index.html`（`file://` 协议）是**不行**的，
> 必须由一个服务器提供（比如后端 FastAPI 顺便托管）。
> 因为 `file://` 下不能发网络请求，`fetch` 会被浏览器直接拒绝。

---

## 6. 出问题时，看哪里

前端出问题，90% 的答案在**两个地方**，按顺序看：

### ① 终端窗口（`npm run dev` 那个黑框）

编译错误、依赖缺失、端口占用都在这里，是**红字**。
最典型的样子：

```
[vite] Internal server error: ...
error during build:
```
或者
```
Error: Cannot find module 'vue'
```

### ② 浏览器 F12

按 `F12` 打开开发者工具，两个标签页最有用：

- **Console（控制台）**：JavaScript 运行时错误。看**第一条红字**，后面的多半是连带的。
- **Network（网络）**：每条请求的状态。重点看 `/api/process` 那条：
  - `200` = 成功
  - `404` = 地址错了
  - `500` = 后端内部出错（看后端终端）
  - `(failed)` / `ERR_CONNECTION_REFUSED` = **后端根本没启动**

### 常见问题对照表

| 现象 | 最可能的原因 | 怎么办 |
|---|---|---|
| `npm : 无法将"npm"项识别为...` | 没装 Node，或装完没重开终端 | 装 Node LTS，关掉终端重开 |
| `'vite' 不是内部或外部命令` | 没执行 `npm install` | 先 `npm install` |
| `Cannot find module ...` | `node_modules` 不全 | 删掉 `node_modules` 重装 |
| `Port 5173 is in use` | 上次的窗口没关 | Vite 会自动改用 5174，看终端打印的实际地址 |
| 页面全白 | 打开错地址 / 编译失败 | 看终端有没有红字；F12 看 Console |
| 改了代码页面没变 | 热更新卡住 | 刷新页面；还不行就 `Ctrl+C` 重启 |
| 点生成后提示 `Cannot connect to backend` | 后端没启动 | 起后端，或勾 demo 开关绕过后端 |
| 时间轴上方显示 `🔇 Audio unavailable` | 后端没把 `storage` 挂到 `/storage` | 见 `API_CONTRACT.md` 第 3.2 节 |
| 页面出现黄色横幅说上传了却没处理 | 后端没按模块返回结果 | 见 `API_CONTRACT.md` 第 4 节 |

### 一个省事的排查思路

先问自己：**问题出在"界面"还是"数据"？**

- 界面上的字、颜色、位置不对 → 前端（`components/` 里的文件）
- 数据不对、缺模块、播不出声、校验拦截 → 多半是后端，或者前后端的**接口约定**

`API_CONTRACT.md` 就是那份约定，两边吵架时以它为准。

---

## 7. 怎么把前端传到 GitHub

> 完全没用过 git、不知道 clone 是什么？先看 [`GIT_GUIDE.md`](./GIT_GUIDE.md)，
> 那一份从"git 是什么"讲起。本章假设你已经会 clone / add / commit / push。

### 7.1 先理解一件最容易搞错的事

**你本地这个文件夹不是 git 仓库**（没有 `.git`），而且它只是仓库的**部分副本**，还比仓库旧。

对照仓库真实目录可以看出，仓库根目录有这些文件，你本地**一个都没有**：

```
api.py                 ← FastAPI 网关（/api/process、/api/health、音频回放）
docs/  design/  agent_notes/
AGENTS.md  A_GROUP_README.md  requirements-gpu.txt
tests/test_narrative.py
```

所以下面两件事**绝对不能做**：

- ❌ 不要用网页"上传文件夹"把本地整个目录传上去
- ❌ 不要 `git add -A` 然后提交

因为这两种做法都会让 git 认为"这些文件被删除了"，**队友的 api.py、docs/ 会一起没掉**。

正确做法：**clone 一份干净仓库，只把前端拷进去，其余用 git 命令在 clone 里完成。**

### 7.2 三个绝对不能提交的东西

| 东西 | 大小 | 为什么不能传 |
|---|---|---|
| `node_modules/` | **70 MB** | 依赖包本体。别人 `npm install` 会自己装，传上去仓库永久变大 |
| `dist/` | 0.1 MB | 构建产物，随时能重新生成 |
| `.env.local` | — | 本机配置，可能含地址或密钥 |

`frontend/colostruct_v3/.gitignore` 里已经写了这些规则（它会被一起传上去），
但根目录的 `.gitignore` 也要补，防止下次在别的地方又踩。

### 7.3 每个文件往哪里去

| 本地（`Colostruct v3` 下） | 仓库里对应 | 动作 |
|---|---|---|
| `frontend/colostruct_v3/`（排除 `node_modules`、`dist`） | `frontend/colostruct_v3/` | ✅ **复制**（唯一要新增的目录） |
| `legacy_mvp/` | 无 | ⛔ **不要传**，用 `git mv` 在仓库里原地生成 |
| `backend/` | `core/`、`data/`、`eval/`、`tests/` | ⛔ **不要传**，是旧副本，会覆盖队友代码 |
| `.gitignore` | 有同名文件 | ✅ **追加**几行，不要整个覆盖 |
| `README.md` | 有同名文件 | ⚠️ 先 `git diff` 确认，单独一次提交 |
| `demo_payload.json`、`generate_demo_payload.py` | 无 | ⚠️ 可选，见 7.6 |

为什么 `legacy_mvp/` 不用传？因为 `git mv` 移动的是**仓库里的** `app.py` 和 `ui/`，
那才是最新版。你本地 `legacy_mvp/` 里的是旧副本，传上去反而可能比仓库版本差。

### 7.4 完整命令（按顺序执行）

```powershell
# 0) 在父目录 clone 一份干净仓库，生成一个【新文件夹】
#    第二个参数是新文件夹的名字，我随手写成 colostruct-git，你可以换
#    注意用 -LiteralPath，因为路径里有 [TJU]
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT'
git clone https://github.com/Qixx-xx/Colostruct.git colostruct-git
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git'

# 先看清楚仓库里现在到底有什么
git ls-files | Select-Object -First 40
```

```powershell
# 0.5) 确认 api.py 没依赖 app.py / ui/（否则移动会把它弄坏）
Select-String -LiteralPath api.py -Pattern '^\s*(import|from)\s' | Select-Object -First 20
```

如果输出里出现 `import ui` 或 `from app import`，**先停下来问队友**，不要移动。

```powershell
# 1) 打 tag，把"Streamlit 完整版"钉在当前这个提交上
#    必须先打 tag 再移动，否则以后找不回原始结构
git tag v1-streamlit-mvp
git push origin v1-streamlit-mvp
```

```powershell
# 2) 归档旧代码（移动的是仓库里的最新版，不是你本地那份）
git mv app.py legacy_mvp/app.py
git mv ui legacy_mvp/ui
git status --short      # 应该看到两行 R（rename），不应出现 D（delete）
```

```powershell
# 3) 只拷前端，排除 node_modules 和 dist
robocopy 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\Colostruct v3\frontend' 'frontend' /E /XD node_modules dist .vite-temp
# robocopy 返回 1 表示"有文件被复制"，是成功不是报错
```

```powershell
# 4) 补根目录 .gitignore —— 用编辑器打开，把下面这段贴到文件末尾
#    （不要用命令覆盖，队友可能也改过这个文件）
```

```gitignore

# Frontend (Vue 3 + Vite)
node_modules/
frontend/**/dist/
frontend/**/.vite-temp/
*.timestamp-*-*.mjs
.idea/
*.log
```

贴完 `git diff .gitignore` 看一眼：如果 diff 里出现了你不认识的**删除行**，
说明你覆盖掉了队友的改动，撤回来改成只粘贴新增部分。

```powershell
# 5) 提交前自查（最关键的一步，不要跳过）
git add --dry-run frontend | Select-String -Pattern 'node_modules|/dist/|\.idea'
```

**这一行必须没有任何输出。** 有输出就说明忽略规则没生效，回去检查。

```powershell
# 6) 检查有没有误删文件
git status --short
```

**输出里不能出现以 `deleted:` 开头的行。** 出现了就 `git restore <那个文件>` 撤回，
说明你拷东西的方式不对。

```powershell
# 7) 提交并推送
git add frontend .gitignore
git status --short
git commit -m "feat(frontend): migrate UI from Streamlit to Vue 3"
git push
```

`git mv` 的效果已经自动暂存了，所以第 7 步只需要 `add` 前端和 `.gitignore`。

### 7.5 提交前的六项自查

- [ ] `git status` 里看不到 `node_modules`
- [ ] 看不到任何 `deleted:` 开头的行
- [ ] `git ls-files api.py` 有输出（说明 api.py 还在）
- [ ] `git ls-files frontend | Measure-Object -Line` 结果是**三十几个**，不是几千个
- [ ] `git ls-files frontend | Select-String 'config.js'` 能看到 `public/config.js`
- [ ] 移动后旧版仍可运行：`streamlit run legacy_mvp/app.py`

最后一条之所以能成立，是因为 Python 运行脚本时会把**脚本所在目录**放进 `sys.path`，
所以 `legacy_mvp/app.py` 里的 `from ui import ...` 仍然能找到同目录下的 `ui/`。
如果它报 `ModuleNotFoundError: ui`，在 `legacy_mvp/app.py` 开头加两行：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
```

### 7.6 两个可选文件

**`demo_payload.json`**：一份演示数据，给前端"不需要后端也能看界面"用的。
可以传，但要注意它只是快照，会过时。

**`generate_demo_payload.py`**：生成上面那个文件的脚本。**如果要传，请放到 `scripts/` 目录下**，
不要放根目录——脚本里写死了 `PROJECT_ROOT = Path(__file__).resolve().parents[1]`，
它假定自己在 `scripts/` 里。放根目录会算错路径，导致 `from core.pathology_schema import ...` 失败。

另外它是**只读文件**（属性 `-ar---`），要改得先去掉只读属性。

### 7.7 如果搞砸了怎么退回

```powershell
git reset --hard HEAD          # 丢弃所有未提交的改动，回到上次提交
git clean -fd                  # 删掉未跟踪的新文件（谨慎：会删 frontend/ 等新文件）
```

这两条会**永久丢弃**你的改动，只在确认没有价值时用。
更安全的做法是 `git stash` 或者先 `git status` 看清楚再动手。

## 8. 你现在可以先跳过的部分

不用有心理负担。以下这些**不影响你运行、验收、改文案**：

- **响应式原理**：Vue 怎么知道你改了变量（底层用了 JavaScript 的 `Proxy`）。
- **虚拟 DOM 与 diff 算法**：Vue 怎么算出"只改了哪一小块"。
- **打包器内部**：Vite 背后是 esbuild / rolldown，怎么把 30 个文件合成 1 个。
- **`.vue` 编译过程**：`<template>` 怎么变成渲染函数。
- **CSS 布局**：`grid-template-columns`、`flex` 这些。改排版时现查就行。

真想学的话，优先级大概是：
`v-if` / `v-for` / `v-model` / `@click`（1 小时，够看懂 90% 的模板）
→ `ref` / `computed`（1 小时）
→ 组件与 props（1 小时）
→ 剩下的随用随查。

---

## 9. 术语速查卡

| 看到这个 | 就理解成 |
|---|---|
| `ref('upload')` | 一个被监视的变量，初值是 `'upload'` |
| `state.page` | 全局共享的"当前在哪个页面" |
| `computed(() => ...)` | 像 `@property`，从别的状态算出来的 |
| `v-if="x"` | `if x:` 这段才显示 |
| `v-else-if` / `v-else` | 对应的 `elif` / `else` |
| `v-for="f in fields"` | `for f in fields:` 渲染一串 |
| `v-model="state.macroText"` | 输入框和变量双向绑定（改了框就等于改了变量） |
| `@click="fn"` | `on_click=fn` 的 Vue 写法 |
| `:src="url"` | 冒号表示"后面是个 JavaScript 表达式"，不是字符串 |
| `{{ x }}` | 把变量值显示出来，相当于 f-string 的插值 |
| `props` | 传给组件的参数（像函数形参） |
| `emit` | 组件往外发事件（像回调函数） |
| `import ... from './x.js'` | `from x import ...` |
| `export function` | 把它公开出去，让别人能 `import` |
| `async` / `await` | 和 Python 的 `async` / `await` 一个意思 |
| `fetch(url)` | `requests.post(url)` 的浏览器版（但是异步的） |
| `FormData` | 一个专门装"表单 + 文件"的容器，等同于 `requests` 的 `files=` |

---

## 10. 最后：它在整个系统里的位置

```
┌─────────────────────────────────────────────────────────┐
│  用户的浏览器                                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 这个前端（Vue）                                     │  │
│  │ 负责：收文件、画界面、显示结果、生成 Markdown        │  │
│  └───────────────────┬───────────────────────────────┘  │
└──────────────────────┼──────────────────────────────────┘
                       │ HTTP 请求（音频文件上传）
                       ▼
┌─────────────────────────────────────────────────────────┐
│  后端（Python / B 组）                                   │
│  ASR 转写 → LLM 抽 15 个字段 → 校验证据 → 返回 JSON      │
│  顺带把 storage/audio 下的音频文件挂成 /storage 提供下载  │
└─────────────────────────────────────────────────────────┘
```

前端**不产生任何医学结论**，它只是把后端的结果摆出来让人核对和修改。
所以任何"数据不对"的问题，先往右半边看。
