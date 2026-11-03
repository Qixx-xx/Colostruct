# ColoStruct - AI 结直肠外科门诊助手

ColoStruct 是一个面向结直肠外科医生的本地优先 Web 应用，可将有序的多段音频转化为可审阅的 15 项结直肠癌病理报告草稿，并附带用于证据核对的转写文本。

## 📁 项目目录结构


```text
colostruct/
├── app.py                      # Streamlit 入口：路由、双栏布局
├── ui/
│   ├── __init__.py         # 让 Python 识别为包
│   ├── common.py           # 公共库（原 utils.py：字典、时间轴、卡片渲染、回调）
│   ├── upload_panel.py         # 上传面板：多段音频有序上传与拼接状态
│   ├── review_panel.py         # 审校面板：双栏审阅（音频/转写 ↔ 15 个字段）
│   └── export_panel.py         # 导出面板：导出按钮与格式选择
├── core/
│   ├── pipeline.py             # 编排：上传 → 拼接 → 转写 → 清洗 → LLM 预处理 → 抽取 → 校验
│   ├── audio_merge.py          # 音频拼接 (pydub)，16 kHz 单声道，段间 0.5 秒静音
│   ├── asr.py                  # faster-whisper 封装
│   ├── hotwords.py             # 结直肠术语词典与偏置提示词构造
│   ├── cleanup.py              # 仅去噪：语气词、重复片段、表层归一化
│   ├── preprocess.py           # LLM 预处理：口误纠错 + 时序覆盖
│   ├── align.py                # 时间戳对齐与证据回溯
│   ├── llm.py                  # LLM 调用封装 + JSON Schema 约束 + 重试
│   ├── pathology_schema.py     # 15 字段 Pydantic 模型
│   ├── validate.py             # 事后审计：证据、白名单、字段规则、覆盖验证
│   ├── export.py               # Markdown / JSON 导出 + AI 水印
│   └── ehr_adapter.py          # EHR 适配层（桩，不连接真实系统）
├── data/
│   ├── golden/                 # 黄金测试集（去标识化合成数据）
│   ├── field_rules.yaml        # 字段规则（15个字段）
│   ├── hotwords.csv            # 术语词典
│   └── corrections.csv         # 表层形式映射
├── storage/                    # 运行时生成（已被 .gitignore 忽略）
│   ├── colostruct.db           # SQLite
│   ├── audio/                  # 上传片段 + 拼接音频
│   └── exports/                # 导出文件
├── eval/
│   ├── run_cer.py              # CER 计算
│   ├── run_f1.py               # 15 个字段的 F1 计算
│   └── report.md               # 评估报告输出
├── tests/
│   ├── test_audio_merge.py
│   ├── test_cleanup.py
│   ├── test_validate.py
│   └── test_export.py
├── docs/                       # 项目文档与里流程设计图
├── design/                     # 前端页面设计图
├── agent_notes/                # AI提示词及上下文存档
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
├── A_GROUP_README.md           #A组技术细节及AB具体工作划分
└── README.md
