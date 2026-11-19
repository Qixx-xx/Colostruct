# `/api/process` 接口契约

> 给 **B 组（后端）** 的对接说明。
> 前端 `frontend/colostruct_v3` 已按本契约实现完毕，后端只要满足这个契约，前端不需要改一行代码。

---

## 1. 为什么需要这个文件

原 `legacy_mvp/ui/upload_panel.py` 第 108 行已经在调用：

```python
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/process")
response = requests.post(BACKEND_API_URL, files=files, timeout=300)
```

> ⚠️ **重要更正（2026-11）**：本文档早期版本写过"仓库里没有 HTTP 服务"，那是错的。
> 仓库根目录本来就有 **`api.py`**（FastAPI 网关，已挂 `/api/process`、`/api/health` 和音频回放）。
> 那次判断是基于一份不完整的本地副本，副本里缺少 `api.py`。
>
> **所以现在的任务不是"从零写一个网关"，而是"把已有的 `api.py` 和本契约对一遍"。**
> 请按下面顺序核对，只在有差异的地方改：
>
> 1. 请求字段名是不是 `diag_audio` / `macro_audio` / `micro_audio`（第 2 节）
> 2. 返回是不是 `{diagnosis, macro, micro}` 三层信封（第 3 节）
> 3. 三个模块是不是**各自独立**返回，而不是只返回 diagnosis（第 4 节）
> 4. 音频是不是通过 HTTP 可取（`audio_url` 或 `/storage` 挂载，第 3.2 节）
> 5. 单模块失败是不是 `200` + `status: "failed"`（第 5 节）
>
> 另外注意：仓库里的 `core/pathology_schema.py` 已经有 `FullClinicalReport` /
> `NarrativeSection`，`core/export.py` 支持 JSON 导出，而本契约只描述了
> `{diagnosis, macro, micro}` 这层信封。**如果 `api.py` 返回的是 FullClinicalReport，
> 那前端需要适配**——这种情况下请把 `api.py` 的实际返回样例发给前端，以实际返回为准，
> 前端改成本更低的那个方向。

本文档定义前端期望的形状，供核对用。

---

## 2. 请求

```
POST /api/process
Content-Type: multipart/form-data
```

| 表单字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `diag_audio` | File | 三选一及以上 | 诊断录音，提取 15 个结构化字段 |
| `macro_audio` | File | 三选一及以上 | 大体描述录音，转文本 |
| `micro_audio` | File | 三选一及以上 | 镜下描述录音，转文本 |

- 至少一个字段非空，否则请返回 `400`。
- 文件格式：`.mp3` / `.wma` / `.wav`（前端 `accept` 已放开这三种）。
- 字段名**必须**是上面这三个，不能改。这是从 `legacy_mvp/ui/upload_panel.py:112-117` 沿用下来的。
- 每类一次只传一个文件（前端就是只取 `files[0]`，和 legacy 行为一致）。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/process \
  -F "diag_audio=@case1_diag.wav" \
  -F "macro_audio=@case1_macro.wav" \
  -F "micro_audio=@case1_micro.wav"
```

---

## 3. 响应

`200 OK`，`application/json`。**最外层必须是这三个 key**：

```json
{
  "diagnosis": { "status": "success", "data": { ...模块 payload... } },
  "macro":     { "status": "not_uploaded", "data": null },
  "micro":     { "status": "failed", "data": null }
}
```

### 3.1 `status` 的取值（只有三种）

| 值 | 含义 | `data` |
|---|---|---|
| `success` | 该模块处理成功 | 模块 payload 对象 |
| `failed` | 该模块的 AI 服务失败 | `null` |
| `not_uploaded` | 用户没上传这一类的音频 | `null` |

> ⚠️ 前端的强校验：响应里**必须存在 `diagnosis` 这个 key**，否则前端会提示
> `Invalid response format from backend: missing 'diagnosis' field`，并展示原始 JSON。
> 这条校验来自 `legacy_mvp/ui/upload_panel.py:129-133`，请保留。

### 3.2 模块 payload 的结构

`diagnosis.data` / `macro.data` / `micro.data` 共用这一个结构
（参考仓库根目录的 `demo_payload.json`，它就是一份真实样例）：

```json
{
  "audio_url": "http://127.0.0.1:8000/api/audio/abc123.wav",
  "clean_segments": [
    { "segment_id": "seg-001", "start": 0.0, "end": 3.0, "text": "Rectal: anterior recession, ..." }
  ],
  "fields": {
    "tumour_site": {
      "value": "Rectal",
      "evidence": [
        { "segment_id": "seg-001", "quote": "Rectal: anterior recession" }
      ],
      "status": "populated",
      "validation_msg": null
    }
  },
  "override_logs": [],
  "has_block": false
}
```

#### `audio_url`

**浏览器能直接请求到音频的地址。**

> 🔴 现状问题：`backend/core/pipeline.py:214` 返回的是
> `str(stitched_path)`，也就是服务器本地文件路径，两种形态都可能出现：
>
> - `STORAGE_DIR` 未设置 → `D:\...\backend\storage\audio\<case_id>\stitched.wav`
> - `STORAGE_DIR=./storage` → `storage/audio/<case_id>/stitched.wav`
>
> 浏览器把这种字符串当 URL 解析，请求必然 404，`<audio>` 就会「只显示时长、放不出声」。
> 这就是组员反馈的第 4 条问题。

前端已经做了兼容（`frontend/colostruct_v3/src/media.js`）：**只要路径里含 `storage/`，
就截取该段并拼成同源的 `/storage/...`**。所以后端只需要做一件事：

```python
# 把 storage 目录挂到 /storage
app.mount("/storage", StaticFiles(directory=STORAGE_AUDIO_DIR.parent), name="storage")
```

挂载后 `storage/audio/<case_id>/stitched.wav` 就能通过
`GET /storage/audio/<case_id>/stitched.wav` 访问，前端自动拼好，不需要后端改返回值。

另外两种写法前端也支持，后端可以任选：

- 直接返回绝对 URL：`"audio_url": f"{base}/storage/audio/{case_id}/stitched.wav"`
- 返回完整 http 地址：`"audio_url": "http://127.0.0.1:8000/api/audio/xxx.wav"`（原样使用）

没有音频时返回空字符串 `""`，前端会显示「Audio unavailable」提示而不是坏播放器。

#### `clean_segments`

| 字段 | 类型 | 说明 |
|---|---|---|
| `segment_id` | string | 唯一，前端用它做联动主键 |
| `start` | float | 秒，相对整条拼接头 |
| `end` | float | 秒 |
| `text` | string | 该片段的转写文本 |

必须**按 `start` 升序**（前端虽然会再排一次，但别依赖它兜底）。
`segment_id` 要和 `fields[*].evidence[*].segment_id` 对得上，否则点击证据按钮无法定位。

#### `fields`

15 个字段，key 必须是这 15 个（与 `backend/core/pathology_schema.py` 的
`PATHOLOGY_FIELD_KEYS` 一致）：

```
tumour_site
operative_procedure
tumour_dimension
tumour_perforation
relation_to_anterior_peritoneal_reflection
plane_of_mesorectal_excision
histological_tumour_type
histological_tumour_grade
extent_of_invasion
lymphatic_and_venous_invasion
perineural_invasion
lymph_node_status
tumour_deposits
proximal_and_distal_margins
circumferential_margin
```

每个字段对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `value` | string \| null | `null` 表示未提及 |
| `evidence` | array | 每条 `{segment_id, quote}`。可以带 `start`/`end`，前端不用 |
| `status` | string | `populated` / `flagged` / `absent` |
| `validation_msg` | string \| object \| null | **两种形态都支持**，见下 |

**`status` 与前端的显示逻辑**（`legacy_mvp/ui/common.py:182-193`）：

| `status` | 卡片配色 | 徽章 |
|---|---|---|
| `populated` | 绿底 | `Populated` |
| `flagged` | 黄底 + 显示警告文案 | `⚠ Verify` |
| `absent` | 灰底 | `Not Mentioned` |

注意前端判定 `absent` 的条件是 `status === 'absent'` **或** `value === null`，
也就是说 `status` 给了 `populated` 但 `value` 是 `null` 时，前端仍会当作"未提及"。

**`validation_msg` 的两种形态**：

- 字符串（中文）：前端会查 `MSG_MAPPING` 翻成英文，查不到就原样显示。
  目前支持这四条：见 `frontend/colostruct_v3/src/labels.js` 的 `MSG_MAPPING`。
- 对象 `{ "en": "..." }`：直接取 `en`。

新增中文校验信息时，前端会原样显示中文。如果希望统一英文，需要在
`src/labels.js` 的 `MSG_MAPPING` 里加一条。

#### `override_logs`

数组，每条含 `field_name`（前端用它给对应卡片加 `🔄 Overridden` 标记）。
没有就返回 `[]`（不要返回 `null`）。

#### `has_block`

布尔。`true` 表示存在阻断级问题，**前端会禁止导出**并提示校验失败。
判定口径来自 `legacy_mvp/ui/review_panel.py:106-109`。

---

## 4. 每个模块必须独立返回（组员反馈的第 3 条问题）

`backend/core/pipeline.py:179` 的 `process_case(audio_file_paths)` 一次只处理
**一组**音频，返回**一个**模块 payload。所以 HTTP 层不能只调用一次就返回，
必须按用户实际上传的模块分别调用：

```python
diag  = _run(paths.get("diag"))   # 用户没传 -> {"status": "not_uploaded", "data": null}
macro = _run(paths.get("macro"))
micro = _run(paths.get("micro"))
```

**最容易踩的坑**：图省事把 macro/micro 写死成 `not_uploaded`。

后果就是组员反馈的第 3 条——「上传了 diagnosis 后 macro 和 micro 的预览消失」：
用户明明传了三段音频，返回里只有 diagnosis 是 success，于是

- 左栏 `🎧` 标签页只剩 Diagnosis，macro/micro 的时间轴整块不见；
- 右栏 Macro/Micro 只剩一句 `[Not Uploaded]`。

前端已经加了一个横幅把这种矛盾直接说出来（"You uploaded audio for Macro, Micro,
but the backend returned status not_uploaded..."）。**看到这个横幅就是后端没按模块返回。**

## 5. 错误处理

| 情况 | 后端返回 | 前端表现 |
|---|---|---|
| 一个文件都没传 | `400` + 说明文本 | 显示 `Server error: 400 - <body>` |
| 音频解析失败 | `500` + 说明文本 | 同上 |
| 某个模块 AI 服务挂了 | **`200`** + 该模块 `status: "failed"` | 该模块显示错误，其他模块正常 |
| 服务没起来 | — | `❌ Cannot connect to backend service (...)` |
| 超过 300 秒 | — | 前端中止并提示连接失败 |

注意第 3 行：**单模块失败不要用 HTTP 错误码表达**，要用 `status: "failed"`。
这是"部分失败仍可审校其余模块"的设计前提。

---

## 6. 跨域（CORS）

开发阶段**不需要**后端配 CORS。`vite.config.js` 已配置代理：

```
前端请求  /api/process  →  Vite 转发  →  http://127.0.0.1:8000/api/process
```

浏览器看到的是同源请求，不会触发跨域检查。

只有在以下情况才需要后端加 CORS 中间件（或 Nginx 同源部署）：

- 前端改动 `VITE_API_URL` 指向别的机器；
- `npm run build` 后的静态文件由另一个端口/域名托管。

---

## 7. 前端怎么切换接口地址

在 `frontend/colostruct_v3/` 下新建 `.env.local`：

```ini
# 默认走 vite proxy，指向本机 8000
# VITE_API_URL=

# 指到别的机器（此时需要后端开 CORS）
VITE_API_URL=http://192.168.1.10:8000/api/process
```

`.env.local` 已在 `.gitignore` 里，不会被提交。参考 `.env.example`。

---

## 8. 最小可行实现参考

```python
# backend/api.py —— 新增，不需要改 core/ 里的任何东西
import shutil, tempfile, uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles

from core.pipeline import process_case
from core import STORAGE_AUDIO_DIR   # 或自己定义

app = FastAPI()

@app.post("/api/process")
async def process(
    diag_audio: UploadFile | None = File(None),
    macro_audio: UploadFile | None = File(None),
    micro_audio: UploadFile | None = File(None),
):
    uploads = {"diag": diag_audio, "macro": macro_audio, "micro": micro_audio}
    tmpdir = Path(tempfile.mkdtemp())
    paths = {}
    for kind, up in uploads.items():
        if up is None:
            continue
        dest = tmpdir / up.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        paths[kind] = str(dest)

    if not paths:
        raise HTTPException(status_code=400, detail="at least one audio file required")

    try:
        # 注意 process_case 一次只处理一组音频；三路需要分别调用并各自包成模块 payload
        diag     = _run(paths.get("diag"))
        macro    = _run(paths.get("macro"))
        micro    = _run(paths.get("micro"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"diagnosis": diag, "macro": macro, "micro": micro}
```

`_run(path)` 负责把 `process_case` 的输出包成 `{"status": ..., "data": ...}`，
并在失败时返回 `{"status": "failed", "data": null}` 而不是抛异常。

---

## 9. 自检清单

- [ ] 只传 `diag_audio` 时，响应里 `macro`/`micro` 的 `status` 是 `not_uploaded`
- [ ] **三段音频都上传时，三个模块都必须是 `success`**（不能有 `not_uploaded`，否则就是第 4 节的坑）
- [ ] 响应最外层有 `diagnosis` key
- [ ] 15 个字段 key 与 `pathology_schema.PATHOLOGY_FIELD_KEYS` 完全一致
- [ ] `clean_segments` 的 `segment_id` 与 `evidence.segment_id` 能对上
- [ ] `GET /storage/audio/<case_id>/stitched.wav` 在浏览器里能直接播放
- [ ] 单模块 AI 失败返回 `200` + `status: "failed"`，不是 `500`
