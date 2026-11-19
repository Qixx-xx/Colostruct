# ColoStruct 项目交接说明书（HANDOFF）

> **生成时间**：2026-11-19 16:55（Asia/Shanghai）
> **仓库**：https://github.com/Qixx-xx/Colostruct
> **适用对象**：接续本项目的 AI agent / 新接手开发者
> **阅读顺序建议**：0 → 1 → 2 → 3 → 4 → 5 → 9 → 10 → 11。只想快速接手看 0、2、9、10。

---

## 0. 30 秒速览

ColoStruct 是一个**本地优先的结直肠癌病理报告草稿生成系统**：上传诊断 / 大体（MACRO）/ 镜下（MICRO）音频，本地 Whisper 转写，LLM 抽取 15 个结构化字段并生成两段叙事文本，后端做证据审计，Streamlit 人工校审后导出 Markdown / JSON。

**当前真实状态（重要）：**

| 项目 | 状态 |
|---|---|
| 远端 `main` | `35a7e5f`（PR #7 已合并：依赖与环境模板修复） |
| 远端是否有 open PR | **没有** |
| `main` 的 pipeline | **只有 mock**（`process_case`），没有真实 ASR/LLM 链路 |
| 真实完整系统在哪里 | 只在**本机目录 `repo-cuda`**（无 `.git`，是拷贝） |
| 真实链路是否入库 | **否**：`api.py`、`core/asr_hf_whisper.py`、`process_case_real` 均未提交 |
| 本次新增叙事功能 | 已在 `repository/Colostruct` 实现，**未提交**；已同步到 `repo-cuda` |
| GPU 是否可用 | **是**，RTX 5070 Ti Laptop，CUDA 12.8，GPU 推理已验证 |
| 当前运行中的服务 | 仅 Streamlit（8501，来自 `repo-cuda`）；API 8000 未启动 |

**最关键的下一步**：先把“真实链路 + 叙事功能”提交成 PR，否则项目只存在于这台电脑的两个拷贝里，无法复现、无法协作。

> 如果接收方**只能访问 GitHub**：当前 clone 下来只有 mock + 未提交的叙事功能（叙事功能也不在远端）。必须先让 B 组推送任务 A/B 的 PR，或者把 `repo-cuda` 打包（排除模型、音频、`.env`、`storage/`）发给对方，否则无法复现真实链路。

---

## 1. 产品目标与不可违反的约束

### 1.1 Pipeline

```
有序多段音频上传
  → pydub 拼接（16 kHz mono，段间 0.5 s 静音，记录全局偏移）
  → Whisper ASR（全局时间戳）
  → 规则去噪 cleanup（只去语气词/重复/空片段，不改临床含义）
  → Pass A（口误纠正 + 时序覆盖，保留 override log）
  → Pass B（抽取 15 个字段）
  → Schema 校验 + 证据审计 validate
  → 双栏人工校审
  → Markdown / JSON 导出（带 AI 水印）
```

### 1.2 必填 15 字段（顺序固定，不可随意重排）

`tumour_site`, `operative_procedure`, `tumour_dimension`, `tumour_perforation`, `relation_to_anterior_peritoneal_reflection`, `plane_of_mesorectal_excision`, `histological_tumour_type`, `histological_tumour_grade`, `extent_of_invasion`, `lymphatic_and_venous_invasion`, `perineural_invasion`, `lymph_node_status`, `tumour_deposits`, `proximal_and_distal_margins`, `circumferential_margin`

### 1.3 硬约束（摘自 `AGENTS.md`，违反即返工）

- 无证据字段必须精确为 `[not mentioned]`，**绝不编造临床事实**。
- 规则清洗只能去噪，不得改写、总结、重排、推断临床含义。
- 每个有值字段必须有 transcript evidence + 时间戳；审计只标记、不改写。
- 阻塞级失败必须可见并阻止导出。
- 导出水印按 `AGENTS.md` 原文应为：`AI-assisted draft — not for clinical use without review`。
  - ⚠️ 当前 `core/export.py` 用的是中文版本，**与 AGENTS 不一致，属于已知待确认问题**。
- 不写医院 EHR/eHR；不公网部署；不把临床数据发到未批准云端；优先合成/去标识数据；不提交音频、模型、`.env`、`storage/`。

---

## 2. 代码 / 分支 / PR 现状

### 2.1 远端分支（2026-11-19 实测）

| 分支 | commit | 日期 | 是否含真实链路 |
|---|---|---|---|
| `main` | `35a7e5f` | 2026-11-17 | 否（mock pipeline；有 PR #7 的依赖/模板更新） |
| `feat/a-asr-llm-integration` | `3726a5c` | 2026-11-11 | 只有 `core/asr_hf_whisper.py`；无 `api.py`、无 `process_case_real` |
| `feat/b-pipeline-integration` | `7758fa7` | 2026-11-03 | 否（旧 B 组 UI/集成） |
| `chore/fix-deps-and-env-example-for-cross-machine-repro` | `d89f79b` | 2026-11-17 | 仅依赖/模板（已合并进 main） |
| `chore/reorganize-repo` / `docs/sync-prd-v0.3` / `feat/a-ai-modules` / `feature-frontrnd-app` / `forntend` | 旧 | 2026-10/11 | 历史分支 |

- **open PR：无**。
- PR #7：`chore(deps, env): 补齐运行依赖并完善 .env.example（跨机复现）`，已 merge。
- 最新 `main` 只有 mock：`core/pipeline.py` 仅 `process_case`，无 `process_case_real`。

### 2.2 本地未提交改动（在 `repository/Colostruct`）

```text
 M .env.example             (+5  行：COLOSTRUCT_NARRATIVE_MOCK 说明)
 M core/cleanup.py          (+69 行：clean_narrative_output)
 M core/pathology_schema.py (+57 行：NarrativeSection / FullClinicalReport)
 M core/pipeline.py         (+250 行：process_full_report 等)
 M core/validate.py         (+54 行：NarrativeValidationError / validate_narrative)
?? tests/test_narrative.py  (新增 11 个测试)
```

这是**本次叙事功能的全部成果**，尚未创建分支、尚未提交。

### 2.3 本地其他资产

| 资产 | 路径 | 说明 |
|---|---|---|
| 旧完整链路备份 | `repo_backup_before_sync_20261117_1015/` | 含 `api.py`、`asr_hf_whisper.py`、真实 pipeline、`.env`、patch |
| git stash | `stash@{0}` | 2026-11-17 重置前保存的同一批本地工作 |
| GPU 完整副本 | `repo-cuda/` | 无 `.git`，完整可运行，已同步叙事功能 |
| 初始化/测试脚本 | `D:\Colostruct-Models\_setup\` | 下载、GPU 测试、API smoke、日志 |

---

## 3. 两个代码副本（务必分清）

| | `repository/Colostruct` | `repo-cuda` |
|---|---|---|
| 版本控制 | ✅ git，`main` = `origin/main` | ❌ 纯拷贝，无 `.git` |
| 用途 | **正式开发 / 提交 PR** | **GPU 真实运行 / 联调** |
| diagnosis | `process_case`（**mock**） | `process_case` + `process_case_real`（**真实**） |
| `api.py` | ❌ 不存在 | ✅ 存在（FastAPI 网关） |
| `core/asr_hf_whisper.py` | ❌ 不存在 | ✅ 存在（HF Whisper 后端） |
| 叙事功能 | ✅ 已实现（未提交） | ✅ 已同步 |
| `.env` | 指向 HF/cuda，但 main 代码**不支持** HF 后端（会退回 mock） | 指向 HF/cuda，真实生效 |
| 测试 | 147 passed / 2 skipped | 136 passed / 2 skipped（未拷 `test_narrative.py`） |

**关键陷阱**：在 `repository/Colostruct` 里直接跑 `streamlit`/pipeline，看到的是 **mock 结果**；`.env` 里的 `COLOSTRUCT_ASR_BACKEND=hf` 不会生效，因为 main 没有 `_build_real_asr_engine` 和 `asr_hf_whisper.py`。真实效果只能在 `repo-cuda` 看到。

**同步策略**：`pathology_schema.py` / `cleanup.py` / `validate.py` 两份完全一致，可直接拷贝；`pipeline.py` 两份不同（cuda 多真实链路），**不要整体覆盖**，只同步新增函数块。

---

## 4. 架构与数据流

### 4.1 diagnosis（15 字段）

```
audio file(s)
  → core/audio_merge.py（拼接、16k mono、offsets）
  → core/asr.py + core/asr_hf_whisper.py（HF Whisper）或 faster-whisper
  → core/asr_adapter.py（ASRResult → clean segments）
  → core/cleanup.py（去噪）
  → core/llm/service.py：Pass A（preprocessing）→ Pass B（extraction）
  → core/validate.py：证据/数值/极性/覆盖审计
  → core/pathology_schema.py：ColoStructExtraction（15 字段）
```

### 4.2 macro / micro（叙事）

```
audio
  → ASR（共享引擎，加锁串行）
  → core/llm/client.py：OllamaClient.generate_json(...)  ← A 组接口
        期望返回 {"text": "<narrative>"}
  → core/cleanup.py: clean_narrative_output()
  → core/validate.py: validate_narrative()（> ASR 原文 120% 直接失败）
  → NarrativeSection(text=..., status="success"|"failed"|"absent")
```

### 4.3 API / 前端

```
Streamlit (8501)
  → POST http://127.0.0.1:8000/api/process
    multipart: diag_audio, macro_audio, micro_audio（各自 0/1 个文件）
  → api.py（repo-cuda）
    - /api/health
    - /storage/audio/{case}/{file}（回放拼接音频）
    - /api/process（诊断 + macro/micro 纯转写）
  → 返回：
    {
      "status": "success|partial|failed",
      "error": null|str,
      "diagnosis": {"status": "...", "data": {audio_url, clean_segments, fields, override_logs, has_block}, "error": ...},
      "macro":     {"status": "...", "data": {audio_url, clean_segments, text}, "error": ...},
      "micro":     {"status": "...", "data": {...}, "error": ...}
    }
```

- `api.py` 把诊断 `audio_url` 从本地路径改写为 `http://<request host>:8000/storage/audio/...`。
- macro/micro 的 `audio_url` 为空（上传临时文件在 `finally` 删除，不保留原始音频）。
- ASR 引擎全局缓存 + `threading.Lock`（Whisper 非线程安全；并发加载会 `MODEL_LOAD_FAILED`）。
- API 对失败也返回 HTTP 200 + 结构完整 JSON，避免前端解析崩溃。
- CORS 全开；仅适合本机/可信内网；默认绑定 `127.0.0.1`。

### 4.4 前端契约（C 组代码，不要擅自改）

`ui/upload_panel.py`：

- `BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/process")`
- 只取每个模块第一个文件：`files['diag_audio'] = (name, bytes, type)`
- `requests.post(..., timeout=300)`（写死 300s）
- 上传类型限制 `mp3` / `wma`
- 响应必须有 `diagnosis` 键，`diagnosis.status == "success"` 时读 `data.clean_segments` 与 `data.fields`

---

## 5. 能力矩阵（均已实测）

| 能力 | 位置 | 状态 | 证据 |
|---|---|---|---|
| HF Whisper 加载 | `repo-cuda` | ✅ | 8 段、53.775 s 音频 |
| HF Whisper GPU float16 | `repo-cuda` | ✅ | 2.9–3.0 s，VRAM ≈ 571 MB |
| faster-whisper GPU | `repo-cuda` | ✅ | 12 s 音频 0.66 s，加载 1.72 s |
| 真实 diagnosis（15 字段） | `repo-cuda` | ✅ | API 7/7 smoke，字段完整 |
| 叙事 mock（36800 原文） | 两份 | ✅ | macro 1212 / micro 678 字符 |
| 叙事真实（ASR+Ollama） | `repo-cuda` | ✅ | 33.3 s，macro/micro 各 631 字符 |
| API `/api/process` | `repo-cuda` | ✅ | health / empty / corrupt / diag / macro+micro 全过 |
| Streamlit 前端 | 两份 | ✅ | HTTP 200，AppTest 0 异常 |
| 叙事接入 API | — | ❌ | `process_full_report` 未被 `api.py` 调用 |
| main 真实链路 | `repository/Colostruct` | ❌ | 仍 mock |
| Docker 镜像 | — | ❌ | Dockerfile 过期，见瓶颈 |
| CI | — | ❌ | 无 GitHub Actions |

测试数量：

- `repository/Colostruct`：**147 passed, 2 skipped, 26 subtests**（含新增 11 个叙事测试）
- `repo-cuda`：**136 passed, 2 skipped, 26 subtests**（未拷 `test_narrative.py`）

---

## 6. 本次新增：FullClinicalReport / 叙事功能（未提交成果）

### 6.1 `core/pathology_schema.py`

```python
NarrativeStatus = Literal["success", "failed", "absent"]

class NarrativeSection(_ColoStructModel):
    text: str | None = None
    status: NarrativeStatus = "absent"

class FullClinicalReport(_ColoStructModel):
    diagnosis: ColoStructExtraction
    macro: NarrativeSection = Field(default_factory=NarrativeSection)
    micro: NarrativeSection = Field(default_factory=NarrativeSection)
```

- `NarrativeSection` / `FullClinicalReport` 已加入 `__all__`。
- 位置：`core/pathology_schema.py:647` 与 `:675`。

### 6.2 `core/cleanup.py`

`clean_narrative_output(text: str) -> str`（`:325`）：

- 去掉 Markdown ``` 围栏（含 `markdown` 语言标记，行内/整行）；
- 去掉“好的，以下是大体检查：”“Here is the polished report:”等开场；
- 去掉“希望以上对您有帮助”“Hope this helps”等结尾；
- **保留 `1)`、`1&2)` 等数字序号**；
- 保留 `MACROSCOPIC EXAMINATION:` 这类临床标题；
- 折叠多余空行。

### 6.3 `core/validate.py`

`NarrativeValidationError(ValueError)`（`:1177`）与 `validate_narrative(llm_text, raw_asr_text) -> bool`（`:1186`）：

- 空原文 / 空润色文本 → 抛异常；
- `len(polished) > len(raw) * 1.2` → 抛异常；
- pipeline 捕获后把 section 置 `failed`。

> 这是**纯长度守卫**，不做语义校验；后续可升级为数字/实体一致性校验。

### 6.4 `core/pipeline.py`（两份都已加）

`process_full_report(diag_file, macro_file=None, micro_file=None) -> FullClinicalReport`：

- `ThreadPoolExecutor(max_workers=3)` 并行跑 diagnosis / macro / micro；
- diagnosis 优先 `process_case_real`（cuda），否则 `process_case`（main mock）；
- diagnosis 复用同一个 ASR 引擎（`_LockedASREngine`），避免并发加载两个 Whisper；
- macro/micro：ASR → `_polish_narrative()`（A 组 `OllamaClient.generate_json`，要求 `{"text": ...}`）→ `clean_narrative_output` → `validate_narrative`；
- 任一 section 失败只置 `failed`，不影响其他 section；
- diagnosis 失败 → 空 extraction + `has_block=True`（fail-closed）；
- Mock：`COLOSTRUCT_NARRATIVE_MOCK=1` 时直接返回 36800 原文（`MOCK_NARRATIVE_TEXT`）；
- 位置：main `core/pipeline.py:449`；cuda `core/pipeline.py:605`。

调用示例：

```python
from core.pipeline import process_full_report

report = process_full_report(diag_path, macro_path, micro_path)
print(report.diagnosis.fields["tumour_site"].value)
print(report.macro.status, report.macro.text[:80])
```

### 6.5 Mock 文本来源：`36800.docx`

`Sample2/SampleReport/36800.docx` **不是文本 docx，而是 3 张扫描图片**：

- image1：15 字段诊断清单；
- image2：MACROSCOPIC EXAMINATION 原文；
- image3：MICROSCOPIC EXAMINATION 原文。

已把 image2/3 的英文原文转写进 `MOCK_NARRATIVE_TEXT`（macro 1212 字符、micro 678 字符）。原图解压在 `D:\Colostruct-Models\_setup\docx36800\`。

### 6.6 测试

`tests/test_narrative.py`（新增 11 个）：

- 清洗：中英文客套、代码围栏、序号保留、临床标题保留；
- 校验：120 字符通过、121 字符拒绝、空输入、类型错误；
- Schema：默认 `absent`、状态赋值；
- mock 全链路：`process_full_report` → 15 字段 + success。

---

## 7. 运行环境快照（本机）

### 7.1 硬件 / 系统

| 项 | 值 |
|---|---|
| OS | Windows 11 家庭版 中文版 10.0.26200 |
| CPU | Intel Core Ultra 9 290HX Plus，24 核 |
| RAM | 31.5 GB |
| GPU | NVIDIA RTX 5070 Ti Laptop GPU，12 227 MiB，driver 592.47 |
| 集显 | Intel(R) Graphics（任务管理器 GPU 0；NVIDIA 是 GPU 1） |
| 磁盘 | C: 55.9 GB 可用；D: 200.8 GB 可用 |
| CUDA 驱动能力 | 支持 CUDA 12.8；`nvcc` 13.5（系统工具，非必需） |

### 7.2 Python 环境

| 环境 | 路径 | Python | 关键包 |
|---|---|---|---|
| `colostruct` | `D:\download\Anaconda\envs\colostruct` | 3.11.18 | torch **2.12.0.dev20260408+cu128**、transformers 4.49.0、faster-whisper 1.2.1、ctranslate2 4.9.0、streamlit 1.67.0、fastapi 0.162.5、pydantic 2.14.1、numpy 2.4.6 |
| `colostruct-cuda` | `D:\download\Anaconda\envs\colostruct-cuda` | 3.11.18 | torch **2.12.0.dev20260408+cu128**、transformers 4.49.0、faster-whisper 1.2.1、ctranslate2 4.9.0、streamlit 1.67.0、fastapi 0.163.1、pydantic 2.14.3、numpy 2.4.6、**nvidia-cudnn-cu12 9.20.0.48**、**nvidia-cublas-cu12 12.9.2.10** |

> ⚠️ 两个环境当前都检测到 `torch.cuda.is_available() == True`；`colostruct` 已不是纯 CPU 环境（可能是后来安装/被改动）。不要假设它是 CPU-only。
>
> ⚠️ **仓库 `requirements.txt` 仍然钉死 `torch==2.15.0+cpu` + CPU index**（PR #7 的版本）。GPU 机器不能“先装 cu128 再跑 requirements”（会被降级成 CPU 版），也不能“先跑 requirements 再装 cu128 不处理旧包”（可能残留冲突）。正确做法见第 16 节第 3 步，或像 `repo-cuda` 一样维护一份去掉 torch pin 的 requirements。

### 7.3 模型

| 模型 | 信息 |
|---|---|
| Whisper | `JackyHoCL/whisper-small-cantonese-yue-english`，revision `bde975727e573bb92d4c4ee3c05a29a0f79fb195`；本地目录 `D:\Colostruct-Models\whisper`；`model.safetensors` 966 995 080 B；SHA-256 `20fe857006eeb3cfd3c85946d73f01ac46743c410257619b322954d1c8cd99b9` |
| HF 缓存 | `D:\Colostruct-Models\huggingface`（硬链接了 Whisper 权重，`local_files_only` 可加载） |
| faster-whisper base | 已缓存 `Systran/faster-whisper-base` |
| Ollama | 0.40.16；`qwen3:8b`，digest `500a1f067a9f…`，5 225 388 164 B，Q4_K_M；实测推理时 `ollama ps` 显示 100% GPU（空闲时会卸载，显示为空） |
| 模型根目录 | `D:\Colostruct-Models\{whisper,huggingface,ollama}`；日志在 `_setup\` |

### 7.4 端口 / 进程（生成时）

- Streamlit 正在 8501 运行（来自 `repo-cuda`，pid 64744）。
- API 8000 **未启动**。
- Ollama 服务在 11434（按需拉起 llama-server）。

---

## 8. 运行手册（Windows PowerShell）

### 8.1 先解决 conda 不可用的问题

本机 PowerShell 执行策略会拦截 `conda-hook.ps1`，`conda activate` 可能报“无法将 conda 项识别…”。三种方式任选：

**方式 A（当前窗口，最快）**

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& "D:\download\Anaconda\shell\condabin\conda-hook.ps1"
conda activate colostruct-cuda
```

**方式 B（一次性修复，需重开终端）**

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
& "D:\download\Anaconda\Scripts\conda.exe" init powershell
```

**方式 C（不激活，直接用绝对路径，最稳）**

```powershell
$envPy = "D:\download\Anaconda\envs\colostruct-cuda"
$env:PATH = "$envPy\Library\bin;$envPy\Lib\site-packages\nvidia\cublas\bin;$envPy\Lib\site-packages\nvidia\cudnn\bin;$env:PATH"
$env:PYTHONUTF8 = "1"
```

### 8.2 启动 GPU 后端（在 `repo-cuda`）

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& "D:\download\Anaconda\shell\condabin\conda-hook.ps1"
conda activate colostruct-cuda

cd "D:\华为云盘\钱家萱的文件\大学\学习\Project-Based CST&AI Foundations\AI医生助手\AI医生助手agent工作区\repo-cuda"
$env:PATH = "$env:CONDA_PREFIX\Lib\site-packages\nvidia\cublas\bin;$env:CONDA_PREFIX\Lib\site-packages\nvidia\cudnn\bin;$env:PATH"
$env:PYTHONUTF8 = "1"

python api.py
# 看到 Uvicorn running on http://127.0.0.1:8000 才算成功
```

### 8.3 启动前端（另一个终端）

```powershell
conda activate colostruct-cuda
cd "...\repo-cuda"
$env:PYTHONUTF8 = "1"
python -m streamlit run app.py
# http://127.0.0.1:8501
```

### 8.4 自检

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
python -c "import sys; print(sys.executable)"          # 必须是 envs\colostruct-cuda\python.exe
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv -l 1
ollama ps
```

### 8.5 常见错误对照表

| 现象 | 原因 / 解决 |
|---|---|
| `conda : 无法将“conda”项识别…` | PowerShell 未初始化 / 执行策略拦截 → 8.1 方式 A/B/C |
| `ModuleNotFoundError: No module named 'dotenv'` | 用了系统 Python 或 base；`$env:CONDA_PREFIX` 为空时 PATH 拼错 → 检查 `sys.executable` |
| `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` | pip cuDNN 与 torch 自带 cuDNN 不一致；**保持 `nvidia-cudnn-cu12==9.20.0.48`** |
| `Could not load cublas64_12.dll` / ctranslate2 找不到 CUDA | 启动前把 `nvidia\cublas\bin`、`nvidia\cudnn\bin` 加进 PATH |
| `Dashboard 无法连接后端` | 只开了 Streamlit，8000 没有监听 → 启动 `api.py` |
| `Input type (float) and bias type (Half)...` | 已修复（`input_features` 转模型 dtype）；不要回退 `asr_hf_whisper.py` |
| `MODEL_LOAD_FAILED`（并发时） | 已通过共享 `_LockedASREngine` 修复；不要再让多个线程各自加载模型 |
| pydub 提示找不到 ffmpeg | 无害；实际用 `imageio-ffmpeg`；conda 的 `Library\bin\ffmpeg.exe` 在本机是坏的 |
| GPU 利用率只在 8501 页面出现 | 那是 Intel 集显在渲染；NVIDIA 是任务管理器 GPU 1，看 Compute/Cuda 图 |

### 8.6 Mock / 真实切换

| 场景 | 做法 |
|---|---|
| main 仓库（无真实链路） | 诊断自动走 mock；叙事可用 `COLOSTRUCT_NARRATIVE_MOCK=1` |
| repo-cuda 真实诊断 | `.env` 保持 `COLOSTRUCT_ASR_BACKEND=hf`、`WHISPER_DEVICE=cuda` |
| 叙事离线 mock | 设置 `COLOSTRUCT_NARRATIVE_MOCK=1`，macro/micro 直接返回 36800 原文 |
| 叙事真实 | 不设 mock；需要 Ollama 与 Whisper 可用 |

---

## 9. 当前瓶颈与技术难题（按优先级）

### P0 — 阻断协作 / 复现

**1. 真实链路完全未入库。**
`api.py`、`core/asr_hf_whisper.py`、`process_case_real`、`_build_real_asr_engine` 只存在于 `repo-cuda`（无 git）和本地备份。远端 `main` 与所有分支都没有完整真实链路。
→ 任何新机器 clone 下来只能跑 mock；也无法开 PR 评审。
→ **必须尽快提交。**

**2. 叙事功能未提交。**
5 个文件 + 1 个测试只在工作区；一旦误清理/重置就丢失（虽然 stash/备份还在）。
→ 建分支 `feat/full-report-narrative-sections` 提交 PR。

### P1 — 功能不完整 / 误导

**3. main 的 `.env` 指向 HF/cuda，但 main 代码没有 HF 后端。**
`repository/Colostruct/.env` 里 `COLOSTRUCT_ASR_BACKEND=hf`、`WHISPER_DEVICE=cuda`，但 main 的 `pipeline.py` 没有 `_build_real_asr_engine`，`core/asr_hf_whisper.py` 不存在。结果：配置看起来是真实的，实际跑的是 mock。
→ 要么把真实链路合进来，要么把 `.env` 示例改回 CPU/faster-whisper，并明确“main 仅 mock”。

**4. `process_full_report` 没有接入 API。**
`api.py` 只有 `/api/process`（诊断 + macro/micro 纯转写），没有调用 `FullClinicalReport`。
→ 新增 `/api/process_full`（或扩展 `/api/process`），返回 `FullClinicalReport.model_dump()`；需要和 C 组确认前端字段。

**5. 水印与 `AGENTS.md` 不一致。**
`core/export.py:35` 是中文水印，`AGENTS.md` 要求英文原文 `AI-assisted draft — not for clinical use without review`。
→ 需产品/A 组确认唯一标准；改动会影响导出测试。

### P2 — 工程债务 / 运行脆弱

**6. Dockerfile 过期且有硬错误。**
- `COPY data/hotwords.csv`，但仓库文件是 `data/HOTWORDS.csv`（Linux 大小写敏感 → build 失败）；
- 没有 `COPY api.py`，没有 `EXPOSE 8000`，`CMD` 只启动 Streamlit；
- 没有 `.dockerignore`（会把 `.env`、`storage/`、模型打进 build context）。
→ 修 Dockerfile + 加 compose（api + streamlit）或文档说明。

**7. README 目录树过期。**
列了不存在的 `core/hotwords.py`、`preprocess.py`、`align.py`、`llm.py`、`ehr_adapter.py`；缺 `api.py`、`core/asr_hf_whisper.py`、`core/llm/`。
→ 更新 README，补 quickstart。

**8. GPU 环境脆弱。**
- torch nightly cu128 与 cuDNN 必须严格对齐（9.20.0.48）；升级会崩。
- 必须把 nvidia DLL 目录加入 PATH，否则 ctranslate2 报错。
- Windows conda 激活/执行策略坑多。
→ 需要一份 `GPU_SETUP.md` 或安装脚本，并锁定版本。

**9. 线程模型是“伪并行”。**
`process_full_report` 确实起 3 个线程，但 ASR 被 `_NARRATIVE_ASR_LOCK` 串行化（为了安全），真正并行的是 LLM 润色。若要求 ASR 也并行，需要每线程独立引擎 + 显存预算（Whisper-small fp16 ≈ 0.6 GB/实例，本机 12 GB 可承受 2–3 个）。

**10. 叙事校验只有长度。**
`validate_narrative` 只检查 `>120%` 就失败，不做数字/实体/极性一致性校验。可能漏掉“等长但改事实”的润色。
→ 可复用 `core/validate.py` 的数字/极性工具做叙事级校验。

**11. 安全边界。**
`api.py` CORS `*`、无鉴权、`/storage/audio` 可下载拼接音频；默认绑定 `127.0.0.1` 没问题，但一旦 `API_HOST=0.0.0.0` 会把临床音频暴露到局域网。
→ 跨机必须可信内网 + 防火墙 + 认证（至少 token）。

**12. 云盘同步副本。**
`core/*(1).py`、`core/llm/*(1).py` 这类冲突副本曾反复出现（云盘同步导致），会污染 `git status`。
→ 提交前清理；`.gitignore` 可加 `*(1).py`。

**13. 其他小问题。**
- `data/HOTWORDS.csv`、`field_rules.yaml`、`corrections.csv` 当前没有任何代码读取（Docker/README 却引用）。
- `COLOSTRUCT_USE_REAL_PIPELINE` 在当前前端代码中未使用（旧版遗留）。
- `Dockerfile` 无 8000 端口；`README` 无 API 说明。
- `ui/upload_panel.py` 的 `timeout=300` 写死，低配机器可能不够。
- 没有 CI / 没有真实模型回归测试。

**14. `requirements.txt` 钉死 CPU torch，GPU 安装会互相覆盖。**
PR #7 的 `requirements.txt` 含 `--extra-index-url .../whl/cpu` 与 `torch==2.15.0+cpu`。GPU 机器若直接 `pip install -r requirements.txt` 会把 GPU torch 降级；若先装 cu128 再跑 requirements 也会被覆盖。`repo-cuda` 已经手工删掉 torch pin 才装成 cu128。
→ 建议拆成 `requirements.txt`（不钉 torch）+ `requirements-cpu.txt` / `requirements-gpu.txt`，或在文档中明确“GPU 机器使用 `--no-deps` / 强制重装”的顺序。
→ 验收：新 GPU 机器按文档操作后 `torch.cuda.is_available()==True` 且 `pip check` 无冲突。

---

## 10. 建议的下一步（按顺序执行，含验收标准）

### 任务 A（P0）：提交叙事功能

- 分支：`feat/full-report-narrative-sections`
- 提交：`core/pathology_schema.py`、`core/cleanup.py`、`core/validate.py`、`core/pipeline.py`、`tests/test_narrative.py`、`.env.example`
- 验收：`python -m pytest -q` → 147 passed；`COLOSTRUCT_NARRATIVE_MOCK=1` 跑通 `process_full_report`。
- 注意：不要带 `.env`、`storage/`、`__pycache__`。

### 任务 B（P0）：提交真实链路

- 分支：`feat/real-pipeline-integration`
- 文件：`api.py`、`core/asr_hf_whisper.py`、`core/asr.py`、`core/audio_merge.py`、`core/llm/client.py`、`core/pipeline.py`（`process_case_real` / `_build_real_asr_engine`）
- 依赖：`requirements.txt` 增加 HF/CUDA 说明（CPU torch 与 CUDA torch 二选一，不要同时钉死）
- 验收：`repo-cuda` 等价环境里 API 7/7 smoke；`pytest` 全绿。
- 冲突提示：任务 A 的 `pipeline.py` 与任务 B 的 `pipeline.py` 会改同一文件，建议 B 基于 A 的分支继续，或先合并 A 再 B。

### 任务 C（P1）：Full report 接入 API

- 新增 `POST /api/process_full`（保留 `/api/process` 兼容），返回 `FullClinicalReport.model_dump(mode="json")`
- 或者扩展现有 `/api/process`：当 macro/micro 需要真实润色时走 `process_full_report`
- 和 C 组确认前端展示字段（macro/micro 已有 text/clean_segments 结构）
- 验收：前端一次上传三路音频，得到完整 15 字段 + 两段叙事；失败时 `failed` 可见。

### 任务 D（P1）：水印统一

- 确认标准（`AGENTS.md` 英文原文 vs 当前中文版），修改 `core/export.py` 并同步测试/文档。
- 验收：导出 Markdown 首行精确匹配。

### 任务 E（P2）：Docker / README

- 修 `Dockerfile`：`COPY api.py`、`HOTWORDS.csv` 大小写、`EXPOSE 8501 8000`、compose 或双进程说明；加 `.dockerignore`。
- 更新 `README.md` 目录树与 Quickstart。
- 验收：`docker build` 成功；容器内 API + 前端可启动（模型通过 volume 挂载）。

### 任务 F（P2）：测试 / CI

- 给 `repo-cuda` 补 `tests/test_narrative.py`；
- 增加 API 契约测试（TestClient，不加载真实模型，用 fake engine）；
- 加 GitHub Actions：`pip install -r requirements.txt` + `pytest`（不打模型、不跑真实推理）。
- 验收：PR 自动跑绿。

### 任务 G（P2）：GPU/部署文档

- 把 conda 激活、PATH、cuDNN 版本、torch nightly 版本写进 `docs/`；
- 提供一键 `scripts/setup_gpu.ps1`（可选）。
- 验收：新机器按文档可复现 `torch.cuda.is_available() == True`。

---

## 11. 接续 agent 工作规约（务必遵守）

1. **先判断在哪个副本工作**：
   - 改代码 / 提交 PR → `repository/Colostruct`
   - 跑真实 GPU / 联调 → `repo-cuda`
   - 两份不要互相 `cp -r` 整体覆盖；`pipeline.py` 不同。
2. **A 组文件未经协调不要改**：
   `core/asr.py`、`core/asr_adapter.py`、`core/asr_hf_whisper.py`、`core/llm/*`。
3. **C 组前端未经协调不要改**：`app.py`、`ui/*`、`requirements.txt` 的前端段。
4. **不写死机器路径到共享源码**；路径放 `.env`（已 gitignore）。
5. **Windows 必须设置 `PYTHONUTF8=1`**，否则 16 个测试会因 GBK 失败。
6. **提交前**：
   ```powershell
   python -m pytest -q
   git status --porcelain
   git diff --stat
   ```
   确认没有 `.env`、`storage/`、`audio`、模型、`__pycache__`、`*(1).py`。
7. **提交规范**：feature branch → PR → 不直接 push main；PR 描述写清“改了什么/为什么/怎么验证”。
8. **不要声称跑通**，除非真的执行过命令；本文件中的数字都是实测的。
9. **GPU 相关改动后必须验证**：
   ```powershell
   python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv -l 1
   ollama ps
   ```
10. **失败时保留原始报错**，不要盲目升级/降级依赖；先判断是镜像、DLL、环境还是代码问题。

---

## 12. 首次接手 10 分钟检查清单

```powershell
# 1) 仓库状态
cd "...\repository\Colostruct"
git status -sb
git log --oneline -5

# 2) 测试
$env:PYTHONUTF8 = "1"
& "D:\download\Anaconda\envs\colostruct\python.exe" -m pytest -q   # 期望 147 passed

# 3) GPU 副本是否在跑
Get-NetTCPConnection -LocalPort 8000,8501 -State Listen -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:8000/api/health

# 4) 模型
ollama ps
Test-Path "D:\Colostruct-Models\whisper\model.safetensors"

# 5) 叙事 mock 快速验证
$env:COLOSTRUCT_NARRATIVE_MOCK = "1"
& "D:\download\Anaconda\envs\colostruct\python.exe" "D:\Colostruct-Models\_setup\narrative_unit_test.py"
```

如果 8000 未启动，按第 8 节启动 `repo-cuda/api.py`；如果 GPU 不可用，先看第 8.5 节的 cuDNN/PATH 两条。

---

## 13. 关键决策记录（避免走回头路）

| 决策 | 原因 |
|---|---|
| Whisper 默认用 A 组 HF checkpoint（`JackyHoCL/...`），不是更快的 faster-whisper | 与 A 组实验口径一致；`COLOSTRUCT_ASR_BACKEND=hf` |
| CUDA 上用 float16，CPU 上 float32 | GPU 显存/吞吐；CPU half 不稳定 |
| `process_full_report` 诊断也复用同一个 ASR 引擎 | 并发加载两个 Whisper 会 `MODEL_LOAD_FAILED` |
| 叙事 20% 长度守卫 | 防止 LLM 润色时“加内容”；先做确定性守卫，语义校验后置 |
| API 失败也返回 200 + 结构化 JSON | 前端 `requests` 解析更稳；前端已有 `diagnosis` 检查 |
| 诊断音频通过 `/storage/audio` 提供 HTTP URL | 浏览器 `<audio>` 不能播放 Windows 绝对路径 |
| main 保持 mock、真实链路单独 PR | 避免一次性大爆炸合并；但当前已拖太久，P0 应尽快处理 |

---

## 14. 参考与附件（本机路径）

| 内容 | 路径 |
|---|---|
| GitHub 仓库 | https://github.com/Qixx-xx/Colostruct |
| PR #7（已合并） | https://github.com/Qixx-xx/Colostruct/pull/7 |
| 正式仓库 | `repository/Colostruct` |
| GPU 完整副本 | `repo-cuda` |
| 旧链路备份 | `repo_backup_before_sync_20261117_1015` |
| git stash | `repository/Colostruct` → `stash@{0}` |
| 36800 扫描件 | `Sample2/SampleReport/36800.docx`；图片解压 `D:\Colostruct-Models\_setup\docx36800` |
| 模型根目录 | `D:\Colostruct-Models\{whisper,huggingface,ollama}` |
| 安装/测试脚本与日志 | `D:\Colostruct-Models\_setup\` |
| 产品/技术文档 | `repository/Colostruct/docs/`、`PRD-ColoStruct-MVP.md`、`TechDesign-ColoStruct-MVP.md` |
| A 组接口说明 | `repository/Colostruct/A_GROUP_README.md` |
| 项目约束 | `repository/Colostruct/AGENTS.md` |

---

## 15. 成果打包清单（迁移时带什么）

> ⚠️ 注意：**当前只把这份 md 发给另一个 agent 是不够的**——真实链路还没进 GitHub。要么先完成任务 A/B 的 PR，要么把 `repo-cuda` 按下面的规则打包。

### 15.1 必须随代码迁移

```text
core/pathology_schema.py
core/cleanup.py
core/validate.py
core/pipeline.py
core/asr.py
core/asr_adapter.py
core/asr_hf_whisper.py          # 目前只在 repo-cuda
core/audio_merge.py
core/export.py
core/extract_clinical_info.py
core/llm/                       # A 组：client/prompts/preprocessing/extraction/parsing/result/service
api.py                          # 目前只在 repo-cuda
app.py
ui/                             # C 组前端
tests/                          # 含 test_narrative.py
data/field_rules.yaml
data/corrections.csv
data/HOTWORDS.csv
docs/
AGENTS.md
A_GROUP_README.md
requirements.txt
.env.example
Dockerfile
.gitignore
```

### 15.2 配置（只给模板，不给真实 .env）

- `.env.example`：已包含 LLM / ASR / 存储 / 前后端 / GPU 设备等全部变量；
- 新机器复制成 `.env` 后，只改本机相关项（模型路径、Ollama 地址、API 地址）。

### 15.3 模型（只给“身份”，不打包权重）

| 模型 | 迁移方式 |
|---|---|
| Whisper | 给 `WHISPER_MODEL_ID` + `WHISPER_REVISION`，首次运行自动下载；离线机器拷贝 `D:\Colostruct-Models\whisper` 并设 `WHISPER_MODEL_PATH` |
| qwen3:8b | `ollama pull qwen3:8b`；记录 digest `500a1f067a9f...` 作为版本凭证 |
| faster-whisper base | 可选；`Systran/faster-whisper-base` 自动缓存 |

### 15.4 测试素材

- 合成音频：`synthetic_pathology_tts_win_zira.wav`（本机生成，SHA-256 `563031b5...`，可重新生成，见 `_setup/make_synthetic_audio.ps1`）；
- `36800.docx`：3 张扫描图，含报告原文；来源为 `Sample2` 样例，**是否已去标识化、能否外发需先确认**；
- **不要**打包任何真实患者音频（`Sample2` 的真实病例）。

### 15.5 不要打包

```text
.env
storage/
*.wav  *.mp3  *.wma  *.m4a  *.flac
models/  *.safetensors  *.gguf  *.pt  *.pth
__pycache__/  .pytest_cache/  *.pyc
*(1).py                 # 云盘冲突副本
.git/                   # 如果只做运行副本
```

---

## 16. 迁移到另一台机器的 12 步

1. **拿代码**：`git clone https://github.com/Qixx-xx/Colostruct`，切到包含真实链路/叙事的分支（完成 P0 PR 后）。
2. **Python**：3.11（conda 或 venv）。
3. **依赖**：
   - CPU：`pip install -r requirements.txt`
   - GPU（正确顺序，二选一）：
     - **推荐**：使用去掉 `torch==2.15.0+cpu` 与 CPU `--extra-index-url` 的 requirements（可直接把 `repo-cuda/requirements.txt` 拷成 `requirements-gpu.txt`），然后：
       ```powershell
       pip install -r requirements-gpu.txt
       pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
       pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.20.0.48
       ```
     - **或**：先按原版装（会得到 CPU torch），再强制重装 GPU torch：
       ```powershell
       pip install -r requirements.txt
       pip install --force-reinstall --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
       pip install --force-reinstall nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.20.0.48
       ```
  装完验证 `torch.cuda.is_available()` 为 True 且 `pip check` 无冲突。
4. **ffmpeg**：系统安装，或依赖 `imageio-ffmpeg`。
5. **Ollama**：安装 0.40.16+，`ollama pull qwen3:8b`；`OLLAMA_MODELS` 可指向独立盘。
6. **Whisper**：设 `WHISPER_MODEL_ID/REVISION` 自动下载，或拷贝离线目录。
7. **配置**：`copy .env.example .env`，改本机路径/地址；Windows 另设 `PYTHONUTF8=1`。
8. **启动后端**：`python api.py`（GPU 版记得 PATH 加 nvidia 两个 bin）。
9. **启动前端**：`python -m streamlit run app.py`。
10. **健康检查**：`/api/health` 200；`torch.cuda.is_available()` True（GPU 机器）。
11. **冒烟**：`pytest -q`；`POST /api/process` 传一段音频；检查 15 字段 + macro/micro。
12. **验收**：导出 Markdown 首行水印正确；失败路径返回结构化 JSON；GPU 机器上 `nvidia-smi` 能看到 python 进程。

**迁移验收指标（与本次实测对齐）**：

- `pytest`：≥147 passed（含叙事测试）；
- GPU ASR：53.8 s 音频 ≤ 5 s（本机 2.9–3.0 s）；
- 全链路 `process_full_report`：≤ 60 s（本机 33.3 s）；
- API 冒烟：7/7；
- 15 字段完整，macro/micro `success` 或明确 `failed`；
- `ollama ps` 显示 100% GPU。

---

## 17. 一句话总结给下一位 agent

> 真实系统只活在本机 `repo-cuda`（GPU，已验证）；`repository/Colostruct` 的 main 仍是 mock，但已有未提交的“叙事长文本”功能（147 测试全绿）。你的第一优先级是把这两部分整理成分支/PR，第二优先级是把 `process_full_report` 接进 `api.py`，让前端一次请求拿到 15 字段 + macro + micro；不要重做模型、不要动 A 组/C 组文件、不要把模型和音频提交进 git。
