# ColoStruct - AI 结直肠外科门诊助手

ColoStruct 是一个面向结直肠外科医生的本地优先 Web 应用：将有序的多段音频转化为可审阅的 15 项结直肠癌病理报告草稿，并附带用于证据核对的转写文本。

系统采用前后端分离结构：

- **前端** `frontend/colostruct_v3/`（Vue 3 + Vite）：负责上传、审校、导出
- **后端** `api.py`（FastAPI）：负责调用本地 ASR / LLM 流水线

> 早期的 Streamlit 前端已归档到 `legacy_mvp/`，仅供回溯参考，不再维护。
> 想查看归档前的完整状态：`git checkout v1-streamlit-mvp`。

## 📁 项目目录结构

```text
colostruct/
├── api.py                      # FastAPI 网关：/api/process、/api/health、音频回放
├── frontend/                   # 前端（Vue 3 + Vite）
│   └── colostruct_v3/
│       ├── src/                # 组件、全局状态、导出逻辑、接口封装
│       ├── public/config.js    # 运行时配置（后端地址，改这里不需要重新构建）
│       ├── introduction/       # 前端文档：入门、迁移说明、接口契约、Git 指南
│       ├── scripts/selfcheck.mjs # 前端自检（npm run selfcheck）
│       ├── package.json
│       └── vite.config.js      # 开发代理：/api 与 /storage 转发到 127.0.0.1:8000
├── legacy_mvp/                 # 已归档的 Streamlit 前端（不再维护）
│   ├── app.py                  # Streamlit 入口：路由、双栏布局
│   └── ui/
│       ├── __init__.py         # 让 Python 识别为包
│       ├── common.py           # 公共库（字典、时间轴、卡片渲染、回调）
│       ├── upload_panel.py     # 上传面板：诊断 / 大体 / 镜下音频上传
│       ├── review_panel.py     # 审校面板：双栏审阅（音频/转写 ↔ 15 个字段）
│       └── export_panel.py     # 导出面板：Markdown / JSON 导出
├── core/
│   ├── pipeline.py             # 编排：mock / 真实 ASR+LLM、FullClinicalReport
│   ├── audio_merge.py          # 音频拼接 (pydub)，16 kHz 单声道，段间 0.5 秒静音
│   ├── asr.py                  # ASR 接口、结果契约、faster-whisper 后端
│   ├── asr_hf_whisper.py       # Hugging Face Whisper 后端（CUDA float16 支持）
│   ├── asr_adapter.py          # ASRResult → 后端 clean segments
│   ├── cleanup.py              # 仅去噪：语气词、重复片段、表层归一化、叙事清洗
│   ├── extract_clinical_info.py# A 组对外入口（兼容层）
│   ├── pathology_schema.py     # 15 字段 / NarrativeSection / FullClinicalReport
│   ├── validate.py             # 证据审计、字段规则、叙事长度校验
│   ├── export.py               # Markdown / JSON 导出 + AI 水印
│   └── llm/
│       ├── __init__.py
│       ├── client.py           # Ollama HTTP 客户端（JSON 模式）
│       ├── parsing.py          # LLM 输出解析
│       ├── prompts.py          # Pass A / Pass B Prompt
│       ├── preprocessing.py    # Pass A：口误纠正 + 时序覆盖
│       ├── extraction.py       # Pass B：15 字段抽取
│       ├── result.py           # AGroupResult / Diagnostics 契约
│       └── service.py          # Pass A → Pass B 编排
├── data/
│   ├── golden/                 # 黄金测试集（去标识化合成数据）
│   ├── field_rules.yaml        # 字段规则（15 个字段）
│   ├── HOTWORDS.csv            # 结直肠术语词典
│   └── corrections.csv         # 表层形式映射
├── storage/                    # 运行时生成（已被 .gitignore 忽略）
│   └── audio/                  # 上传片段 + 拼接音频
├── eval/
│   └── run_f1.py               # 15 个字段的 F1 计算
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fake_asr_backend.py
│   ├── test_asr_adapter.py
│   ├── test_asr_contract.py
│   ├── test_asr_engine_fake.py
│   ├── test_asr_offline.py
│   ├── test_asr_real_model.py
│   ├── test_a_group_llm_contract.py
│   ├── test_cleanup_validate_integration.py
│   ├── test_narrative.py       # 叙事清洗 / 20% 校验 / process_full_report
│   ├── test_privacy_redaction.py
│   ├── test_result_backend_integration.py
│   ├── test_result_contract.py
│   ├── test_service_real_schema.py
│   └── test_service_result.py
├── docs/                       # 产品、技术、测试、研究文档
├── design/                     # 早期页面设计参考图
├── agent_notes/                # AI 提示词及上下文存档
├── .env.example                # 环境变量模板（复制为 .env）
├── .gitignore
├── AGENTS.md                   # 项目约束与协作说明
├── Dockerfile
├── requirements.txt            # CPU / 通用依赖（含 CPU torch）
├── requirements-gpu.txt        # GPU 依赖（不含 torch，配 CUDA 12.8 单独安装）
├── A_GROUP_README.md           # A 组技术细节及 A/B 分工
└── README.md
```

## 🚀 快速开始

### 1. Python 环境

```powershell
conda create -n colostruct python=3.11 -y
conda activate colostruct
pip install -r requirements.txt
```

### 2. 本地模型

```powershell
# LLM
ollama pull qwen3:8b

# ASR：首次运行会按 WHISPER_MODEL_ID 自动下载 Hugging Face 模型；
# 离线机器可把模型目录放到 WHISPER_MODEL_PATH 指定的位置。
```

### 3. 配置

```powershell
copy .env.example .env
# 编辑 .env：OLLAMA 地址、WHISPER_MODEL_PATH 等
```

> `BACKEND_API_URL` 只被归档的 Streamlit 前端使用。
> Vue 前端默认请求同源的 `/api/process`，由 Vite 代理转发到 8000 端口，无需配置。

### 4. 启动

#### 终端 1：后端（必须先起）

```powershell
python api.py
```

- 健康检查：http://127.0.0.1:8000/api/health

#### 终端 2：前端

需要 Node.js 22.18+ 或 24.12+。

```powershell
cd frontend/colostruct_v3
npm install        # 仅首次运行需要
npm run dev
```

- 打开 http://localhost:5173
- 前端会自动把 `/api` 和 `/storage` 请求转发到 `127.0.0.1:8000`

#### 可选：运行归档的 Streamlit 版

只用于对照旧行为，功能不再更新。

```powershell
python -m streamlit run legacy_mvp/app.py
```

- 地址：http://127.0.0.1:8501

### GPU（CUDA 12.8，可选）

```powershell
pip install -r requirements-gpu.txt
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.20.0.48
```

并在 `.env` 中设置：

```ini
ASR_DEVICE=cuda
WHISPER_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
```

> 上述 cuBLAS/cuDNN 版本是 Windows + CUDA 12.8 的已验证组合；cuDNN 必须与 torch 自带版本一致，否则会出现 `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH`。

## 📚 前端文档

都在 `frontend/colostruct_v3/introduction/`：

| 文件 | 内容 |
|---|---|
| `FRONTEND_PRIMER.md` | 前端入门：怎么运行、运行原理、每个文件负责什么、怎么上传 GitHub |
| `GIT_GUIDE.md` | Git 纯新手说明：clone / add / commit / push / 冲突处理 |
| `MIGRATION_NOTES.md` | 从 Streamlit 迁移的对照表、与旧版的差异、验收清单 |
| `API_CONTRACT.md` | `/api/process` 接口契约（给后端核对用） |
| `TALK_5MIN.md` | 五分钟汇报讲稿 |

## ✅ 测试

后端：

```powershell
python -m pytest -q
```

前端自检（不需要浏览器，约 10 秒）：

```powershell
cd frontend/colostruct_v3
npm run selfcheck
```
