# Streamlit → Vue 迁移说明

> 这份文档回答两个问题：**怎么跑起来**，以及**你原来那段 Streamlit 代码现在在哪一行**。
> 验收时对照着看，不需要先学 Vue。

---

## 1. 怎么跑起来

```bash
cd frontend/colostruct_v3
npm install          # 已经装过就跳过
npm run dev          # 打开 http://localhost:5173
```

打开后想直接看完整界面（后端还没就绪）：

1. 在上传页勾选 **`⚙️ (Dev) Use bundled demo data — no backend needed`**
2. 随便选一个音频文件（演示模式下文件内容不会被读取，只为让按钮亮起来）
3. 点 **🚀 Generate Combined Report**

会跑完 4 步进度，然后带着一份真实病例数据（8 个转写片段 + 15 个字段，含 3 个植入的幻觉字段）进入审校页。

另外两个命令：

```bash
npm run build        # 生产构建，产物在 dist/
npm run selfcheck    # 迁移一致性自检（22 项，不需要浏览器）
```

`npm run selfcheck` 是这次迁移特意加的：它逐字符比对导出的 Markdown、验证 segment 索引、
校验 HTML 转义。**改完代码跑一下它，比肉眼看界面可靠。**

---

## 2. 文件对应关系

| 原来的文件 | 现在的文件 | 说明 |
|---|---|---|
| `legacy_mvp/app.py` (24 行) | `src/App.vue` + `src/store.js` | 路由分发 → `v-if`；`session_state` → `reactive` |
| `legacy_mvp/ui/common.py` 第 9-72 行 | `src/labels.js` | 文案字典，一个字没改 |
| `common.py` 第 76-91 行 | `src/transcript.js` | `hydrate_evidence` / `build_segment_index` |
| `common.py` 第 95-108 行 | `src/store.js` | 三个联动回调 |
| `common.py` 第 112-122 行 | `src/App.vue` | `render_header()` |
| `common.py` 第 125-173 行 | `src/components/AudioTimeline.vue` | 时间轴，**从 iframe 改成组件** |
| `common.py` 第 177-250 行 | `src/components/FieldCard.vue` | 字段卡片 |
| `legacy_mvp/ui/upload_panel.py` | `src/components/UploadPanel.vue` + `src/api.js` | 上传页 + 网络层 |
| `legacy_mvp/ui/review_panel.py` | `src/components/ReviewPanel.vue` | 审校页 |
| `legacy_mvp/ui/export_panel.py` 第 17-52 行 | `src/export.js` `buildMarkdown` | Markdown 生成 |
| `legacy_mvp/ui/export_panel.py` 第 83-116 行 | `src/export.js` `buildPreviewHtml` | 预览 HTML |

每个文件顶部都有注释，写明"对应 legacy 的哪个文件第几行"。

---

## 3. 你需要理解的只有一张表

| Streamlit | Vue 3 | 在哪 |
|---|---|---|
| `st.session_state.page` | `const page = ref('upload')` | `store.js` |
| `st.rerun()` | **删掉**，改数据界面自动更新 | 原项目 11 处全部消失 |
| `if page=="upload": upload_panel.render()` | `<UploadPanel v-if="state.page === 'upload'" />` | `App.vue` |
| `st.columns([4.5, 5.5])` | CSS `grid-template-columns: 4.5fr 5.5fr` | `ReviewPanel.vue` |
| `st.file_uploader()` | `<input type="file" @change>` | `UploadPanel.vue` |
| `st.text_area(key="input_x")` | `<textarea v-model="state.editedFields.x">` | `FieldCard.vue` |
| `st.checkbox()` | `<input type="checkbox" v-model>` | `ReviewPanel.vue` |
| `st.tabs([...])` | `activeTab = ref(0)` + `v-if` | `ReviewPanel.vue` |
| `components.html(TIMELINE_TEMPLATE)` | 组件 + `:style="{ left: pct + '%' }"` | `AudioTimeline.vue` |
| `requests.post(url, files=...)` | `fetch(url, { body: FormData })` | `api.js` |
| `st.download_button(data=md)` | `Blob` + `a.download` | `export.js` |
| `st.button(on_click=f)` | `<button @click="f">` | 各组件 |

要学的新概念只有 6 个：`ref` / `reactive`、`v-if`、`v-for`、`v-model`、`@click`、`computed`。
`src/components/FieldCard.vue` 是最值得读的一个文件 —— 它同时用到了这 6 个，而且只有 130 行。

---

## 4. 和 legacy 不一样的地方（有意为之）

1. **文件类型选择器多了 `.wav`**。原版是 `type=["mp3","wma"]`；后端 pydub 本来就吃 wav，
   demo 音频也是 wav，所以放开了。如果必须和原版完全一致，改 `UploadPanel.vue` 的 `ACCEPT` 常量。

2. **没有音频地址时不渲染 `<audio>`**。原版即使 `audio_url` 为空也照渲染，
   结果是个坏掉的播放器。

3. **提示框是页面内彩色块**，不再是 Streamlit 的浮层 toast。
   对应关系：`st.success` → 绿块、`st.error` → 红块、`st.info` → 蓝块、`st.warning` → 黄块。

4. **进度条在生成完成后消失**。Streamlit 的 `st.progress` 会一直留在页面上。

5. **切换页面后文件选择不丢**。文件存在 `store.js` 的 `fileSelection` 里，
   等价于 Streamlit 把 widget 状态存在 `session_state`。换成组件本地状态会丢。

6. **少了一次整页报错**。原版 `upload_panel.py:129-133` 用 `st.stop()` 中断整个脚本，
   Vue 里没有"中断渲染"这回事，改成在页面内显示错误 + 原始 JSON。

7. **新增了一个 Dev 开关** `Use bundled demo data`，原版没有。
   它是为了在后端就绪前验收界面。接口连通后连同 `src/dev/` 整个目录一起删掉。

8. **时间轴不再是 iframe**。原版用 `components.html` 塞一个 190px 的 iframe，
   还要把 `json.dumps` 里的 `</` 转义掉防止 Script 闭合。现在是普通组件，
   点击行为与原版一致（只做 `currentTime` 跳转 + `play()`，不改选中状态）：
   **选中靠下面的 segment 按钮，两件事在原来就是分开的。**

---

## 5. 原样保留的遗留行为

这些看起来像 bug，但为了"迁移"而不是"改需求"，都照搬了：

1. **允许一次选多个文件，但每类只发第一个**（`upload_panel.py:112-117` 就是 `[0]`）。
   界面会显示全部文件名，实际只上传第一个。要改就改 `UploadPanel.vue` 的 `generate()`。

2. **清空字段输入框后，导出会回退到后端原值**。
   `export_panel.py:18-20` 的条件是 `if edited is not None and str(edited).strip()`，
   空串判为假，于是走 `fd.value`。也就是说医生想手动清空一个字段是做不到的。
   `selfcheck.mjs` 里专门有一条测试锁定了这个行为。如果这是缺陷，改 `export.js` 的
   `getFieldValue` 即可（把回退逻辑去掉），同时删掉那条测试。

---

## 6. 已知问题（需要别人处理）

1. **`audio_url` 是服务器本地文件路径，浏览器播不了。**
   `backend/core/pipeline.py:244` 返回 `str(stitched_path)`，形如
   `D:\...\storage\audio\<id>\stitched.wav`。前端 `<audio>` 会 404。
   已写进 `API_CONTRACT.md` 第 3.2 节，需要 B 组改成 HTTP URL。

2. **demo 音频文件不在仓库里。** `demo_payload.json` 里写的
   `storage/audio/demo_rectal_case.wav` 位于被 `.gitignore` 忽略的 `storage/` 下，
   所以演示时播放器是空的（时间轴的方块、联动、字段显示都正常）。

3. **`generate_demo_payload.py` 是只读文件，我没能改。**
   它的 `print(json.dumps(...))` 在中文 Windows 上重定向会产出 **GBK** 文件
   （原来的 `demo_payload.json` 就是 GBK，已经转成 UTF-8 了）。
   要根治，请先去掉文件的只读属性，然后在 `main()` 开头加：

   ```python
   try:
       sys.stdout.reconfigure(encoding="utf-8")
   except (AttributeError, OSError):
       pass
   ```

4. **`node_modules` 的写入被当前沙箱挡住**，我这边只能靠 `npm run build` 验证编译，
   跑不起 dev server。你在自己的终端里跑 `npm run dev` 不受影响。

---

## 7. 验收清单

跑 `npm run dev`，勾上 demo 数据，按顺序核对：

- [ ] 上传页两张卡片并排（Diagnosis / Pathological Section），窄屏时自动堆叠
- [ ] 没选文件时按钮不出现，只有 "Please upload at least one file..." 提示
- [ ] 选了文件后按钮出现，点击走完 4 步进度
- [ ] 审校页左栏有 `🎧 Diagnosis` 标签页，时间轴上有 8 个方块
- [ ] 点某个方块 → 音频跳转（没音频文件时无反应，正常）
- [ ] 点下方 `⏱ seg-00X` 按钮 → 按钮变蓝、时间轴上对应方块变橙、右栏对应卡片出现 📍 和蓝框
- [ ] 右栏 15 张卡片：3 张绿（Populated）、3 张黄（⚠ Verify 且显示英文警告）、9 张灰（Not Mentioned）
- [ ] 黄卡片的警告是中文字符串但显示成英文（`MSG_MAPPING` 生效）
- [ ] 点卡片下方的 `▶ seg-00X` 证据按钮 → 左右同时联动
- [ ] 点 `Clear highlight` → 高亮全部清除
- [ ] 勾选确认框前点导出 → 提示 `⛔ Please check the confirmation box first.`
- [ ] 勾选后进入导出页 → 左侧两个绿勾、右侧带 AI 水印的文档预览
- [ ] 点 `⬇️ Export Markdown` → 下载 `clinical_report.md`
- [ ] 打开下载的 md，15 个字段标签齐全，未提及的显示 `[Not Mentioned]`
- [ ] `🔙 Return to Upload` 回到上传页，之前选的文件还在
- [ ] 回到上传页再勾 `(Dev) Simulate AI Service Failure` 生成 → 审校页显示红色错误、导出被拦截

---

## 9. 组员反馈的 4 个问题：Vue 版的核对结果

| # | 反馈 | Vue 版原来是否有 | 处理 |
|---|---|---|---|
| 2 | 右栏字段下方 `seg-xxx` 红色按钮点了不跳转播放 | **有**（照搬了 legacy 行为） | 已修 |
| 3 | 上传 diagnosis 后 macro/micro 的预览消失 | **没有**（渲染逻辑无条件） | 已加矛盾提示 |
| 4 | macro/micro 音频播不了，只识别到长度 | **有**（同一个 audio_url 问题） | 已修 |
| — | 旧版还在用 mock / 接口是本机地址 | 保留且强化 | 见第 10 节 |

### 第 2 条：证据按钮不跳转播放 —— 已修

根因：`legacy_mvp/ui/common.py:95-108` 的 `_select_evidence` / `_select_segment`
**只改高亮状态，从来不碰音频元素**。点时间轴方块才会 seek（`common.py:154`），
点证据按钮只变色。这是原版的设计遗漏，我迁移时原样保留了，所以问题一起过来了。

修法：`store.js` 新增 `seekRequest = { sid, seq }`，`selectSegment` / `selectEvidence`
都会递增 `seq`；`AudioTimeline.vue` 监听 `seq` 变化，跳到对应片段并 `play()`。

为什么用递增计数而不是直接监听 `activeSegment`：重复点同一个片段时
`activeSegment` 没变，watch 不触发，用户会觉得"第一次能播第二次不能"。

### 第 3 条：macro/micro 预览消失 —— 前端无此 bug，但已加提示

排查结论：前端三个上传框、两个文本框都是**无条件渲染**的，不存在"上传 A 导致 B 消失"。
真正的原因是后端只返回了 diagnosis 一个模块：

`backend/core/pipeline.py:179` 的 `process_case()` 一次只处理一组音频、返回一个模块 payload，
而 HTTP 层（目前还不存在）如果只调用一次、把 macro/micro 写死成 `not_uploaded`，
界面就会表现为：左栏只剩 `🎧 Diagnosis` 一个标签页，右栏 Macro/Micro 只剩 `[Not Uploaded]`。

修法：`ReviewPanel.vue` 增加一个横幅，检测"用户传了文件但后端说没传"的矛盾并直接显示。
看到这个横幅就说明是后端没按模块返回，不是界面坏了。
详见 `API_CONTRACT.md` 第 4 节。

### 第 4 条：音频只有长度放不出声 —— 已修

根因：`backend/core/pipeline.py:214` 的 `audio_url = str(stitched_path)` 是文件系统路径，
浏览器当 URL 请求必然 404，`<audio>` 就只剩时长条。

修法：新增 `src/media.js` 的 `resolveAudioUrl()`，把路径里 `storage/` 之后的部分截出来，
拼成同源 `/storage/...`；`vite.config.js` 加了 `/storage` 代理转发到后端 8000。
后端只需 `app.mount("/storage", StaticFiles(...))`，返回值一个字都不用改。

无法识别的绝对路径会返回空串并 `console.warn`，此时界面显示
`🔇 Audio unavailable for this track`，而不是塞一个注定 404 的地址进去。

---

## 10. 全本地部署（无云端）

最终形态是"用户在个人电脑上下载整套东西（含本地大模型）直接跑"。对应的配置策略：

### 10.1 三层优先级，默认全部指向本机

`src/config.js`：

| 优先级 | 来源 | 何时改 |
|---|---|---|
| 1 | `window.__COLOSTRUCT_CONFIG__`（`dist/config.js`） | **运行时**，改完刷新即生效 |
| 2 | `import.meta.env.VITE_*` | 构建时，开发 / CI 用 |
| 3 | 内置默认值 | 同源 `/api/process`、`/storage` |

关键点：`VITE_` 变量是**构建时写死进 bundle** 的，改一次要重新 `npm run build`——
对最终用户不现实。所以额外提供了 `public/config.js`，构建时原样复制到 `dist/config.js`，
用户直接编辑那个文件即可切换后端地址，**不需要装 Node、不需要重新构建**。

```js
// dist/config.js
window.__COLOSTRUCT_CONFIG__ = {
  apiUrl: 'http://127.0.0.1:8000/api/process',
  mediaBase: 'http://127.0.0.1:8000',
}
```

### 10.2 和 Streamlit 版配置的对应关系

| Streamlit 版（保留，未改动） | Vue 版 |
|---|---|
| `upload_panel.py:108` `os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/process")` | `config.js` 的 `apiUrl`，默认值相同 |
| `backend/.env.example` 的 `BACKEND_API_URL` 一行 | 保留原样，Streamlit 仍在用 |
| `STORAGE_DIR` / `DATABASE_PATH` | 未改动，仍由后端读取 |
| `COLOSTRUCT_OLLAMA_URL` = `http://127.0.0.1:11434` | 未改动，本地 Ollama |

**`legacy_mvp/`、`backend/.env.example`、`Dockerfile`、`requirements.txt` 我一个字节都没动**，
Streamlit 版仍然可以按原样启动。

### 10.3 关于 mock

Vue 版**没有**内置 mock 后端。唯一的演示数据在 `src/dev/`，由上传页那个
`⚙️ (Dev) Use bundled demo data` 开关显式启用，默认关闭。
不勾它就一定走真实 HTTP 请求——不存在"忘了关 mock 导致假数据"的风险。

## 11. 接后端时要做什么

B 组的 `/api/process` 就绪后：

1. 不勾 demo 开关，直接点生成。默认请求 `/api/process`，由 `vite.config.js` 代理到 `127.0.0.1:8000`。
2. 后端不在本机：改 `dist/config.js` 里的 `apiUrl`（推荐，不用重新构建）；
   或建 `.env.local` 写 `VITE_API_URL=...`（要重新 `npm run build`，且后端要开 CORS）。
3. 后端要补两件事，否则界面会缺东西：
   - 按模块分别返回 `diagnosis` / `macro` / `micro`（否则见第 9 节第 3 条）
   - `app.mount("/storage", StaticFiles(...))`（否则音频播不了，见第 9 节第 4 条）
4. 联调通过后清理演示代码：
   - 删 `src/dev/` 整个目录
   - 删 `UploadPanel.vue` 里 `useDemoData` 相关的 `<label>`、`ref` 和 `if` 分支

契约细节见 `API_CONTRACT.md`。
