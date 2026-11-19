# 粤英混杂医学 ASR + LLM 数据生成：技术路线调研报告

> 生成时间：2026-11-19 · 项目：ColoStruct（https://github.com/Qixx-xx/Colostruct）
> 调研范围：粤英混杂（Cantonese-English code-switching）ASR 低资源适配、LLM 合成训练数据、医学领域术语识别、LLM 抽取层调整策略
> 配套材料：`research/scholar_csen_asr.csv`、`research/scholar_synthetic_tts.csv`、`research/scholar_medical_asr.csv`（学术检索原始结果）

---

## 0. 一页结论（TL;DR）

**Q1：12 条约 30 秒的真实数据（合计约 6 分钟）完全无法微调，怎么办？**

答：不要再等真实数据。学术界对低资源 ASR 的成熟解法是三层组合，按投入从低到高：

1. **零训练层（1-2 天）**：热词/上下文偏置（Whisper `initial_prompt` + 解码增强），先吃掉"医学术语识别错"这一大块错误；
2. **合成数据层（1-2 周，本报告核心）**：LLM 生成粤英混杂病理口语文本 → 粤语 TTS 合成音频 → 微调 Whisper。这正是老师建议的"用 LLM 生成训练数据"，且有 ICASSP 2025 的公开先例（MCE 数据集）；
3. **公开语料层**：MCE（34.8h 粤英混杂）、WenetSpeech-Yue（21800h 粤语）、Common Voice zh-HK/yue 等做预微调或混训，弥补合成音频的声学单一性。

**12 条真实数据的正确定位：永远做测试集/验证集，绝不做训练集。** 它是你唯一可信的"真实世界标尺"。

**Q2：老师说的"利用 LLM 生成训练数据进行调整"，是提示词级还是参数级？**

答：**对 ASR 层，是参数级微调**——LLM 在这里只是"数据制造机"（生成文本），音频由 TTS 合成，最终用这些 (音频, 文本) 对对 Whisper 做有监督微调（SFT/LoRA）。这不是提示词工程，也不存在"提示词上的 BP 迭代"。

**对 LLM 抽取层（Pass A/B），先提示词、后参数**：qwen3:8b 这类模型先做提示词工程 + 评测集迭代即可；如果效果不够，再用 LLM 生成的 (转写文本 → 15 字段) 配对数据做 LoRA SFT。若老师确实想要"提示词的可量化迭代"，对应的技术是 DSPy / TextGrad 这类"文本梯度"框架，而不是真的反向传播。

---

## 1. 问题重述与关键约束

| 约束 | 影响 |
|---|---|
| 真实数据仅 12 条 × 30s（≈6 分钟） | 任何直接微调都会严重过拟合；只能当测试集 |
| 场景：粤英混杂 + 结直肠病理术语（15 字段） | 通用 ASR 双重失效：语言混杂 + OOV 术语 |
| 现有基座：`JackyHoCL/whisper-small-cantonese-yue-english`（Whisper-small 粤语微调版） | 已是合理起点；可替换/对照更强的基座 |
| 硬件：RTX 5070 Ti Laptop 12GB | Whisper-small 全参微调可行；large-v3 可推理、LoRA 微调需省显存技巧 |
| 硬约束：不编造临床事实、字段需证据、优先合成/去标识数据 | 合成数据路线**恰好合规**：不碰真实患者隐私 |

---

## 2. Q1 详解：ASR 低资源破局的三层路线

### 2.1 第 0 层：热词 / 上下文偏置（零训练，先做）

**原理**：Whisper 的 `initial_prompt` 会把给定文本作为解码前缀，解码器会倾向输出其中出现过的词。这是不改参数的领域适配手段，对专有名词/术语尤其有效。

**学术依据**：

- SIGDIAL 2024《Improving Speech Recognition with Jargon Injection》：把领域术语注入 Whisper 解码（initial prompt + trie 加权解码），在领域语料上显著提升，且无需训练数据。 (https://aclanthology.org/2024.sigdial-1.42.pdf)
- arXiv 2502.11572《Improving Rare-Word Recognition of Whisper in Zero-Shot Settings》：Whisper 对领域稀有词识别差是公认问题，上下文偏置是直接解法；该文进一步用 670h Common Voice 微调出"可被提示偏置"的 Whisper，稀有词识别提升 45.6%，且泛化到未见语言。 (https://arxiv.org/pdf/2502.11572)
- TCPGen（Interspeech 2023）：指针网络把偏置词表融合进解码，Whisper-large 上稀有词 WER 相对降 40-50%。 (https://www.isca-archive.org/interspeech_2023/sun23e_interspeech.pdf)

**对本项目的直接落点**：仓库里已有 `data/HOTWORDS.csv` 但**没有任何代码读取它**（交接文档 P2-13 已指出）。第一优先级就是把 15 字段相关术语（mesorectal excision、circumferential margin、perineural invasion 等英文术语 + 中文/粤语对应说法）经 `initial_prompt` 注入 `core/asr_hf_whisper.py` 的解码调用。

**局限**：prompt 长度有限（经验上 < 224 token 前缀窗口），热词表大时需要分批/检索式选择；对"发音层面的粤语混杂"无能为力——那是声学和语言模型问题，必须靠微调。

### 2.2 第 1 层：LLM + TTS 合成数据管线（核心路线）

**这就是老师建议的学术原型**。已有公开工作完整走过这条路：

**先例 1：MCE 数据集 + Whisper-MCE（ICASSP 2025，HKUST）**

- 用 **多智能体数据生成框架（MADGF，基于 GPT-4）** 生成粤英混杂文本（>16,000 句，覆盖多话题），再由 20 位真人（10 男 10 女，广式/港式粤语）录音，得到 34.8-40 小时粤英混杂音频。
- 用它微调 Whisper 得到 **Whisper-MCE：混杂错误率 MER 14.28%，比原版 Whisper 相对降低 35.13%**；在 Common Voice zh-HK 上 CER 12.61%（SOTA）。
- 代码与数据公开：GitHub `Shelton1013/Whisper_MCE`（数据集研究用途授权，课程项目可用，注意不可商用）。 (https://github.com/Shelton1013/Whisper_MCE)

**先例 2：SwitchLingua（MCE 团队的后续工作）**

- 用 LLM 框架（LinguaMaster）生成 42 万条多语言混杂文本（含粤语、12 种语言），真人录音 80+ 小时。**文本全部由 LLM 生成**这一范式再次被验证。 (https://arxiv.org/pdf/2506.00087)

**先例 3：TTS 合成替代真人录音（低资源 ASR 的标准做法）**

- ICASSP 2025《Enhancing Low-Resource ASR through Versatile TTS》：微调 CosyVoice 生成合成语音做数据增强，显著缩小低资源 ASR 数据差距。 (https://arxiv.org/pdf/2410.16726)
- LREC 2026《Investigating the role of synthetic data augmentation…》：系统研究 TTS 增强在什么条件下对低资源 ASR 最有效。 (https://aclanthology.org/anthology-files/anthology-files/pdf/lrec/2026.lrec-1.442.pdf)
- ACL 2023《Making More of Little Data》：小数据 + 增强的系统方法论。 (https://aclanthology.org/2023.acl-long.42/)
- 医学领域先例：UNITED-MEDASR（arXiv 2412.00055）用**合成数据 + 语义纠正**微调 Whisper 做临床语音识别。 (https://arxiv.org/abs/2412.00055)

**对 MCE 路线的一个工程改良**：MCE 用真人录音是因为 2023 年 TTS 质量不够。2025-2026 年粤语 TTS 已可用（见 2.4），可以**用 TTS 替代真人录音**，把"录音成本"降为零，数据规模只受算力限制。建议"真人 12 条 + TTS 合成 N 小时"混训，TTS 音频负责覆盖术语和句式，真人数据负责评测。

### 2.3 第 2 层：公开语料（预微调 / 混训 / 对照）

| 数据集 | 规模 | 内容 | 可用性 | 用途建议 |
|---|---|---|---|---|
| **MCE** | 34.8h，>16k 句 | 粤英混杂（GPT-4 生成文本+真人录音） | GitHub 公开，研究用途 | **首选**：与本项目任务完全同分布，可直接混训 |
| **WenetSpeech-Yue** | 21,800h | 粤语 10 领域，多维标注；WSYue-eval 含 code-switch 评测子集 | arXiv 2509.03959，AAAI 2026 | 粤语底座增强；其 code-switch 子集可做额外评测 |
| **SwitchLingua** | 80+h 音频，420k 文本 | 12 语言混杂（含粤语、健康话题） | MCE 团队陆续释出 | 关注释出，粤英子集可用 |
| **CUMIX**（CUHK） | 17h | 粤英混杂朗读 | 需申请（LDC/CUHK） | 备选 |
| Common Voice yue / zh-HK | 203h / 108h | 纯粤语朗读 | CC0，直接下载 | 防灾难性遗忘的回放数据 |
| MDCC | 73.6h | 粤语有声书 | 公开 | 同上 |
| SEAME / ASCEND | 30h+ / 10h+ | **普通话**-英语混杂 | 公开 | 不推荐直接混训（语言不同），方法论参考 |

（来源：arXiv 2509.03959、arXiv 2310.17953、arXiv 2201.02419）

### 2.4 粤语 TTS 工具链（合成数据的"音频工厂"）

| 工具 | 特点 | 许可 | 建议 |
|---|---|---|---|
| **CosyVoice2**（阿里） | 支持粤语，zero-shot 声音克隆，多说话人 | Apache-2.0 | **首选**：多人声避免合成音频"声学过窄" |
| **GPT-SoVITS v2** | 支持粤语（`yue`），5 秒参考音即可克隆 | MIT | 备选，社区成熟 |
| **canto-tts**（typangaa） | 港式粤语 + 英文混杂专用，CPU 可跑，ONNX | Apache-2.0 | 轻量备选；单一默认音色，code-switch CER 13.87% |
| edge-tts `zh-HK-*` 音色 | 微软在线服务，零部署 | 在线服务 | **注意**：项目约束"不把临床数据发到未批准云端"——但合成文本不含真实患者数据，用 LLM 生成的去标识文本做 TTS 是合规的；若严格内网则不用 |

**关键工程点**：用**多个说话人/音色**合成（声音克隆 5-10 个自愿者参考音，或多模型混合），再加速度/音高/噪声增强。单一 TTS 音色会让 ASR 学到"TTS 腔"而非"人声鲁棒性"。

### 2.5 微调方法学与数据量经验（给"完全无法微调"祛魅）

经验证据：

- **1 小时**领域内标注音频即可把 Whisper-medium 在儿童语音上从 13.10% WER 降到 9.56%（133h 也才到 8.86%，收益曲线极陡）。 (https://kili-technology.com/blog/fine-tuning-audio-models-guide)
- **4 小时**音频微调 Whisper-small 可行，关键是增强 + 防过拟合（早停、验证集选 checkpoint）。 (https://www.f22labs.com/blogs/how-to-fine-tune-whisper-small-for-better-speech-recognition/)
- HF 官方教程：**10 小时** Common Voice 在免费 T4 上不到 1 小时训完。 (https://github.com/Vaibhavs10/fast-whisper-finetuning)
- **LoRA/PEFT**：只训低秩矩阵，小数据下显著缓解过拟合；MDPI 2024 土耳其语实验显示 LoRA 微调后 WER 相对降 43-52%（大数据集上）。 (https://www.mdpi.com/2079-9292/13/21/4227)
- Interspeech 2025《Adapting Whisper for Parameter-Efficient Code-Switching Speech Recognition via Soft Prompt Tuning》：专门针对混杂语音的软提示微调，保留预训练知识的同时适配混杂场景。（见 `research/scholar_csen_asr.csv`）

**结论**：你们的瓶颈从来不是"6 分钟数据能不能微调"，而是"去哪里弄 20-50 小时同分布数据"。合成数据管线 + MCE 混训正好补上这个缺口。

**硬件核算（RTX 5070 Ti 12GB）**：

- Whisper-small（244M）**全参微调** fp16 + gradient checkpointing：可行（约 6-8GB 显存）。
- whisper-large-v3（1.55B）：推理 fp16 没问题；微调走 **LoRA（r=32/64）+ 8bit optimizer**，可行但慢。
- 建议先在 whisper-small 粤语基座上跑通管线，再评估是否上 large-v3。

### 2.6 基座模型选择实验（低成本、高信息）

值得花 1 天做的对照（全部在你们 12 条真实测试集上测 CER/MER）：

1. 当前基座 `JackyHoCL/whisper-small-cantonese-yue-english`
2. `openai/whisper-large-v3`（v3 明确在训练中加入了粤语）
3. Whisper-MCE（ICASSP 2025 发布的粤英混杂微调权重）
4. SenseVoice-Small（阿里，支持粤语，FunASR 生态）

选一个最强基座再做第 1-2 层，避免在弱基座上浪费微调预算。

---

## 3. Q2 详解：LLM 层"生成训练数据进行调整"到底是什么

### 3.1 先把两个层面分开

老师的话容易被听成一件事，实际涉及**两个不同模型**：

| | ASR 层（Whisper） | LLM 层（qwen3:8b，Pass A/B 抽取） |
|---|---|---|
| LLM 生成数据的角色 | 生成粤英混杂**口语化文本** → TTS → (音频,文本) 对 | 生成 (转写文本 → 15 字段 JSON) **配对样本** |
| 消费方式 | **参数级**：Whisper SFT/LoRA | 提示词级（首选）或 LoRA SFT（备选） |
| "BP 迭代"存在吗 | 存在——对 Whisper 参数反向传播 | 提示词无 BP；若要迭代用 DSPy/TextGrad；参数迭代即 SFT |

### 3.2 ASR 侧：LLM 是"数据制造机"，不是被调整对象

管线（对应 MADGF 的医学版）：

```
医学知识源（15 字段定义、病理报告模板、术语表）
  → LLM 生成粤英混杂病理口述文本（多智能体：生成器→评审→过滤）
  → 质量过滤（混杂比例、术语覆盖、口语化程度、去重）
  → 粤语 TTS 多音色合成 + 声学增强
  → (音频, 文本) 训练集 20-50h
  → Whisper LoRA/全参微调
  → 在 12 条真实数据上评测（CER/MER/术语命中率）
```

**生成文本的设计要点**（从 MCE/SwitchLingua 论文提炼）：

- **混杂模式要仿真**：港式粤英混杂有语言学规律（英文多为名词/术语嵌入粤语句架，即 Matrix Language Frame）。给 LLM 的 prompt 里放 12 条真实转写的**句法模式**作为 few-shot 示例（注意：只用模式，不泄露真实患者内容）。
- **术语覆盖要强制**：15 字段 × 每字段的英文术语/粤语口语说法/同义变体，做成 checklist 要求生成器逐项覆盖。
- **口语化**：口述不是书面报告——要有犹豫、改口、重复（你们的 Pass A 正好处理这些，训练数据里也该有）。
- **多智能体评审**：一个 agent 生成、一个 agent 按 checklist 打分、不合格重生成（MADGF 原文做法）。

### 3.3 LLM 抽取侧：提示词优先，三条升级路径

**路径 A（现在就该做）：提示词工程 + 评测集**
为 Pass A/B 建一个 30-50 条的评测集（LLM 生成转写文本 + 人工核对 15 字段标注），每次改 prompt 跑一遍看准确率/字段级 F1。这回答了"如何量化"——**量化靠固定评测集，不靠 BP**。

**路径 B（如果老师坚持"可迭代的提示词优化"）：DSPy / TextGrad**
- **TextGrad**（NeurIPS 2024）：把 LLM 的批评当作"文本梯度"反向传播到 prompt——这是"提示词上的 BP 迭代"这个直觉的**真实学术对应物**。
- **DSPy**：把 prompt 当作可优化程序，用评测指标驱动自动搜索 few-shot 示例和指令。
- 如果你们想回应老师的思路，这是点名可用的工具。

**路径 C（效果仍不够时）：LLM 生成配对数据 → qwen3:8b LoRA SFT**
- 用强模型（GPT-4 级或更大 Qwen）生成 (嘈杂转写文本 → 干净 15 字段 JSON) 配对 500-2000 条；
- 关键：**训练输入要用带 ASR 噪声的文本**（用你们的 ASR 错误模式扰动干净文本），让模型学会对转写错误鲁棒。ACL 2024《Speech-based Slot Filling using LLMs》证明：把 ASR 的 N-best 假设喂进 LoRA 微调，可显著提升对 ASR 噪声的鲁棒性。 (https://aclanthology.org/2024.findings-acl.379.pdf)
- qwen3:8b LoRA 在 12GB 上可训（QLoRA 4bit 更稳）。

### 3.4 给老师的一句话回应模板

> "LLM 生成数据在两个层面起作用：对 ASR，LLM 生成粤英混杂医学文本、TTS 合成语音，然后**微调 Whisper 参数**（有真实的反向传播）；对字段抽取 LLM，我们先用固定评测集做提示词迭代（量化靠评测集），必要时用 DSPy/TextGrad 做'文本梯度'式提示词优化，或用 LLM 生成的配对数据对 qwen3 做 LoRA 微调。"

---

## 4. 推荐技术路线（分阶段，含验收标准）

### 阶段 0：评测基建（第 1 周，一切的前提）

没有可信评测，后面所有工作都无法证明有效。

- 人工精标 12 条真实音频的转写（逐句、保留粤英原样），存为 `tests/data/gold_asr/*.json`；
- 建评测脚本：CER（字符级，适合中文）、MER（混杂错误率，MCE 论文定义）、**术语命中率**（15 字段关键词 recall 单独统计）；
- 跑基座模型对照实验（2.6 节 4 个候选），确定微调基座。

**验收**：一条命令输出当前系统在 12 条金标上的三组指标。

### 阶段 1：零训练增益（第 1 周，并行）

- 把 `data/HOTWORDS.csv` 接入 `core/asr_hf_whisper.py` 的 `initial_prompt`（修掉交接文档 P2-13 的死文件问题）；
- 热词表 = 15 字段英文术语 + 中文/粤语说法（从 PRD 和 36800 样例提取）；
- 测 initial_prompt 开/关的指标差。

**验收**：术语命中率提升可测量；无回归。

### 阶段 2：合成数据管线（第 2-3 周）

- 写生成 prompt：few-shot 粤英混杂病理口述，强制 15 字段术语覆盖，多智能体评审；
- 生成 3000-8000 句（覆盖 MACRO/MICRO/诊断三种文体）；
- CosyVoice2 / GPT-SoVITS 多音色合成 → 目标 20-50h；加噪声/变速/变调增强；
- （可选）拉取 MCE 数据集混训。

**验收**：抽样 50 条合成音频用另一个 ASR 回测，CER < 10%（保证合成质量）；术语覆盖率 100%。

### 阶段 3：Whisper 微调（第 3-4 周）

- 基座上 LoRA 微调（whisper-small 可先全参对照）；
- 训练/验证划分：合成数据训练，12 条真实数据**只做最终测试**（或留出 2-3 条做验证）；
- 防遗忘：混入 10-20% Common Voice zh-HK 回放数据；
- 早停 + 验证集选 checkpoint。

**验收**：12 条真实数据上 CER/MER/术语命中率显著优于阶段 1 基线（预期术语命中率大幅提升，整体 CER 降 20%+，参照 MCE 的 35% MER 降幅）。

### 阶段 4：LLM 抽取层迭代（第 3-4 周，并行）

- 建 Pass A/B 评测集（30-50 条 LLM 生成 + 人工核对）；
- 提示词迭代；可选 DSPy/TextGrad 实验（回应老师思路）；
- 若准确率不达标：生成 500-2000 条配对数据 → QLoRA 微调 qwen3:8b。

### 阶段 5：回归集成（第 4-5 周）

- 微调后的 Whisper 权重接回 `repo-cuda` 真实链路（注意走任务 A/B 的 PR 流程）；
- 端到端跑 12 条真实音频：15 字段 + macro/micro 叙事；
- 按 AGENTS.md 审计：无证据字段 `[not mentioned]`、证据时间戳、阻塞可见。

---

## 5. TODO List（可直接分配执行）

| # | 任务 | 产出物 | 验收标准 | 依赖 | 预估 |
|---|---|---|---|---|---|
| T0 | 金标评测集：人工精标 12 条真实音频转写 | `tests/data/gold_asr/` + 标注规范 | 双人核对，粤英原样保留 | 无 | 2 天 |
| T1 | 评测脚本：CER/MER/术语命中率一键输出 | `scripts/eval_asr.py` | 对基座跑出有意义的数 | T0 | 1 天 |
| T2 | 基座对照：whisper-small-yue vs large-v3 vs Whisper-MCE vs SenseVoice | 对照表 | 12 条金标三组指标齐全 | T1 | 1 天 |
| T3 | 热词注入：HOTWORDS.csv → initial_prompt | `core/asr_hf_whisper.py` 补丁 + 测试 | 术语命中率提升且无回归 | T1 | 1 天 |
| T4 | 术语表扩充：15 字段 × 英/中/粤说法 | `data/HOTWORDS.csv` v2 | 覆盖 36800 样例全部术语 | 无 | 1 天 |
| T5 | 合成文本生成器：多智能体 prompt + 评审 checklist | `scripts/gen_synth_text.py` + 3-8k 句 | 术语覆盖 100%，抽检口语化合格 | T4 | 3 天 |
| T6 | TTS 合成：CosyVoice2 多音色 20-50h + 增强 | `data/synth_audio/` | 回测 CER < 10% | T5 | 3 天 |
| T7 | （可选）申请/下载 MCE 数据集并格式对齐 | `data/mce/` | 可加载进训练管线 | 无 | 1 天 |
| T8 | Whisper 微调管线：LoRA/全参 + 回放数据 + 早停 | `scripts/finetune_whisper.py` + 权重 | 12 条金标指标显著优于 T2 最佳基线 | T2,T6 | 4 天 |
| T9 | LLM 抽取评测集 + prompt 迭代 | `tests/data/gold_extract/` + prompt v2 | 字段级 F1 可追踪 | 无 | 3 天 |
| T10 | （可选）DSPy/TextGrad 提示词优化实验 | 实验记录 | 相对手工 prompt 有提升才采纳 | T9 | 2 天 |
| T11 | （可选）qwen3:8b QLoRA SFT（噪声鲁棒配对数据） | 适配器权重 | 字段 F1 超 prompt 基线 | T9 | 3 天 |
| T12 | 微调权重集成回真实链路 + 端到端回归 | PR + 回归报告 | 12 条真实音频端到端通过审计 | T8 + 交接文档任务 A/B | 2 天 |

**优先级说明**：T0-T3 是第一周必须完成的（成本低、信息量大）；T5/T6/T8 是核心攻关；T9 并行；T10/T11 是回应老师思路的可选加分项，**不要在 ASR 主线没跑通前投入**。

---

## 6. 风险与降级方案

| 风险 | 概率 | 应对 |
|---|---|---|
| TTS 合成音频"太干净"，微调后不认真人发音 | 中 | 多音色 + 噪声/混响增强；混训 MCE 真人数据；12 条真实数据始终在测试集把关 |
| LLM 生成的粤英混杂"不像人话" | 中 | few-shot 用真实 12 条的句法模式；评审 agent 按混杂率/语法打分；请粤语母语组员抽检 |
| Whisper-small 容量不够，混杂场景上限低 | 中 | T2 对照会暴露；降级到 large-v3 + LoRA（12GB 可行） |
| MCE 数据授权限制（研究用途） | 低 | 课程项目属研究用途；报告/论文中注明来源；若发商用需联系作者 |
| 微调后通用粤语退化（灾难性遗忘） | 中 | 混 Common Voice zh-HK 回放；LoRA 天然缓解 |
| 医学术语仍出错 | 低-中 | 叠加第 0 层 initial_prompt；或上 trie 加权解码（SIGDIAL 2024 方案） |
| 12 条测试集"被看光"导致过拟合评测 | 中 | 微调选型只用其中 2-3 条做验证；最终报告前一次性测全量；尽早争取补录真实数据 |

---

## 7. 参考文献与资源

**粤英混杂数据集 / 模型**

1. Xie & Chen, *Developing a Multilingual Dataset and Evaluation Metrics for Code-Switching: A Focus on Hong Kong's Polylingual Dynamics*, ICASSP 2025（MCE 数据集 + Whisper-MCE + MADGF）。https://arxiv.org/abs/2310.17953 · https://github.com/Shelton1013/Whisper_MCE
2. *SwitchLingua*（LinguaMaster 框架，LLM 生成 420k 混杂文本，含粤语）。https://arxiv.org/pdf/2506.00087
3. Guo et al., *WenetSpeech-Yue: A Large-scale Cantonese Speech Corpus with Multi-dimensional Annotation*, AAAI 2026。https://arxiv.org/abs/2509.03959
4. *Automatic Speech Recognition Datasets in Cantonese: A Survey and New Dataset*。https://arxiv.org/pdf/2201.02419.pdf
5. CUMIX（CUHK 17h 粤英混杂），综述见 Ganji et al. 2019。https://www.sciencedirect.com/science/article/abs/pii/S0167639318304217

**TTS 合成增强 / 低资源 ASR**

6. Yang et al., *Enhancing Low-Resource ASR through Versatile TTS: Bridging the Data Gap*, ICASSP 2025。https://arxiv.org/pdf/2410.16726
7. Hao et al., *Investigating the role of synthetic data augmentation and training strategies on improving low-resource language ASR*, LREC 2026。https://aclanthology.org/anthology-files/anthology-files/pdf/lrec/2026.lrec-1.442.pdf
8. Bartelds et al., *Making More of Little Data: Improving Low-Resource ASR Using Data Augmentation*, ACL 2023。https://aclanthology.org/2023.acl-long.42/

**热词 / 上下文偏置**

9. *Improving Speech Recognition with Jargon Injection*, SIGDIAL 2024。https://aclanthology.org/2024.sigdial-1.42.pdf
10. Jogi et al., *Improving Rare-Word Recognition of Whisper in Zero-Shot Settings*, 2025。https://arxiv.org/pdf/2502.11572
11. Sun et al., *Can Contextual Biasing Remain Effective with Whisper and GPT-2?* (TCPGen), Interspeech 2023。https://www.isca-archive.org/interspeech_2023/sun23e_interspeech.pdf

**医学 ASR**

12. Banerjee et al., *UNITED-MEDASR: High-precision medical speech recognition through synthetic data and semantic correction*, 2024。https://arxiv.org/abs/2412.00055
13. Danilevskyi et al., *Towards an Accurate Domain-Specific ASR: Transcription for Pathology*, TSD 2025。https://link.springer.com/chapter/10.1007/978-3-032-02548-7_26

**微调方法学**

14. Yang et al., *Adapting Whisper for Parameter-Efficient Code-Switching Speech Recognition via Soft Prompt Tuning*, 2025。（见 research/scholar_csen_asr.csv）
15. Miao, *Enhancing Whisper's Zero-Shot Capabilities for Code-Switching through Fine-Tuning*（large-v3 + MCE 微调硕士论文）, 2025。https://campus-fryslan.studenttheses.ub.rug.nl/665/
16. HF 官方 Whisper LoRA 微调教程。https://github.com/Vaibhavs10/fast-whisper-finetuning

**LLM 层**

17. *Speech-based Slot Filling using Large Language Models*（ASR N-best + LoRA 噪声鲁棒）, ACL Findings 2024。https://aclanthology.org/2024.findings-acl.379.pdf
18. TextGrad（文本梯度优化提示词）。https://github.com/zou-group/textgrad
19. DSPy（程序化提示词优化）。https://github.com/stanfordnlp/dspy

**粤语 TTS**

20. CosyVoice2（支持粤语、zero-shot 克隆，Apache-2.0）。https://github.com/FunAudioLLM/CosyVoice
21. GPT-SoVITS（支持 `yue`）。https://github.com/RVC-Boss/GPT-SoVITS
22. canto-tts（港式粤语+英文混杂，Apache-2.0）。https://github.com/typangaa/canto-tts
